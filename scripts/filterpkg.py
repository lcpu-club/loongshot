#!/usr/bin/env python3

import os
import sys
import argparse
from git import Repo
import dbcmd

REPO_URL = 'https://gitlab.archlinux.org/archlinux/kde-build.git'
KDEBUILD_PATH = os.path.join(os.path.expanduser('~'), 'kde-build')
PACKAGES_DICT = {
    'gear': 'libkexiv2',
    'kf6': 'kcoreaddons',
    'maui': 'mauiman',
    'plasma': 'kwayland',
    'qt5': 'qt5-base',
    'qt6': 'qt6-base'
}

repo_uptodate = False

def ensure_kdebuild_repo():
    global repo_uptodate
    if repo_uptodate:
        return
    try:
        if not os.path.exists(KDEBUILD_PATH):
            parent_dir = os.path.dirname(KDEBUILD_PATH)
            if parent_dir and not os.path.exists(parent_dir):
                os.makedirs(parent_dir, exist_ok=True)
            Repo.clone_from(REPO_URL, KDEBUILD_PATH)
        else:
            repo = Repo(KDEBUILD_PATH)
            origin = repo.remote('origin')
            origin.pull()
        repo_uptodate = True
    except Exception as e:
        print(f"Prepare repo fails: {e}", file=sys.stderr)
        raise

def read_packages_list(file_name):
    if os.path.exists(file_name):
        try:
            packages = []
            with open(file_name, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        packages.append(line)
            return packages
        except Exception as e:
            print(f"Read files fails: {e}", file=sys.stderr)
            raise
    return []

def process_packages_with_kdebuild(task_mgr, input_packages, build_list, repo, nokde=False):
    """
    Checks if packages belong to KDE groups and schedules full group builds if necessary.
    Uses task_mgr to insert tasks.
    """
    full_base_path = os.path.join(KDEBUILD_PATH, 'package-list')

    if not os.path.exists(full_base_path):
        ensure_kdebuild_repo()

    # Create a copy for iteration, though we modify input_packages in place later
    kde_packages = []

    for key, value in PACKAGES_DICT.items():
        if value in input_packages:
            ensure_kdebuild_repo()

            # Read dependencies and optional packages
            file_path_dep = os.path.join(full_base_path, key, "packages-dep")
            kde_packages.extend(read_packages_list(file_path_dep))

            file_path_opt = os.path.join(full_base_path, key, "packages-opt")
            kde_packages.extend(read_packages_list(file_path_opt))

            # Identify missing packages in the current input list
            missings = [pkg for pkg in kde_packages if pkg not in input_packages]

            # Logic: If missing count is low (<3), assume we are adding new packages
            # and schedule the whole KDE group for build.
            if len(missings) < 3:
                # Remove KDE packages from input_packages because we are scheduling
                # them separately via insert_task (or ignoring them if nokde=True)
                for pkg in kde_packages:
                    if pkg in input_packages:
                        input_packages.remove(pkg)

                kdes = ','.join(kde_packages)

                if nokde:
                    # User requested not to build KDE, so we just return True
                    # (after having removed them from input_packages)
                    return True
                else:
                    return task_mgr.insert_task(kdes, build_list, repo)
            else:
                print(f"Missing some pkg: {missings}", file=sys.stderr)

    return True

def filter_package(db_manager, input_pkgs, query_template):
    """
    Filters packages based on a SQL query.
    """
    if not input_pkgs:
        return []

    try:
        # Generate placeholders for IN clause: (%s, %s, %s)
        placeholders = ','.join(['%s'] * len(input_pkgs))
        query = query_template.format(placeholders=placeholders)

        with db_manager.transaction() as cursor:
            cursor.execute(query, tuple(input_pkgs))
            # Set of packages to remove
            to_remove = {row[0] for row in cursor.fetchall()}

        return [s for s in input_pkgs if s not in to_remove]

    except Exception as e:
        print(f"Database Error: {e}", file=sys.stderr)
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Filter out packages not to build.")
    parser.add_argument("-s", "--stag", action="store_true", help="Using staging db.")
    parser.add_argument("-T", "--test", action="store_true", help="Using testing db.")
    parser.add_argument("-k", "--nokde", action="store_true", help="Don't insert KDE packages to task list.")
    parser.add_argument("-l", "--list", type=int, help="List to operate on.", default=1)
    args = parser.parse_args()

    # Read packages from stdin
    pkgs = []
    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break
            line = line.strip()
            if line:
                pkgs.append(line)
        except KeyboardInterrupt:
            break

    if not pkgs:
        return False

    # Initialize Database Connection
    with dbcmd.DatabaseManager() as db_manager:
        task_mgr = dbcmd.TaskManager(db_manager)

        # 1. Filter packages already built/failed (flags & 32768)
        #    and where log_version matches current version
        packages_query = """
        SELECT DISTINCT base FROM packages WHERE flags & 32768 != 0
        AND log_version = x86_version AND base IN ({placeholders})
        """
        pkgs = filter_package(db_manager, pkgs, packages_query)

        # 2. Filter packages in the 'black' group list
        grouplist_query = """
        SELECT base FROM grouplist WHERE group_name='black'
        AND base IN ({placeholders})
        """
        pkgs = filter_package(db_manager, pkgs, grouplist_query)

        # 3. Handle KDE logic
        repo = 1 if args.test else 2 if args.stag else 0
        if not process_packages_with_kdebuild(task_mgr, pkgs, args.list, repo, args.nokde):
            return False

    # Output remaining packages to stdout
    for s in pkgs:
        print(s)

    return True

if __name__ == "__main__":
    try:
        sys.exit(0 if main() else 1)
    except KeyboardInterrupt:
        sys.exit(130)

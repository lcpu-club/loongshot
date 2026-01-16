#!/usr/bin/env python3

import os
from git import Repo
import sys
import argparse
import dbinit
import dbcmd

repo_url = 'https://gitlab.archlinux.org/archlinux/kde-build.git'
kdebuild_path = os.path.join(os.path.expanduser('~'), 'kde-build')
packages_dict = {
    'gear': 'libkexiv2',
    'kf5': 'kcoreaddons5',
    'kf6': 'kcoreaddons',
    'maui': 'mauiman',
    'plasma': 'kwayland',
    'qt5': 'qt5-base',
    'qt6': 'qt6-base'
}
repo_uptodate = False
db_manager = dbcmd.DatabaseManager()

def ensure_kdebuild_repo():
    global repo_uptodate
    if repo_uptodate:
        return
    try:
        if not os.path.exists(kdebuild_path):
            parent_dir = os.path.dirname(kdebuild_path)
            if parent_dir and not os.path.exists(parent_dir):
                os.makedirs(parent_dir, exist_ok=True)
            Repo.clone_from(repo_url, kdebuild_path)
        else:
            repo = Repo(kdebuild_path)
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


def process_packages_with_kdebuild(input_packages, build_list, repo, nokde=False):
    full_base_path = os.path.join(kdebuild_path, 'package-list')

    if not os.path.exists(full_base_path):
        ensure_kdebuild_repo()

    original_packages = input_packages.copy()
    kde_packages = []

    for key, value in packages_dict.items():
        if value in input_packages:
            ensure_kdebuild_repo()
            file_path = os.path.join(full_base_path, key, "packages-dep")
            packages = read_packages_list(file_path)
            if packages:
                kde_packages.extend(packages)
            file_path = os.path.join(full_base_path, key, "packages-opt")
            packages = read_packages_list(file_path)
            if packages:
                kde_packages.extend(packages)

            missings = [pkg for pkg in kde_packages if pkg not in input_packages]
            # rebuild all list
            if len(missings)<3:
                # When adding new packages to the list, compare86 can't find them, just add them here.
                for pkg in kde_packages:
                    if pkg not in missings:
                        input_packages.remove(pkg)
                kdes = ','.join(kde_packages)
                if nokde:
                    return True
                else:
                    return db_manager.insert_task(kdes, build_list, repo)
            else:
                print(f"Missing some pkg: {missings}", file=sys.stderr)

    return True


def filter_package(input_pkgs, query_template):
    if not input_pkgs:
        return []

    try:
        conn = dbinit.get_conn()
        cursor = conn.cursor()
        placeholders = ','.join(['%s'] * len(input_pkgs))

        query = query_template.format(placeholders=placeholders)
        cursor.execute(query, tuple(input_pkgs))
        to_remove = {row[0] for row in cursor.fetchall()}
        cursor.close()
        conn.close()

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

    pkgs = []
    while True:
        line = sys.stdin.readline().strip()
        if not line:
            break
        pkgs.append(line)

    if not pkgs:
        return False

    packages_query = """
    SELECT DISTINCT base FROM packages WHERE flags & 32768 != 0 
    AND log_version = x86_version AND base IN ({placeholders})
    """
    pkgs = filter_package(pkgs, packages_query)

    grouplist_query = """
    SELECT base FROM grouplist WHERE group_name='black'
    AND base IN ({placeholders})
    """
    pkgs = filter_package(pkgs, grouplist_query)
    repo = 1 if args.test else 2 if args.stag else 0
    if not process_packages_with_kdebuild(pkgs, args.list, repo, args.nokde):
        return False

    for s in pkgs:
        print(s)

    return True

if __name__ == "__main__":
    sys.exit(0 if main() else 1)

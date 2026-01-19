#!/usr/bin/env python3

import argparse
import os
import sys
import pyalpm
from pydantic import BaseModel
import dbcmd

class PackageMetadata(BaseModel):
    name: str = None
    base: str = None
    x86_version: str = None
    loong_version: str = None
    x86_testing_version: str = None
    loong_testing_version: str = None
    x86_staging_version: str = None
    loong_staging_version: str = None
    repo: str = None

def load_black_list(db_manager, bl_file, info):
    """Loads banned packages from a file into the database."""
    pkgs = []
    try:
        with open(bl_file, 'r') as f:
            for line in f:
                pkg = line.strip()
                if pkg:
                    if info:
                        pkgs.append((pkg, 'black', info))
                    else:
                        pkgs.append((pkg, 'black'))
    except Exception as e:
        print(f"Error reading blacklist file: {e}", file=sys.stderr)
        return

    if not pkgs:
        return

    with db_manager.transaction() as cursor:
        if info:
            cursor.executemany("INSERT INTO grouplist(base, group_name, info) VALUES (%s, %s, %s)", pkgs)
        else:
            cursor.executemany("INSERT INTO grouplist(base, group_name) VALUES (%s, %s)", pkgs)
        print(f"Inserted {len(pkgs)} packages into the blacklist.")


def load_repo(repo_path, repo):
    """Load the pyalpm repository database."""
    handle = pyalpm.Handle("/", repo_path)
    try:
        db = handle.register_syncdb(repo, 0)
        return db
    except pyalpm.error as e:
        print(f"Failed to load repo {repo_path}: {e}", file=sys.stderr)
        return None


def compare_all(cache_dir, x86_repo_path, loong64_repo_path):
    """Fetch all packages from x86 and loong using pyalpm."""
    pkg_map = {}
    repos = ['core', 'extra', 'core-testing', 'extra-testing', 'core-staging', 'extra-staging']

    for repo in repos:
        x86_db = load_repo(os.path.join(cache_dir, x86_repo_path), repo)
        x86_data = {pkg.name: [pkg.base, pkg.version] for pkg in x86_db.pkgcache} if x86_db else {}

        loong_db = load_repo(os.path.join(cache_dir, loong64_repo_path), repo)
        loong_data = {pkg.name: [pkg.base, pkg.version] for pkg in loong_db.pkgcache} if loong_db else {}

        all_current_names = set(x86_data.keys()) | set(loong_data.keys())

        is_staging = 'staging' in repo
        is_testing = 'testing' in repo
        clean_repo_name = repo.replace('-testing', '').replace('-staging', '')

        for name in all_current_names:
            if name not in pkg_map:
                pkg_map[name] = PackageMetadata(name=name)

            p = pkg_map[name]

            x86_info = x86_data.get(name)
            loong_info = loong_data.get(name)

            # Update Metadata (Base & Repo)
            current_base = x86_info[0] if x86_info else (loong_info[0] if loong_info else None)

            if p.base is None and current_base:
                p.base = current_base

            if p.repo is None:
                p.repo = clean_repo_name

            # Update Versions
            if is_staging:
                if x86_info: p.x86_staging_version = x86_info[1]
                if loong_info: p.loong_staging_version = loong_info[1]
            elif is_testing:
                if x86_info: p.x86_testing_version = x86_info[1]
                if loong_info: p.loong_testing_version = loong_info[1]
            else: # Stable
                if x86_info: p.x86_version = x86_info[1]
                if loong_info: p.loong_version = loong_info[1]

    return list(pkg_map.values())


def fetch_all_packages(db_manager):
    """Syncs the pyalpm package cache with the PostgreSQL database."""
    home_dir = os.path.expanduser("~")
    cache_dir = os.path.join(home_dir, ".cache", "compare86")

    pkglist = compare_all(cache_dir, "x86", "loong")
    print(f"Loaded {len(pkglist)} packages from local cache.")

    # Bit mask (1<<30) is used as a temporary 'touched' flag
    touched_flag = 1 << 30

    with db_manager.transaction() as cursor:
        # Upsert packages
        cursor.executemany('''
            INSERT INTO packages (name, base, repo, flags, x86_version, loong_version,
            x86_testing_version, loong_testing_version, x86_staging_version, loong_staging_version)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (name) DO UPDATE
            SET x86_version = EXCLUDED.x86_version,
                loong_version = EXCLUDED.loong_version,
                x86_testing_version = EXCLUDED.x86_testing_version,
                x86_staging_version = EXCLUDED.x86_staging_version,
                loong_testing_version = EXCLUDED.loong_testing_version,
                loong_staging_version = EXCLUDED.loong_staging_version,
                repo = EXCLUDED.repo,
                base = EXCLUDED.base,
                flags = CASE
                    WHEN packages.flags is NULL then EXCLUDED.flags
                    ELSE packages.flags | EXCLUDED.flags
                END
        ''', [(pkg.name, pkg.base, pkg.repo, touched_flag, pkg.x86_version, pkg.loong_version,
               pkg.x86_testing_version, pkg.loong_testing_version, pkg.x86_staging_version,
               pkg.loong_staging_version) for pkg in pkglist])

        # Delete packages that weren't touched in this sync

        cursor.execute("SELECT name, base FROM packages WHERE flags IS NULL OR flags & %s = 0", (touched_flag,))
        packages_to_delete = cursor.fetchall()
        if packages_to_delete:
            for package in packages_to_delete:
                print(f"{package[0]:<30} {package[1]:<30}")
        cursor.execute("DELETE FROM packages WHERE flags IS NULL OR flags & %s = 0", (touched_flag,))
        print(f"Deleted {cursor.rowcount} stale packages.")

        # Revert the temporary 'touched' flag
        cursor.execute("UPDATE packages SET flags = flags & ~%s", (touched_flag,))


def log_check(db_manager):
    """Check if log files exist for packages and update the DB."""
    base_dir = '/home/arch/loong-status/build_logs'

    # Step 1: Fetch packages without locking the DB during filesystem checks
    with db_manager.transaction() as cursor:
        cursor.execute("SELECT name, loong_version, has_log FROM packages")
        packages = cursor.fetchall()

    updates = []
    nulls = []

    # Step 2: Check filesystem
    for name, loong_version, has_log in packages:
        folder_path = os.path.join(base_dir, name)

        if not os.path.isdir(folder_path):
            nulls.append((name,))
            continue

        log_file_name = f"{has_log}" if has_log is not None else f"{name}-{loong_version}"
        log_file_path = os.path.join(folder_path, log_file_name + ".log")

        if os.path.isfile(log_file_path):
            updates.append((log_file_name, name))
        else:
            nulls.append((name,))

    # Step 3: Batch Update the database
    with db_manager.transaction() as cursor:
        if updates:
            cursor.executemany("UPDATE packages SET has_log = %s WHERE name = %s", updates)
        if nulls:
            cursor.executemany("UPDATE packages SET has_log = NULL WHERE name = %s", nulls)


def main():
    parser = argparse.ArgumentParser(description="Compare packages between x86 and loong.")
    parser.add_argument("-b", "--black", type=str, help="File of banned packages")
    parser.add_argument("-I", "--info", type=str, help="Note for the banned packages")
    parser.add_argument("-S", "--sync", action="store_true", help="Sync the packages table")
    args = parser.parse_args()

    # Use the context manager to ensure clean exit/connection closure
    with dbcmd.DatabaseManager() as db_manager:
        if args.sync:
            fetch_all_packages(db_manager)

        if args.black:
            load_black_list(db_manager, args.black, args.info)

        # log_check(db_manager)

if __name__ == "__main__":
    main()

import argparse
import json
import os
import psycopg2
import pyalpm
import requests
import subprocess

from pydantic import BaseModel

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

def load_config(config_file=None):
    if config_file is None:
        config_file = os.path.join(os.path.expanduser('~'), '.dbconfig.json')
    try:
        with open(config_file, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading configuration file: {e}")
        raise

def get_conn(config_file=None):
    config = load_config(config_file)

    conn = psycopg2.connect(
        dbname=config['database']['name'],
        user=config['database']['user'],
        password=config['database']['password'],
        host=config['database']['host']
    )
    return conn

# Write packages to database
def create_tables(conn):
    cursor = conn.cursor()

    cursor.execute("DROP TABLE IF EXISTS black_list;")
    cursor.execute("DROP TABLE IF EXISTS prebuild_list;")
    cursor.execute("DROP TABLE IF EXISTS build_list;")

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS packages (
        name TEXT PRIMARY KEY,
        base TEXT,
        repo TEXT,
        error_type TEXT,
        has_log TEXT,
        is_blacklisted BOOL DEFAULT FALSE,
        x86_version TEXT,
        x86_testing_version TEXT,
        x86_staging_version TEXT,
        loong_version TEXT,
        loong_testing_version TEXT,
        loong_staging_version TEXT
        )
    ''')

    cursor.execute('''
        CREATE TABLE black_list (
        name TEXT PRIMARY KEY
        )
    ''')

    cursor.close()

def load_black_list(conn, bl_file):
    cursor = conn.cursor()

    with open(bl_file, 'r') as f:
        for line in f:
            name = line.strip()
            if name:
                cursor.execute('INSERT INTO black_list (name) VALUES (%s) ON CONFLICT (name) DO NOTHING', (name,))

    cursor.execute("""
        SELECT name, x86_version, loong_version
        FROM packages
        WHERE name IN (SELECT name FROM black_list);
    """)

    packages_to_check = cursor.fetchall()

    for name, x86_version, loong_version in packages_to_check:
        # Use vercmp to compare versions
        try:
            result = subprocess.run(
                ['vercmp', x86_version, loong_version],
                capture_output=True,
                text=True,
                check=True
            )
            # If x86_version > loong_version, blacklist the package
            if result.stdout.strip() == '1':
                cursor.execute("""
                    UPDATE packages
                    SET is_blacklisted = TRUE
                    WHERE name = %s;
                """, (name,))
        except subprocess.CalledProcessError:
            print(f"Error comparing versions for {name}: {x86_version} vs {loong_version}")

    cursor.close()

# Load the repository database
def load_repo(repo_path, repo):
    handle = pyalpm.Handle("/", repo_path)
    try:
        db = handle.register_syncdb(repo, 0)
        return db
    except pyalpm.error as e:
        print(f"Failed to load repo {repo_path}: {e}")
        return None

# Fetch all packages from x86 and loong, and insert into database
# compare_all in compare86.py only compares package base, but here we need all built packages
def compare_all(cache_dir, x86_repo_path, loong64_repo_path):
    # Key: pkg_name (str), Value: PackageMetadata (obj)
    pkg_map = {}

    repos = ['core', 'extra', 'core-testing', 'extra-testing', 'core-staging', 'extra-staging']

    for repo in repos:
        x86_db = load_repo(os.path.join(cache_dir, x86_repo_path), repo)
        x86_data = {pkg.name: [pkg.base, pkg.version] for pkg in x86_db.pkgcache}

        loong_db = load_repo(os.path.join(cache_dir, loong64_repo_path), repo)
        loong_data = {pkg.name: [pkg.base, pkg.version] for pkg in loong_db.pkgcache}

        all_current_names = set(x86_data.keys()) | set(loong_data.keys())

        is_staging = 'staging' in repo
        is_testing = 'testing' in repo
        clean_repo_name = repo.replace('-testing', '').replace('-staging', '')

        for name in all_current_names:
            if name not in pkg_map:
                pkg_map[name] = PackageMetadata(name=name)

            p = pkg_map[name]

            # Get info for this package from current loop's DBs (or None if missing)
            x86_info = x86_data.get(name)      # [base, ver]
            loong_info = loong_data.get(name)  # [base, ver]

            # --- Update Metadata (Base & Repo) ---
            current_base = None
            if x86_info: current_base = x86_info[0]
            elif loong_info: current_base = loong_info[0]

            if p.base is None and current_base:
                p.base = current_base

            # Set the primary repository (e.g., 'core' or 'extra')
            if p.repo is None:
                p.repo = clean_repo_name

            # --- Update Versions ---
            if is_staging:
                if x86_info: p.x86_staging_version = x86_info[1]
                if loong_info: p.loong_staging_version = loong_info[1]
            elif is_testing:
                if x86_info: p.x86_testing_version = x86_info[1]
                if loong_info: p.loong_testing_version = loong_info[1]
            else: # Stable
                if x86_info: p.x86_version = x86_info[1]
                if loong_info: p.loong_version = loong_info[1]

    # Return the aggregated objects
    return list(pkg_map.values())

def fetch_all_packages(conn):
    home_dir = os.path.expanduser("~")
    cache_dir = os.path.join(home_dir, ".cache", "compare86")

    x86_repo_path = "x86"
    loong64_repo_path = "loong"
    pkglist = compare_all(cache_dir, x86_repo_path, loong64_repo_path)

    cursor = conn.cursor()

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
    ''', [(pkg.name, pkg.base, pkg.repo, (1<<30), pkg.x86_version, pkg.loong_version,
           pkg.x86_testing_version, pkg.loong_testing_version, pkg.x86_staging_version,
           pkg.loong_staging_version) for pkg in pkglist])

    # remove not used packages
    cursor.execute("DELETE FROM packages WHERE flags is NULL or flags & (1<<30) = 0")
    cursor.execute("UPDATE packages SET flags = flags & ~(1<<30)")

    cursor.close()

# Check if log file exists for each package
def log_check(conn):
    cursor = conn.cursor()

    base_dir = '/home/arch/loong-status/build_logs'

    # Fetch all packages with has_log not NULL
    # The basic idea is to check if the log file exists, if not, set has_log to NULL
    # We assume that there is always a log file for a package
    # The log file should has a name identical to value of has_log field
    # If has_log is NULL, we try to use the format {name}-{loong_version}.log to find the log file
    # If the log file is not found, set has_log to NULL
    cursor.execute("SELECT name, loong_version, has_log from packages")
    packages = cursor.fetchall()

    for package in packages:
        name, loong_version, has_log = package
        folder_path = os.path.join(base_dir, name)

        # If the directory does not exist, set has_log to NULL
        if not os.path.isdir(folder_path):
            cursor.execute("""
                UPDATE packages
                SET has_log = NULL
                WHERE name = %s
            """, (name,))
            continue

        # Check for the specific log file
        log_file_name = f"{name}-{loong_version}"
        # Use has_log value if possible
        if has_log is not None:
            log_file_name = f"{has_log}"
        log_file_path = os.path.join(folder_path, log_file_name + ".log")

        if os.path.isfile(log_file_path):
            # If the log file exists, do nothing
            cursor.execute("""
                UPDATE packages
                SET has_log = %s
                WHERE name = %s
            """, (log_file_name, name,))
        else:
            # If the log file does not exist, set has_log to NULL
            cursor.execute("""
                UPDATE packages
                SET has_log = NULL
                WHERE name = %s
            """, (name,))

    cursor.close()

def main():
    parser = argparse.ArgumentParser(description="Compare packages between x86 and loong.")
    parser.add_argument("--bl", type=str, help="Banned packages")
    args = parser.parse_args()

    conn = get_conn()
    try:
        conn.autocommit = False
        fetch_all_packages(conn)
        conn.commit()

        #log_check(conn)
        #conn.commit()
    except Exception as e:
        print(f"Error during database operations: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()

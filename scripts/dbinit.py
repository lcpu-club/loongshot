import argparse
import json
import os
import psycopg2
import pyalpm
import requests
import subprocess

from pydantic import BaseModel

class PackageMetadata(BaseModel):
    name: str = "missing"
    base: str = "missing"
    x86_version: str = "missing"
    loong64_version: str = "missing"
    repo:str = "missing"

def load_config(config_file):
    try:
        with open(config_file, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading configuration file: {e}")
        raise

def get_conn(config):
    config = load_config(config)

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

    cursor.execute(f'''
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

    cursor.execute(f'''
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

# Download repo db from mirrors.
def download_file(source, dest):
    headers = {"User-Agent": "Mozilla/5.0", }
    repo_path = os.path.dirname(dest)
    if not os.path.exists(repo_path):
        os.makedirs(repo_path)
    try:
        # Download the file and save it to dest_path
        response = requests.get(source, headers=headers)
        response.raise_for_status()
        with open(dest, 'wb') as out_file:
            out_file.write(response.content)
    except Exception as e:
        print(f"Error downloading file: {e}")

def update_repo(cache_dir, mirror_x86, x86_repo_path, mirror_loong64, loong64_repo_path):
    for mirror, repo_path in [(mirror_x86, x86_repo_path), (mirror_loong64, loong64_repo_path)]:
        for repo in ["core", "extra"]:
            download_file(f"{mirror}{repo}/os/{repo_path}/{repo}.db",
                        f"{cache_dir}/{repo_path}/sync/{repo}.db")
        
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
    pkglist = []

    for repo in ['core', 'extra']:
        x86 = {}
        loong = {}
        
        x86_db = load_repo(os.path.join(cache_dir, x86_repo_path), repo)
        x86_pkg = {pkg.name: [pkg.base, pkg.version] for pkg in x86_db.pkgcache}
        x86 = {**x86, **x86_pkg}
    
        loong_db = load_repo(os.path.join(cache_dir, loong64_repo_path), repo)
        loong_pkg = {pkg.name: [pkg.base, pkg.version] for pkg in loong_db.pkgcache}
        loong = {**loong, **loong_pkg}

        allpkg = {**loong, **x86}
        for pkg_name in allpkg:
            if pkg_name in x86:
                pkg_base = x86[pkg_name][0]
                x86_version = x86[pkg_name][1]
            else:
                x86_version = 'missing'
            if pkg_name in loong:
                pkg_base = loong[pkg_name][0]
                loong64_version = loong[pkg_name][1]
            else:
                loong64_version = 'missing'
            p = PackageMetadata(
                name=f'{pkg_name}',
                base=f'{pkg_base}',
                x86_version=f'{x86_version}',
                loong64_version=f'{loong64_version}',
                repo=repo
            )
            pkglist.append(p)
    return pkglist

def fetch_all_packages(conn):
    home_dir = os.path.expanduser("~")
    cache_dir = os.path.join(home_dir, ".cache", "loongpkgs")
    mirror_x86 = "https://mirrors.pku.edu.cn/archlinux/"
    mirror_loong64 = "https://loongarchlinux.lcpu.dev/loongarch/archlinux/"

    # Define repo file paths
    x86_repo_path = "x86_64"
    loong64_repo_path = "loong64"
    update_repo(cache_dir, mirror_x86, x86_repo_path, mirror_loong64, loong64_repo_path)
    pkglist = compare_all(cache_dir, x86_repo_path, loong64_repo_path)

    cursor = conn.cursor()

    # If a package is moved from a repo to another, we accept the new one and remove the old one
    # Keep track of the log! If a package has log, it should keep the log unless the new x86_version is not missing and different from loong_version
    cursor.executemany(f'''
        INSERT INTO packages (name, base, x86_version, loong_version, repo, has_log)
        VALUES (%s, %s, %s, %s, %s, NULL) 
        ON CONFLICT (name) DO UPDATE
        SET x86_version = CASE 
                            WHEN EXCLUDED.x86_version = 'missing' THEN packages.x86_version
                            ELSE EXCLUDED.x86_version 
                        END,
            loong_version = EXCLUDED.loong_version,
            repo = EXCLUDED.repo,
            base = EXCLUDED.base,
            has_log = NULL 
        WHERE packages.x86_version <> 'missing' OR EXCLUDED.x86_version <> 'missing';
    ''', [(pkg.name, pkg.base, pkg.x86_version, pkg.loong64_version, pkg.repo) for pkg in pkglist])

    
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
    parser.add_argument( "--db", type=str, help="Database name.")
    parser.add_argument( "--bl", type=str, help="Banned packages")
    args = parser.parse_args()
    
    if args.db is None:
        print("Must provide database name!")
        return
    
    conn = get_conn(args.db)
    try:
        conn.autocommit = False

        # Step 1: Create tables
        create_tables(conn)
        # Step 2: Fetch all packages and insert into database
        fetch_all_packages(conn)
        # Step 3: Load black list and update is_blacklisted field
        if args.bl:
            load_black_list(conn, args.bl)
        # Commit all changes
        conn.commit()

        # Step 4: Check for log files and update has_log field
        log_check(conn)
        conn.commit()
    except Exception as e:
        print(f"Error during database operations: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()
        
if __name__ == "__main__":
    main()

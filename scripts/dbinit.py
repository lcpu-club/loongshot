import argparse
import json
import os
import psycopg2
import pyalpm
import requests
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
        has_log BOOL DEFAULT FALSE,
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
    
    cursor.execute("UPDATE packages SET is_blacklisted = TRUE WHERE name IN (SELECT name FROM black_list);")
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

def fetch_all_packges(conn):
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
        VALUES (%s, %s, %s, %s, %s, 
                CASE WHEN %s <> 'missing' AND %s <> %s THEN FALSE ELSE FALSE END)
        ON CONFLICT (name) DO UPDATE
        SET x86_version = CASE 
                            WHEN EXCLUDED.x86_version = 'missing' THEN packages.x86_version
                            ELSE EXCLUDED.x86_version 
                        END,
            loong_version = EXCLUDED.loong_version,
            repo = EXCLUDED.repo,
            base = EXCLUDED.base,
            has_log = CASE
                        WHEN COALESCE(NULLIF(EXCLUDED.x86_version, 'missing'), packages.x86_version) <> 'missing'
                        AND COALESCE(NULLIF(EXCLUDED.x86_version, 'missing'), packages.x86_version) <> EXCLUDED.loong_version
                        THEN FALSE
                        ELSE packages.has_log
                    END
        WHERE packages.x86_version <> 'missing' OR EXCLUDED.x86_version <> 'missing';
    ''', [(pkg.name, pkg.base, pkg.x86_version, pkg.loong64_version, pkg.repo,
        pkg.x86_version, pkg.x86_version, pkg.loong64_version) for pkg in pkglist])
    
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

        create_tables(conn)
        fetch_all_packges(conn)
        if args.bl:
            load_black_list(conn, args.bl)
        conn.commit()
    except Exception as e:
        print(f"Error during database operations: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()
        
if __name__ == "__main__":
    main()

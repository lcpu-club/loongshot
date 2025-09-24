import argparse
import compare86
import json
import os
import psycopg2

compare_methods=['core_pkg', 'extra_pkg', 'all_pkg', 'build_pkg']

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
def create_tables(db):
    conn = get_conn(db)
    cursor = conn.cursor()

    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS packages (
        name TEXT,
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
        loong_staging_version TEXT,
        PRIMARY KEY (name, repo)
        )
    ''')

    cursor.execute("DROP TABLE IF EXISTS black_list;")

    cursor.execute(f'''
        CREATE TABLE black_list (
        name TEXT PRIMARY KEY
        )
    ''')

    conn.commit()
    cursor.close()
    conn.close()

def load_black_list(db, bl_file):
    conn = get_conn(db)
    cursor = conn.cursor()
    
    with open(bl_file, 'r') as f:
        for line in f:
            name = line.strip()
            if name:
                cursor.execute('INSERT INTO black_list (name) VALUES (%s) ON CONFLICT (name) DO NOTHING', (name,))
    
    cursor.execute("UPDATE packages SET is_blacklisted = TRUE WHERE name IN (SELECT name FROM black_list);")
    conn.commit()
    cursor.close()
    conn.close()

# Fetch all packages from x86 and loong, and insert into database
def fetch_all_packges(db):
    pkglist = compare86.compare_all()
    conn = get_conn(db)
    
    cursor = conn.cursor()

    cursor.executemany(f'''
    INSERT INTO packages (name, base, x86_version, loong_version, repo)
    VALUES (%s, %s, %s, %s, %s)
    ON CONFLICT (name, repo) DO UPDATE
    SET x86_version = EXCLUDED.x86_version,
        loong_version = EXCLUDED.loong_version
    ''', [(pkg.name, pkg.base, pkg.x86_version, pkg.loong64_version, pkg.repo) for pkg in pkglist])
    
    conn.commit()
    cursor.close()
    conn.close()

def main():
    parser = argparse.ArgumentParser(description="Compare packages between x86 and loong.")
    parser.add_argument( "--db", type=str, help="Database name.")
    parser.add_argument( "--bl", type=str, help="Banned packages")
    args = parser.parse_args()
    
    if args.db is None:
        print("Must provide database name!")
        return
    create_tables(args.db)
    fetch_all_packges(args.db)
    if args.bl:
        load_black_list(args.db, args.bl)
        
if __name__ == "__main__":
    main()

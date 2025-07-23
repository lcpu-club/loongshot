import argparse
import sqlite3

compare_methods=['core_pkg', 'extra_pkg', 'all_pkg', 'build_pkg', 'packages']

# Write packages to database
def create_database(db):
    conn = sqlite3.connect(db)
    cursor = conn.cursor()
    # cursor.execute(f'''DROP TABLE IF EXISTS {compare_method} ''')
    # Create a table for each compare method
    for method in compare_methods:
        cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS {method} (
        name TEXT PRIMARY KEY,
        base TEXT,
        repo TEXT,
        x86_version TEXT,
        x86_testing_version TEXT,
        x86_staging_version TEXT,
        loong_version TEXT,
        loong_testing_version TEXT,
        loong_staging_version TEXT
        )
        ''')

    conn.commit()
    cursor.close()
    conn.close()

def main():
    parser = argparse.ArgumentParser(description="Compare packages between x86 and loong.")
    parser.add_argument( "--db", type=str, help="Database name.")
    args = parser.parse_args()
    
    if args.db is None:
        print("Must provide database name!")
        return
    create_database(args.db)

if __name__ == "__main__":
    main()

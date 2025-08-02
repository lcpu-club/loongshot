import argparse
import dbinit
import os
import psycopg2
import subprocess
import time
from pathlib import Path
from psycopg2 import extras

# Define retry triggers
error_type = {
    "Fail to apply loong's patch": ["Fail to apply loong's patch"],
    "Unknown error before build": ["Unknown error before build"],
    "Fail to download source": ["Failure while downloading", "TLS connect error"],
    "Fail to pass the validity check":["Fail to pass the validity check"],
    "Fail to pass PGP check" : ["One or more PGP signatures could not be verified"],
    "Could not resolve all dependencies": ["Could not resolve all dependencies"],
    "Failed in prepare": ["A failure occurred in prepare"],
    "Failed in build": ["A failure occurred in build"],
    "Failed in check": ["A failure occurred in check"],
    "Failed in package": ["A failure occurred in package"],
    "Cannot guess build type": ["configure: error: cannot guess build type"]
}

# Fetch one task from build list
def get_pending_task(db_path, table, task_no):
    conn = dbinit.get_conn(db_path)
    try:
        with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
            cursor.execute(
                f"SELECT * FROM {table} WHERE task_no = %s", (task_no,)
            )
            record = cursor.fetchone()
            cursor.execute(
                f"UPDATE {table} SET status = 'Building' WHERE task_no = %s", (task_no,)
            )
            conn.commit()

            return dict(record) if record else None
    finally:
        conn.close()

# Remove completed build task
def delete_record(db_path: str, record_id: int, error = "Success") -> None:
    conn = dbinit.get_conn(db_path)
    cursor = conn.cursor()

    try:
        cursor.execute("BEGIN TRANSACTION")
        # If build success, update loong_version, otherwise don't
        cursor.execute("""
            INSERT INTO packages(name, base, repo, error_type, x86_version, loong_version)
            SELECT name, base, repo, %s, x86_version, CASE WHEN %s = 'Success' THEN x86_version ELSE loong_version END
            FROM build_list
            WHERE task_no = %s
            ON CONFLICT(name) DO UPDATE SET
            repo = EXCLUDED.repo,
            x86_version = EXCLUDED.x86_version,
            loong_version = EXCLUDED.loong_version
        """, (error, error, record_id,))
        
        cursor.execute(
                f"UPDATE build_list SET status = %s WHERE task_no = %s", (error, record_id,)
            )
        
        conn.commit()

    except psycopg2.Error as e:
        conn.rollback()
        raise RuntimeError(f"Failed: {e}") from e
        
    finally:
        conn.close()

# Execute build 
def execute_with_retry(script_path, db, record, builder):
    attempt = 0 #Retry attempts
    max_retries=3

    command = [
        script_path,
        record['name'],
        "--ver",
        record['x86_version'],
        "--repo",
        record['repo'],
        "--builder",
        builder
    ]

    while attempt < max_retries:
        # Start running script
        process = subprocess.run(
            command,
            text=True
        )
        # An error mask, 0 stands for no error
        mask = 0
        
        # A success build
        if process.returncode == 0:
            delete_record(db, record['task_no'])
            return        

        # When build fails
        need_retry = False
        error = ""
        with open(f"{record['name']}-{record['x86_version']}.log", 'r') as f:
            lines = f.readlines()[-100:]

            # Error handler: Look for retry opportunities
            for line in lines:
                for err, keywords in error_type.items():
                    if any(keyword in line for  keyword in keywords):
                        print(f"Detect retry trigger in logs: {line.strip()} - type: {err}")
                        if err == "Fail to download source":
                            need_retry = True
                            break
                        # TODO: May append extra args
                        elif err == "Fail to pass PGP check":
                            command += ["--","--skippgpcheck"]
                            need_retry = True
                            break
                        else:
                            error = err
                            break
                if need_retry:
                    break
                
        if need_retry:
            attempt += 1
            print(f"Retry attempt {attempt} ...")
            time.sleep(attempt * 5)  
        else:
            print("Failed to build... Now removing task")
            # Error code starts with 1, not 0
            delete_record(db, record['task_no'], error)
            return


def main():
    parser = argparse.ArgumentParser(description='Constantly fetch tasks from build list and run 0build')

    parser.add_argument('--db', nargs=2, metavar=('DB_PATH', 'TABLE_NAME'), help='Database that stores the build list')
    parser.add_argument('--script', type=str, help='Build script to execute')
    parser.add_argument('--builder', type=str, help='Builder machine to use')

    args = parser.parse_args()

    if not args.db:
        print("No database provided!")
        return

    if not args.script:
        print("No build script provided!")
        return

    db = args.db[0]
    table = args.db[1]
    script = args.script
    builder = "localhost"

    if args.builder:
        builder = args.builder
    
    print(f"Database: {db}\nBuild List: {table}\nBuild script: {script}")
    # Create the resulting packages table
    conn = dbinit.get_conn(db)
    cursor = conn.cursor()
    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS packages (
        name TEXT PRIMARY KEY,
        base TEXT,
        repo TEXT,
        error_type TEXT,
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
    task_no = 1
    while True:

        record = get_pending_task(db, table, task_no)

        if not record:
            print("All task completed")
            break

        print(f"\nTask ID={record['task_no']}, name={record['name']}, version={record['x86_version']}")

        try:
            execute_with_retry(script, db, record, builder)  
            task_no += 1      

        except Exception as e:
            print(f"Failed to run script {e}")
            break

if __name__ == "__main__":
    main()

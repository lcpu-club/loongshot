import argparse
import os
import sqlite3
import subprocess
import time
from pathlib import Path

# Define retry triggers
RETRY_TRIGGERS = {
    "Fail to download source": ["Failure while downloading", "TLS connect error"],
    # "Failed to apply patch": ["Fail to apply loong's patch"],
    "Fail to pass PGP check" : ["One or more PGP signatures could not be verified"],
}

# Fetch one task from build list
def get_first_pending_record(db_path, table):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row 
    cursor = conn.cursor()
    
    cursor.execute(f"SELECT * FROM {table} WHERE status = 'pending' ORDER BY task_no LIMIT 1")
    record = cursor.fetchone()
    conn.close()
    
    return dict(record) if record else None


def mark_record_failed(db_path: str, record_id: int) -> None:
    """Mark when failed to build"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("UPDATE build_list SET status = 'failed' WHERE task_no = ?", (record_id,))
    conn.commit()
    conn.close()
    print(f"{record_id} failed to build")

# Remove completed build task
def delete_record(db_path: str, record_id: int) -> None:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        conn.execute("BEGIN TRANSACTION")

        cursor.execute("""
            INSERT INTO packages(name, repo, x86_version, loong_version)  
            SELECT name, repo, x86_version, loong_version
            FROM build_list 
            WHERE task_no = ?
        """, (record_id,))
    
        cursor.execute("DELETE FROM build_list WHERE task_no = ?", (record_id,))
        conn.commit()

    except sqlite3.Error as e:
        conn.rollback()
        raise RuntimeError(f"Failed: {e}") from e
        
    finally:
        conn.close()

# Execute build 
def execute_with_retry(script_path, db, record, builder="localhost", max_retries=3):
    attempt = 0
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
        
        need_retry = False

        # pkgname = record['name']
        with open(f"{record['name']}-{record['x86_version']}.log", 'r') as f:
            lines = f.readlines()[-100:]
        
            # Look for retry opportunities
            for line in lines:
                for error_type, keywords in RETRY_TRIGGERS.items():
                    if any(keyword in line for  keyword in keywords):
                        print(f"Detect retry trigger in logs: {line.strip()} - type: {error_type}")
                        
                        if error_type == "Fail to download source":
                            need_retry = True
                        # TODO: May append extra args
                        elif error_type == "Fail to pass PGP check":
                            command += ["--","--skippgpcheck"]
                            need_retry = True
                        break
                if need_retry:
                    break
        
   
        if process.returncode == 0:
            delete_record(db, record['task_no'])
            break
        elif need_retry:
            attempt += 1
            print(f"Retry attempt {attempt} ...")
            time.sleep(attempt * 5)  
        else:
            mark_record_failed(db, record['task_no'])
            break


def main():
    parser = argparse.ArgumentParser(description='Constantly fetch tasks from build list and run 0build')

    parser.add_argument('--db', nargs=2, metavar=('DB_PATH', 'TABLE_NAME'), help='Database that stores the build list')
    parser.add_argument('--script', type=str, help='Build script to execute')
    parser.add_argument('--builder', type=str, help='Builder machine to use')

    args = parser.parse_args()

    if not args.db:
        print("No arguments provided!")
        return

    db = args.db[0]
    table = args.db[1]
    while True:

        record = get_first_pending_record(Path(db), table)

        if not record:
            print("All task completed")
            break

        print(f"\nTask ID={record['task_no']}, name={record['name']}, version={record['x86_version']}")

        try:
            success = execute_with_retry(args.script, db, record, args.builder)        

        except Exception as e:
            print(f"Failed to run script {e}")
            break

if __name__ == "__main__":
    main()

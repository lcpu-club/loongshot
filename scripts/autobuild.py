import argparse
import os
import sqlite3
import subprocess
import time
from pathlib import Path

# Define retry triggers
RETRY_TRIGGERS = {
    "Network Error": ["Failure while downloading", "TLS connect error", "Could not download sources"],
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

# Execute build 
def execute_script_with_record(script_path: str, record, builder="localhost"):
    print("Start to build")
    try:
        # Build args
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
        
        # Start to build package
        print(f"Args: {command}")
        result = subprocess.run(command, check=True, text=True)
        print(f"Package built successfully.")
        return True

    except subprocess.CalledProcessError as e:
        print(f"Failed to run script, exit code: {e.returncode}")

        return False

def execute_with_retry(script_path, record, builder="localhost", max_retries=3):
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
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )
        
        need_retry = False
        while True:
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            
            print(line, end='')
            if any(keyword in line for keywords in RETRY_TRIGGERS.values() for keyword in keywords):
                print(f"Detect possible retry: {line}")
                process.terminate()
                need_retry = True
                break
            
        if process.returncode == 0:
            return True
        elif need_retry:
            attempt += 1
            print(f"Retry attempt {attempt} ...")
            time.sleep(attempt * 5)  
        else:
            return False
    return False

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
    cursor.execute("DELETE FROM build_list WHERE task_no = ?", (record_id,))
    conn.commit()
    conn.close()

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
            success = execute_with_retry(args.script, record, args.builder)

            if success:       
                delete_record(db, record['task_no'])
            else:
                mark_record_failed(db, record['task_no'])

        except Exception as e:
            print(f"Failed to run script {e}")
            break

if __name__ == "__main__":
    main()

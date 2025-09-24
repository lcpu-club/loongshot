import argparse
import compare86
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
def get_pending_task(db_path, table):
    conn = dbinit.get_conn(db_path)
    try:
        with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
            cursor.execute(
                f"""
                UPDATE {table} 
                SET status = 'Building' 
                WHERE task_no = (
                    SELECT task_no 
                    FROM {table} 
                    WHERE status = 'Pending' 
                    ORDER BY task_no ASC 
                    LIMIT 1 
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING *;
                """
            )
            record = cursor.fetchone()
            conn.commit()

            return dict(record) if record else None
    finally:
        conn.close()

# Remove completed build task
def delete_record(db_path: str, record_id: int, new_loong_version, error = "Success") -> None:
    conn = dbinit.get_conn(db_path)
    cursor = conn.cursor()

    try:
        cursor.execute("BEGIN TRANSACTION")
        # If build success, update loong_version, otherwise don't
        cursor.execute("""
            INSERT INTO packages(name, base, repo, error_type, has_log, x86_version, loong_version)
            SELECT name, base, repo, %s, TRUE, x86_version, CASE WHEN %s = 'Success' THEN %s ELSE loong_version END
            FROM build_list
            WHERE task_no = %s
            ON CONFLICT(name, repo) DO UPDATE SET
            base = EXCLUDED.base,
            repo = EXCLUDED.repo,
            error_type = EXCLUDED.error_type,
            x86_version = EXCLUDED.x86_version,
            loong_version = EXCLUDED.loong_version
        """, (error, error, new_loong_version, record_id,))
        
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

    x86_version = record['x86_version']
    loong_version = record['loong_version']
    x86_pkgver = x86_version.split('-')[0]
    loong_pkgver = loong_version.split('-')[0]

    # If the package is already in loong repo with same version as x86, we need to increment pkgrel
    if x86_pkgver == loong_pkgver:
        base_version, pkgrel = x86_version.rsplit('-', 1)
        current_pkgrel = float(pkgrel)

        # Increment point pkgrel if same version is already built        
        new_pkgrel = current_pkgrel + 0.1
        loong_version = base_version + "-" + str(new_pkgrel)
    # Or update to x86 version
    else:
        loong_version = x86_version

    print(f"Building {record['name']} with x86 version {x86_version} and loong version {loong_version}")

    command = [
        script_path,
        record['name'],
        "--ver",
        loong_version,
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
        
        # A success build
        if process.returncode == 0:
            delete_record(db, record['task_no'], loong_version)
            return        

        # When build fails
        need_retry = False
        error = ""
        with open(f"{record['name']}-{loong_version}.log", 'r') as f:
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
            # If the build succeeds, new loong_version will be used, which might not be the same as the x86_version
            delete_record(db, record['task_no'], loong_version, error)
            return
        
    # If all retries failed, delete the record
    print("Failed after retries... Now removing task")
    delete_record(db, record['task_no'], loong_version, error)

def check_black_list(db):
    conn = dbinit.get_conn(db)
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            DELETE FROM build_list
            WHERE name IN (SELECT name FROM black_list)
            """)
        conn.commit()
        cursor.close()
        conn.close()
    except:
        conn.rollback()
        raise RuntimeError(f"Failed to apply black list")
    
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
        
    # Remove packages that are already in black list
    check_black_list(db)
    while True:

        record = get_pending_task(db, table)

        if not record:
            print("All task completed")
            break

        print(f"\nTask ID={record['task_no']}, name={record['name']}, version={record['x86_version']}")

        try:
            execute_with_retry(script, db, record, builder)  

        except Exception as e:
            print(f"Failed to run script {e}")
            break

if __name__ == "__main__":
    main()

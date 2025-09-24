import argparse
import compare86
import dbinit
import os
import psycopg2
import signal
import subprocess
import sys
import termios
import time
from pathlib import Path
from psycopg2 import extras

# Define retry triggers
error_type = {
    "Fail to apply loong's patch": ["Fail to apply loong's patch"],
    "Unknown error before build": ["Unknown error before build"],
    "Fail to download source": ["Failure while downloading", "TLS connect error", "Could not download sources"],
    "Fail to pass the validity check":["Fail to pass the validity check", "One or more files did not pass the validity check"],
    "Fail to pass PGP check" : ["One or more PGP signatures could not be verified"],
    "Could not resolve all dependencies": ["Could not resolve all dependencies"],
    "Failed in prepare": ["A failure occurred in prepare"],
    "Failed in build": ["A failure occurred in build"],
    "Failed in check": ["A failure occurred in check"],
    "Failed in package": ["A failure occurred in package"],
    "Cannot guess build type": ["configure: error: cannot guess build type"]
}

class BuildControl:
    """
    Handle Ctrl+C to show a simple menu for user to choose action
    """
    def __init__(self):
        self.interrupted = False
        self.action = None

        # Register signal handler
        signal.signal(signal.SIGINT, self._handle_interrupt)
    
    def _handle_interrupt(self, signum, frame):
        """Ctrl+C = 显示菜单"""
        self.interrupted = True
        print("\n\n[s]kip | [q]uit | [Enter]=retry: ", end='', flush=True)
        
        # Set terminal to raw mode to capture single character input
        try:
            choice = input().strip().lower()
            if choice == 's':
                self.action = 'skip'
            elif choice == 'q':
                print("Exiting...")
                self.action = 'quit'
            else:
                self.action = 'retry'
        except EOFError:
            sys.exit(0)

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
    except psycopg2.Error as e:
        conn.rollback()
        raise RuntimeError(f"Database error: {e}") from e
    finally:
        conn.close()

# Remove completed build task
def delete_record(db_path: str, name, record_id: int, new_loong_version, error = "Success") -> None:
    conn = dbinit.get_conn(db_path)
    cursor = conn.cursor()

    try:
        cursor.execute("BEGIN TRANSACTION")
        # Calculate new loong_version and has_log value
        # If build success, update loong_version, otherwise don't
        loong_version_value = new_loong_version if error == "Success" else None
        has_log_value = f"{name}-{loong_version_value}" if loong_version_value else None

        cursor.execute("""
            INSERT INTO packages(name, base, repo, error_type, has_log, x86_version, loong_version)
            SELECT name, base, repo, %s, %s, x86_version, %s
            FROM build_list
            WHERE task_no = %s
            ON CONFLICT (name) DO UPDATE SET
            base = EXCLUDED.base,
            repo = EXCLUDED.repo,
            error_type = EXCLUDED.error_type,
            has_log = EXCLUDED.has_log,
            x86_version = EXCLUDED.x86_version,
            loong_version = EXCLUDED.loong_version
        """, (error, has_log_value, loong_version_value, record_id,))
        
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
    control = BuildControl()
    attempt = 0 # Retry attempts
    max_retries = 3

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
    
    systemd_cmd = [
        "systemd-run",
        "--user",
        "--scope",
        "--collect"
    ]
    unit = f"--unit=loongshot-{record['name']}-{time.time()}"
    script_cmd = [
        script_path,
        record['name'],
        "--ver",
        loong_version,
        "--repo",
        record['repo'],
        "--builder",
        builder,
        "--clean"
    ]

    command = systemd_cmd + [unit] + script_cmd

    process = None
    while attempt < max_retries:
        # Reset control state
        control.interrupted = False
        control.action = None
        need_retry = False

        # Start running script
        process = subprocess.Popen(command, text=True)
        
        while process.poll() is None:
            # If interrupted, handle action
            if control.interrupted and control.action:
                # Stop the systemd service
                subprocess.run(["systemctl", "--user", "stop", unit], 
                                capture_output=True, timeout=60)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                
                if control.action == 'skip':
                    delete_record(db, record['name'], record['task_no'], loong_version, "skipped")
                    return True
                elif control.action == 'quit':
                    delete_record(db, record['name'], loong_version, "QUIT by user")
                    return False 
                else:
                    need_retry = True
                    break
            # Reset control state
            control.interrupted = False  
            control.action = None
   
        time.sleep(1)
                
        # Process finished, check return code
        returncode = process.wait()
        if returncode == 0:
            print("✓ Build successful!")
            delete_record(db, record['name'], record['task_no'], loong_version)
            return        

        # When build fails
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
            delete_record(db, record['name'], record['task_no'], loong_version, error)
            return


    # If all retries failed, delete the record
    print("Failed after retries... Now removing task")
    delete_record(db, record['name'], record['task_no'], loong_version, error)
    
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
            success = execute_with_retry(script, db, record, builder)  
            if success is False:
                print("Exiting program as per user request.")
                break
        except Exception as e:
            print(f"Failed to run script {e}")
            break

if __name__ == "__main__":
    main()

import argparse
import os
import sqlite3
import subprocess
from pathlib import Path

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
def execute_script_with_record(script_path: str, record):
    print("Start to build")
    try:
        # Build args
        command = [
            script_path,
            record['pkgname'],
            record['x86_version']
        ]
        
        # Start to build package
        print(f"Script path {script_path}")
        result = subprocess.run(command, check=True, 
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True)
        print(f"脚本执行成功:\n{result.stdout}")
        return True
    except subprocess.CalledProcessError as e:
        print("Failed")
        print(f"脚本执行失败:\n{e.stderr}")
        return False

def mark_record_failed(db_path: str, record_id: int) -> None:
    """标记记录为失败"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("UPDATE build_list SET status = 'failed' WHERE task_no = ?", (record_id,))
    conn.commit()
    conn.close()
    print(f"记录 {record_id} 已标记为失败状态")

# Remove completed build task
def delete_record(db_path: str, record_id: int) -> None:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM software_versions WHERE id = ?", (record_id,))
    conn.commit()
    conn.close()


parser = argparse.ArgumentParser(description='Constantly fetch tasks from build list and run 0build')

parser.add_argument('--db', nargs=2, metavar=('DB_PATH', 'TABLE_NAME'), help='Database that stores the build list')
parser.add_argument('--script', type=str, help='Build script to execute')

args = parser.parse_args()

if not args.db:
    print("No arguments provided!")
    exit(1)
    
db = args.db[0]
table = args.db[1]
while True:

    record = get_first_pending_record(Path(db), table)
    
    if not record:
        print("All task completed")
        break
    
    print(f"\n处理记录: ID={record['task_no']}, name={record['pkgname']}, version={record['x86_version']}")
        
    try:
        success = execute_script_with_record(args.script, record)
            
        if success:       
            delete_record(db, record['task_no'])
        else:
            # 执行失败，标记为失败并继续下一条
            mark_record_failed(db, record['task_no'])
            
    except Exception as e:
        print(f"Failed to run script {e}")
        break
    

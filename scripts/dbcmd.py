#!/usr/bin/env python3

import argparse
import psycopg2
import json
import os
import sys
from enum import IntFlag
from contextlib import contextmanager

class PkgFlags(IntFlag):
    PATCH     = 1 << 0
    NOCHECK   = 1 << 1
    OLDCONFIG = 1 << 2
    QEMU      = 1 << 3
    HASLOG    = 1 << 4
    SKIPPGP   = 1 << 5
    SKIPHASH  = 1 << 6
    TESTING   = 1 << 7
    STAGING   = 1 << 8
    FAIL      = 1 << 15

BIT_MAP = {
    'patch': PkgFlags.PATCH,
    'nocheck': PkgFlags.NOCHECK,
    'oldconfig': PkgFlags.OLDCONFIG,
    'qemu': PkgFlags.QEMU,
    'haslog': PkgFlags.HASLOG,
    'skippgp': PkgFlags.SKIPPGP,
    'skiphash': PkgFlags.SKIPHASH,
    'testing': PkgFlags.TESTING,
    'staging': PkgFlags.STAGING,
    'fail': PkgFlags.FAIL,
}

ERROR_MESSAGES = [
    "",
    "Fail to apply loong's patch",
    "Unknown error before build",
    "Failure while downloading",
    "One or more files did not pass the validity check",
    "One or more PGP signatures",
    "Could not resolve all dependencies",
    "A failure occurred in prepare",
    "A failure occurred in build",
    "A failure occurred in check",
    "A failure occurred in package",
    "configure: error: cannot guess build type;",
]


class DatabaseManager:
    """Manages the raw database connection and transactions."""

    def __init__(self, config_file=None):
        if config_file is None:
            config_file = os.path.join(os.path.expanduser('~'), '.dbconfig.json')

        self.conn = None
        self.config_file = config_file
        self._connect()

    def _connect(self):
        try:
            with open(self.config_file, 'r') as f:
                config = json.load(f)

            self.conn = psycopg2.connect(
                dbname=config['database']['name'],
                user=config['database']['user'],
                password=config['database']['password'],
                host=config['database']['host']
            )
        except Exception as e:
            print(f"DB Init Error: {e}", file=sys.stderr)
            sys.exit(1)

    def close(self):
        if self.conn:
            self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    @contextmanager
    def transaction(self):
        """Yields a cursor and handles commit/rollback automatically."""
        if self.conn.closed:
            self._connect()

        cursor = self.conn.cursor()
        try:
            yield cursor
            self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            # Re-raise so the logic layer knows something went wrong
            raise e
        finally:
            cursor.close()

# Bit/Flag Operations
class BitManager:
    """Handles package flag bitmasks."""

    def __init__(self, db_manager):
        self.db = db_manager

    def get_bits(self, base):
        try:
            with self.db.transaction() as cursor:
                cursor.execute("SELECT flags FROM packages WHERE base = %s", (base,))
                result = cursor.fetchone()
                return result[0] if result else -1
        except Exception:
            return -2

    def update_bits(self, base, add_bits=0, remove_bits=0):
        try:
            with self.db.transaction() as cursor:
                cursor.execute("SELECT flags FROM packages WHERE base = %s FOR UPDATE", (base,))
                result = cursor.fetchone()

                if result:
                    current_flags = result[0] or 0
                    new_flags = (current_flags | add_bits) & ~remove_bits

                    # Logic: Clear error codes if the Fail bit is removed
                    if (new_flags & PkgFlags.FAIL) == 0:
                        new_flags &= 0xffff

                    cursor.execute("UPDATE packages SET flags = %s WHERE base = %s", (new_flags, base))
                    print(f"Updated flags for '{base}': {new_flags}")
                else:
                    print(f"No entry found for pkgbase '{base}'")
        except Exception as e:
            print(f"Update bits failed: {e}", file=sys.stderr)

# Task Operations
class TaskManager:
    """Handles the build task queue."""

    def __init__(self, db_manager):
        self.db = db_manager

    def insert_task(self, pkgs, tasklist, repo, insert=False, taskno=0):
        pkgbase_list = [pkg.strip() for pkg in pkgs.split(',') if pkg.strip()]
        if not pkgbase_list:
            return False

        try:
            with self.db.transaction() as cursor:
                # 1. Check duplicates
                if not pkgs.startswith('%'):
                    query = "SELECT pkgbase FROM tasks WHERE pkgbase = ANY(%s) AND tasklist!=0"
                    cursor.execute(query, (pkgbase_list,))
                    results = cursor.fetchall()
                    if results:
                        conflict = ", ".join([row[0] for row in results])
                        print(f"Fail: {conflict} already in tasklist.", file=sys.stderr)
                        return False

                # 2. Lock table for atomic ordering calculation
                cursor.execute("LOCK TABLE tasks IN SHARE ROW EXCLUSIVE MODE")

                # 3. Calculate IDs
                cursor.execute("SELECT min(taskno), max(taskno) FROM tasks WHERE tasklist=%s AND info IS NULL", (tasklist,))
                result = cursor.fetchone()
                first, last = result if result else (None, None)

                if first is None:
                    cursor.execute("SELECT max(taskno) FROM tasks WHERE tasklist=%s", (tasklist,))
                    res = cursor.fetchone()
                    first = (res[0] + 1) if res and res[0] is not None else 1
                    last = first - 1

                cursor.execute("SELECT max(taskid) FROM tasks WHERE tasklist=%s", (tasklist,))
                res = cursor.fetchone()
                maxid = (res[0] - 1) if res and res[0] is not None else 0
                if maxid < 1:
                    cursor.execute("SELECT max(taskid) FROM tasks WHERE tasklist!=%s", (tasklist,))
                    res = cursor.fetchone()
                    maxid = res[0] if res and res[0] is not None else 0

                if taskno > first:
                    first = taskno

                # 4. Insert
                if insert:
                    cursor.execute("UPDATE tasks SET taskno=taskno+%s WHERE tasklist=%s AND taskno>=%s",
                                   (len(pkgbase_list), tasklist, first))
                else:
                    first = last + 1

                rows = [(i+first, pkgbase, maxid + 1, tasklist, repo) for i, pkgbase in enumerate(pkgbase_list)]
                insert_query = "INSERT INTO tasks (taskno, pkgbase, taskid, tasklist, repo) VALUES (%s, %s, %s, %s, %s)"
                cursor.executemany(insert_query, rows)
                return True
        except Exception as e:
            print(f"Insert failed: {e}", file=sys.stderr)
            return False

    def remove_task(self, pkgbase, tasklist, remove=False, taskno=0):
        try:
            with self.db.transaction() as cursor:
                if remove or pkgbase.startswith('%'):
                    query = "DELETE FROM tasks WHERE pkgbase=%s AND tasklist=%s"
                    params = [pkgbase, tasklist]
                    if taskno != 0:
                        query += " AND taskno=%s"
                        params.append(taskno)
                    cursor.execute(query, tuple(params))
                    print(f"{cursor.rowcount} task(s) deleted")
                else:
                    # Mark as done logic
                    realbase = pkgbase.split(':')[0]
                    cursor.execute("SELECT flags FROM packages WHERE base = %s", (realbase,))
                    res = cursor.fetchone()
                    flags = res[0] if res else 0

                    done = f"failed:{flags >> 16}" if (flags and flags > 32767) else "done"

                    # Find Log ID
                    cursor.execute("""
                        SELECT id FROM logs
                        WHERE pkgbase=%s AND build_time > NOW() - INTERVAL '1 hour'
                        ORDER BY build_time DESC limit 1
                    """, (realbase,))
                    res = cursor.fetchone()
                    logid = res[0] if res else 0
                    if not res: done = "nolog"

                    cursor.execute("""
                        UPDATE tasks SET info=%s, logid=%s
                        WHERE pkgbase=%s AND tasklist=%s AND info='building'
                    """, (done, logid, pkgbase, tasklist))
        except Exception as e:
            print(f"Remove task failed: {e}", file=sys.stderr)

    def show_task(self, tasklist):
        try:
            with self.db.transaction() as cursor:
                cursor.execute("SELECT pkgbase, info, taskno FROM tasks WHERE tasklist=%s ORDER BY taskno ASC", (tasklist,))
                for row in cursor.fetchall():
                    info = row[1] if row[1] else "waiting"
                    if row[0].startswith('%'): info = "command"

                    if info.startswith("failed:"):
                        try:
                            info = f"failed: {ERROR_MESSAGES[int(info.split(':')[1])]}"
                        except: pass
                    print(f"{row[2]:4} {row[0]:34} {info}")
        except Exception as e:
            print(f"Show task failed: {e}", file=sys.stderr)

    def show_hist(self, hist_no):
        try:
            with self.db.transaction() as cursor:
                cursor.execute("SELECT max(taskid) from tasks")
                res = cursor.fetchone()
                if not res or not res[0]:
                    print("No history in database")
                    return

                target_id = res[0] - hist_no
                cursor.execute("SELECT pkgbase, info, repo FROM tasks WHERE taskid=%s ORDER BY taskno ASC", (target_id,))

                print("pkgbase                            repo       result")
                print("-" * 60)
                for row in cursor.fetchall():
                    repo = ["stable", "testing", "staging"][row[2]] if 0 <= row[2] <= 2 else "unknown"
                    info = row[1]
                    if info and info.startswith("failed:"):
                        try:
                            info = f"failed: {ERROR_MESSAGES[int(info.split(':')[1])]}"
                        except: pass
                    print(f"{row[0]:34} {repo:10} {info}")
        except Exception as e:
            print(f"Show history failed: {e}", file=sys.stderr)

    def get_task(self, tasklist, building=False):
        try:
            with self.db.transaction() as cursor:
                # SKIP LOCKED for concurrency safety
                cursor.execute("""
                    SELECT taskno, pkgbase FROM tasks
                    WHERE tasklist=%s AND info IS NULL
                    ORDER BY taskno ASC LIMIT 1
                    FOR UPDATE SKIP LOCKED
                """, (tasklist,))
                result = cursor.fetchone()

                if result:
                    taskno, pkgbase = result
                    if building and not pkgbase.startswith('%'):
                        cursor.execute("UPDATE tasks SET info='building' WHERE tasklist=%s AND taskno=%s",
                                       (tasklist, taskno))
                    return pkgbase

                # Cleanup and stop logic
                if building:
                    cursor.execute("UPDATE tasks SET tasklist=0 WHERE tasklist=%s AND info IS NOT NULL", (tasklist,))

                cursor.execute("SELECT count(*) from tasks WHERE tasklist!=%s AND tasklist!=0", (tasklist,))
                remain = cursor.fetchone()[0]
                # Wait for other tasklist to finish if remain > 0
                return "%stop" if remain > 0 else None
        except Exception:
            return None

def parse_bits(bit_arg):
    bitmask = 0
    for bit in bit_arg.split(','):
        bit = bit.strip()
        if not bit: continue
        if bit in BIT_MAP:
            bitmask |= BIT_MAP[bit]
        else:
            print(f"Unknown bit: {bit}")
    return bitmask

def parse_args():
    parser = argparse.ArgumentParser(description="Manage loongarch Archlinux package database.")
    subparsers = parser.add_subparsers(dest="command", help="Sub-commands")

    # Bit Command
    bit_parser = subparsers.add_parser("bit", help="Manage bit fields")
    bit_parser.add_argument("--add", type=str, help="Bits to add")
    bit_parser.add_argument("--remove", type=str, help="Bits to remove")
    bit_parser.add_argument("--list", action="store_true", help="List bit names")
    bit_parser.add_argument("--get", action="store_true", help="Get current bitmask")
    bit_parser.add_argument("--show", action="store_true", help="Show meanings")
    bit_parser.add_argument("pkgbase", type=str, nargs='?', help="Pkgbase")

    # Task Command
    task_parser = subparsers.add_parser("task", help="Manage building task")
    task_parser.add_argument("--add", type=str, help="Packages to append")
    task_parser.add_argument("--insert", type=str, help="Packages to insert from top")
    task_parser.add_argument("--show", action="store_true", help="Show queue")
    task_parser.add_argument("--remove", type=str, help="Remove package")
    task_parser.add_argument("--get", action="store_true", help="Get one package")
    task_parser.add_argument("--done", type=str, help="Mark finished")
    task_parser.add_argument("--build", action="store_true", help="Get for build")
    task_parser.add_argument("--list", type=int, default=1)
    task_parser.add_argument("--hist", type=int, default=-1)
    task_parser.add_argument("--stag", action="store_true", help="Staging repo")
    task_parser.add_argument("--test", action="store_true", help="Testing repo")
    task_parser.add_argument("--taskno", type=int, default=0)

    return parser.parse_args()

def main():
    args = parse_args()
    if not args.command:
        print("No command specified. Use --help.")
        return

    if args.command == "bit" and args.list:
        for b in BIT_MAP: print(f" - {b}")
        return

    # Initialize connection and managers
    with DatabaseManager() as db:
        bit_mgr = BitManager(db)
        task_mgr = TaskManager(db)

        if args.command == "bit":
            if not args.pkgbase:
                print("Error: 'pkgbase' required.", file=sys.stderr)
                return

            if args.get or args.show:
                bits = bit_mgr.get_bits(args.pkgbase)
                if args.get: print(bits)
                if args.show:
                    for k, v in BIT_MAP.items():
                        if bits & v: print(k)
                    err = bits >> 16
                    if 0 < err < len(ERROR_MESSAGES): print(ERROR_MESSAGES[err])

            if args.add or args.remove:
                add = parse_bits(args.add) if args.add else 0
                rem = parse_bits(args.remove) if args.remove else 0
                bit_mgr.update_bits(args.pkgbase, add, rem)

        elif args.command == "task":
            repo = 1 if args.test else 2 if args.stag else 0

            if args.add: task_mgr.insert_task(args.add, args.list, repo)
            if args.insert: task_mgr.insert_task(args.insert, args.list, repo, True, args.taskno)
            if args.get:
                print(task_mgr.get_task(args.list, args.build))
            if args.remove: task_mgr.remove_task(args.remove, args.list, True, args.taskno)
            if args.done: task_mgr.remove_task(args.done, args.list)
            if args.show: task_mgr.show_task(args.list)
            if args.hist >= 0: task_mgr.show_hist(args.hist)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)

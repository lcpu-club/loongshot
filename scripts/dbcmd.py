#!/usr/bin/env python3

import argparse
import psycopg2
import json
import os

# Define the bit values for check, fail, and log
BIT_MAP = {
    'patch': 1 << 0,
    'nocheck': 1 << 1,
    'oldconfig': 1 << 2,
    'qemu': 1 << 3,
    'haslog': 1 << 4,
    'skippgp': 1 << 5,
    'skiphash': 1 << 6,
    'testing': 1 << 7,
    'staging': 1 << 8,
    'fail': 1 << 15,
}

error_type = [
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
    def __init__(self, config_file=None):
        # Set the config file to $HOME/.dbconfig.json if not provided
        if config_file is None:
            config_file = os.path.join(os.path.expanduser('~'), '.dbconfig.json')

        try:
            self.config = self.load_config(config_file)
            self.db_name = self.config['database']['name']
            self.db_user = self.config['database']['user']
            self.db_pass = self.config['database']['password']
            self.db_host = self.config['database']['host']
            self.conn = self.get_db_connection()
        except:
            self.conn = None

    def load_config(self, config_file):
        """Loads the configuration from a JSON file."""
        try:
            with open(config_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading configuration file: {e}")
            return {}

    def get_db_connection(self):
        """Establishes and returns a connection to the PostgreSQL database."""
        try:
            conn = psycopg2.connect(
                dbname=self.db_name,
                user=self.db_user,
                password=self.db_pass,
                host=self.db_host
            )
            return conn
        except Exception as e:
            print(f"Error connecting to the database: {e}")
            return None

    def get_bits(self, base):
        """Fetch the bitmask from the database and print the integer value."""
        cursor = self.conn.cursor()

        try:
            # Query to get the bitmask from the database
            cursor.execute("SELECT flags FROM packages WHERE base = %s", (base,))
            result = cursor.fetchone()

            if result:
                return result[0]
            else:
                return -1

        except Exception as e:
            return -2

        finally:
            cursor.close()  # Close the cursor but keep the connection open

    def update_bits(self, base, add_bits=0, remove_bits=0):
        """Update the bitmask in the database for the specified base."""
        cursor = self.conn.cursor()

        try:
            # Fetch the current flags
            cursor.execute("SELECT flags FROM packages WHERE base = %s", (base,))
            result = cursor.fetchone()

            if result:
                current_flags = result[0]
                # Update the flags
                new_flags = (current_flags | add_bits) & ~remove_bits
                if (new_flags & (1 << 15)) == 0:
                    new_flags &= 0xffff
                # Update the database with the new flags
                cursor.execute("UPDATE packages SET flags = %s WHERE base = %s", (new_flags, base))
                self.conn.commit()  # Commit the changes
                print(f"Updated flags for '{base}': {new_flags}")
            else:
                print(f"No entry found for pkgbase '{base}'")

        except Exception as e:
            print(f"Error updating bits: {e}")
            self.conn.rollback()  # Rollback if there's an error

        finally:
            cursor.close()  # Close the cursor but keep the connection open

    def insert_task(self, pkgs, tasklist, repo, insert=False):
        """Insert packages by list of pkgbase."""

        cursor = self.conn.cursor()
        pkgbase_list = pkgs.split(',')
        # Prepare data to insert

        try:
            if not pkgs.startswith('%'): # commands
                query = "SELECT pkgbase FROM tasks WHERE pkgbase = ANY(%s) AND tasklist!=0"
                cursor.execute(query, (pkgbase_list,))
                results = cursor.fetchall()
                if results:
                    conflict = ", ".join([row[0] for row in results])
                    print(f"Fail: {conflict} had been added to the tasklist.")
                    return

            cursor.execute("SELECT min(taskno),max(taskno) FROM tasks WHERE tasklist=%s and info is NULL", (tasklist,))
            result = cursor.fetchone()
            if result:
                first = result[0]
                last = result[1]
            if first is None:
                # when building the last package, all info fields are filled.
                cursor.execute("SELECT max(taskno) FROM tasks WHERE tasklist=%s", (tasklist,))
                result = cursor.fetchone()
                if result:
                    first = result[0]
                if first is None:
                    first = 1
                else:
                    first = first + 1
                last = first - 1
            cursor.execute("SELECT max(taskid) FROM tasks WHERE tasklist=%s", (tasklist,))
            result = cursor.fetchone()
            if result:
                maxid = result[0];
            if maxid is None:
                maxid = 0
            else:
                maxid = maxid - 1
            if maxid < 1:
                cursor.execute("SELECT max(taskid) FROM tasks WHERE tasklist!=%s", (tasklist,))
                result = cursor.fetchone()
                if result:
                    maxid = result[0]
                if maxid is None:
                    maxid = 0

            if insert:
                cursor.execute("UPDATE tasks SET taskno=taskno+%s WHERE tasklist=%s and info is NULL",
                               (len(pkgbase_list), tasklist))
            else:
                first = last + 1
            rows = [(i+first, pkgbase, maxid + 1, tasklist, repo) for i, pkgbase in enumerate(pkgbase_list)]
            # Insert data
            insert_query = "INSERT INTO tasks (taskno, pkgbase, taskid, tasklist, repo) VALUES (%s, %s, %s, %s, %s)"
            cursor.executemany(insert_query, rows)

            # Commit changes and close connection
            self.conn.commit()
        finally:
            cursor.close()

    def remove_task(self, pkgbase, tasklist, remove=False):
        """Removes or done one task from the task list."""
        cursor = self.conn.cursor()
        try:
            if remove or pkgbase.startswith('%'): # commands just delete
                cursor.execute("DELETE FROM tasks WHERE pkgbase=%s and tasklist=%s",
                               (pkgbase, tasklist))
                if cursor.rowcount == 0:
                    print("No package deleted")
            else:
                # get build result from packages database
                realbase = pkgbase.split(':')[0]
                cursor.execute("SELECT flags FROM packages WHERE base = %s", (realbase,))
                results = cursor.fetchone()
                if results:
                    flags = results[0]
                else:
                    flags = 0
                done = f"failed:{flags >> 16}" if flags > 32767 else "done"
                # get build log it from logs database
                cursor.execute("SELECT id FROM logs WHERE pkgbase=%s AND build_time > NOW() - INTERVAL '1 hour' ORDER BY build_time DESC limit 1", (realbase,))
                results = cursor.fetchone()
                if results:
                    logid = results[0]
                else:
                    done = "nolog"
                    logid = 0
                cursor.execute("UPDATE tasks SET info=%s,logid=%s WHERE pkgbase=%s and tasklist=%s",
                    (done, logid, pkgbase, tasklist))
            self.conn.commit()
        finally:
            cursor.close()

    def show_task(self, tasklist):
        """Show the task list."""
        cursor = self.conn.cursor()
        try:
            select_query = "SELECT pkgbase,info FROM tasks WHERE tasklist=%s ORDER BY taskno ASC";
            cursor.execute(select_query, (tasklist,))
            results = cursor.fetchall()
            for row in results:
                info = "waiting" if row[1] is None else row[1]
                if row[0].startswith('%'):
                    info = "command"
                if info.startswith("failed:"):
                    info = f"failed: {error_type[int(info.split(':')[1])]}"
                print(f"{row[0]:34} {info}")
        except Exception as e:
            print(f"An error occurred: {e}")
        finally:
            cursor.close()

    def show_hist(self, hist_no):
        """Show old task list result."""
        cursor = self.conn.cursor()
        try:
            cursor.execute("SELECT max(taskid) from tasks")
            results = cursor.fetchone()
            if results:
                hist_no = results[0] - hist_no
            else:
                print("No history in database")
            select_query = "SELECT pkgbase,info,repo FROM tasks WHERE taskid=%s ORDER BY taskno ASC";
            cursor.execute(select_query, (hist_no,))
            results = cursor.fetchall()
            print("pkgbase                            repo       result")
            print("------------------------------------------------------------")
            for row in results:
                repo = "stable" if row[2] == 0 else "testing" if row[2] == 1 else "staging"
                info = row[1]
                if info and info.startswith("failed:"):
                    info = f"failed: {error_type[int(info.split(':')[1])]}"
                print(f"{row[0]:34} {repo:10} {info}")
        except Exception as e:
            print(f"An error occurred: {e}")
        finally:
            cursor.close()

    def get_task(self, tasklist, building=False):
        """get the row with the minimal taskno and return the pkgbase."""
        cursor = self.conn.cursor()

        try:
            # Find the row with the minimal taskno
            select_query = "SELECT taskno, pkgbase FROM tasks WHERE tasklist=%s and info is NULL ORDER BY taskno ASC LIMIT 1"
            cursor.execute(select_query, (tasklist,))
            result = cursor.fetchone()

            if result:
                taskno = result[0]
                pkgbase = result[1]
                if building and not pkgbase.startswith('%'):
                    cursor.execute("UPDATE tasks SET info=%s WHERE tasklist=%s and taskno=%s",
                                   ("building", tasklist, taskno))
                    self.conn.commit()
                return pkgbase
            else: # Delete the tasks when all done.
                if building:
                    cursor.execute("UPDATE tasks SET tasklist=0 WHERE tasklist=%s and info is not NULL",
                                   (tasklist,))
                    self.conn.commit()
                cursor.execute("SELECT count(*) from tasks WHERE tasklist!=%s and tasklist!=0",
                               (tasklist,))
                result = cursor.fetchone()
                if result:
                    remain = result[0]
                if remain is None:
                    remain = 0
                if remain > 0: # wait for other task to finish
                    return "%stop"
                else:  # all done, can do clean up
                    return None
        except Exception as e:
            # print(f"Error: {e}")
            return None
        finally:
            cursor.close()

    def __del__(self):
        """Destructor to close the database connection."""
        if self.conn:
            self.conn.close()  # Close the connection when the object is destroyed

def parse_bits(bit_arg):
    """Parses a comma-separated list of bits and returns the corresponding bitmask."""
    bitmask = 0
    for bit in bit_arg.split(','):
        bit = bit.strip()
        if len(bit) == 0:
            continue
        if bit in BIT_MAP:
            bitmask |= BIT_MAP[bit]
        else:
            print(f"Unknown bit: {bit}")
    return bitmask


def parse_args():
    """Parses the command-line arguments."""
    parser = argparse.ArgumentParser(description="Manage loongarch Archlinux package database.")

    subparsers = parser.add_subparsers(dest="command", help="Sub-commands")

    # Sub-command: bit
    bit_parser = subparsers.add_parser("bit", help="Manage bit fields")
    bit_parser.add_argument("--add", type=str, help="Bits to add (comma-separated)")
    bit_parser.add_argument("--remove", type=str, help="Bits to remove (comma-separated)")
    bit_parser.add_argument("--list", action="store_true", help="List all available bit names")
    bit_parser.add_argument("--get", action="store_true", help="Get the current bitmask for the pkgbase")
    bit_parser.add_argument("--show", action="store_true", help="Show the meanings of current bitmask for the pkgbase")
    bit_parser.add_argument("pkgbase", type=str, nargs='?', help="The pkgbase to update")

    # Sub-command: task
    task_parser = subparsers.add_parser("task", help="Manage building task")
    task_parser.add_argument("--add", type=str, help="Packages to append (comma-separated)")
    task_parser.add_argument("--insert", type=str, help="Packages to insert from top(comma-separated)")
    task_parser.add_argument("--show", action="store_true", help="Show the packages in queue.")
    task_parser.add_argument("--remove", type=str, help="Remove one package from list")
    task_parser.add_argument("--get", action="store_true", help="Get one package from top")
    task_parser.add_argument("--done", type=str, help="Finished building package from list")
    task_parser.add_argument("--build", action="store_true", help="Get packages for build")
    task_parser.add_argument("--list", type=int, help="The list number to operate on", default=1)
    task_parser.add_argument("--hist", type=int, help="Show list history", default=-1)
    task_parser.add_argument("--stag", action="store_true", help="Add tasks from staging repo")
    task_parser.add_argument("--test", action="store_true", help="Add tasks from testing repo")
    return parser, parser.parse_args()

def main():
    parser, args = parse_args()

    if not any(vars(args).values()):
        parser.print_help()
        return

    if args.command == "bit" and args.list:
        print("Available bits:")
        for bit_name in BIT_MAP.keys():
            print(f" - {bit_name}")
        return

    db_manager = DatabaseManager()
    if not db_manager.conn:
        return
    if args.command == "bit" and (args.get or args.show):
        if args.pkgbase:
            bits = db_manager.get_bits(args.pkgbase)
        else:
            print("Error: 'pkgbase' argument is required for --get.")
        if args.get:
            print(bits)
        if args.show:
            for bit_name in BIT_MAP.keys():
                if (bits & BIT_MAP[bit_name]):
                    print(bit_name)
            err_no = bits >> 16;
            if (err_no > 0) and (err_no < 12):
                print(error_type[err_no])
        return


    if args.command == "bit":
        add_bits = remove_bits = 0

        # Parse the --add argument
        if args.add:
            add_bits = parse_bits(args.add)

        # Parse the --remove argument
        if args.remove:
            remove_bits = parse_bits(args.remove)

        # Update the database with the calculated bitmask
        if args.pkgbase:
            db_manager.update_bits(args.pkgbase, add_bits=add_bits, remove_bits=remove_bits)
        else:
            print("Error: 'pkgbase' argument is required for --add or --remove.")

    if args.command == "task":
        repo = 1 if args.test else 2 if args.stag else 0
        if args.add:
            db_manager.insert_task(args.add, args.list, repo)
        if args.insert:
            db_manager.insert_task(args.insert, args.list, repo, True)
        if args.get:
            print(db_manager.get_task(args.list, args.build))
        if args.remove:
            db_manager.remove_task(args.remove, args.list, True)
        if args.done:
            db_manager.remove_task(args.done, args.list)
        if args.show:
            db_manager.show_task(args.list)
        if args.hist >= 0:
            db_manager.show_hist(args.hist)

if __name__ == "__main__":
    main()

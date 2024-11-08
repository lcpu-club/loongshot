#!/usr/bin/env python3
import sys
import psycopg2
import json
import os
import re

# Define the bit values for check, fail, and log
BIT_MAP = {
    'patch': 1 << 0,
    'nocheck': 1 << 1,
    'oldconfig': 1 << 2,
    'qemu': 1 << 3,
    'haslog': 1 << 4,
    'skippgp': 1 << 5,
    'skiphash': 1 << 6,
    'fail': 1 << 15,
}

builder=""
timecost=0

class DatabaseManager:
    def __init__(self, config_file=None):
        # Set the config file to $HOME/.dbconfig.json if not provided
        if config_file is None:
            config_file = os.path.join(os.path.expanduser('~'), '.dbconfig.json')

        self.config = self.load_config(config_file)
        self.db_name = self.config['database']['name']
        self.db_user = self.config['database']['user']
        self.db_pass = self.config['database']['password']
        self.db_host = self.config['database']['host']
        self.conn = self.get_db_connection()

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
                new_flags = current_flags & ~remove_bits
                new_flags |= add_bits
                # Update the database with the new flags
                cursor.execute("UPDATE packages SET flags=%s,timecost=%s WHERE base=%s", (new_flags, timecost, base))
                self.conn.commit()  # Commit the changes
                print(f"Updated flags for '{base}': {new_flags}")
            else:
                print(f"No entry found for pkgbase '{base}'")

        except Exception as e:
            print(f"Error updating bits: {e}")
            self.conn.rollback()  # Rollback if there's an error

        finally:
            cursor.close()  # Close the cursor but keep the connection open

    def insert_log(self, base, builder="", build_result=0):
        cursor = self.conn.cursor()
        try:
            # Fetch the current flags
            cursor.execute("SELECT id FROM builder WHERE name = %s", (builder,))
            result = cursor.fetchone()

            bid = 1 # unknown builder
            if result:
                bid = result[0]
            cursor.execute("insert into logs(pkgbase,builder,build_result)values(%s,%s,%s)",
                (base, bid, build_result))
            self.conn.commit()  # Commit the changes
        except Exception as e:
            self.conn.rollback()  # Rollback if there's an error

        finally:
            cursor.close()  # Close the cursor but keep the connection open

    def __del__(self):
        """Destructor to close the database connection."""
        if self.conn:
            self.conn.close()  # Close the connection when the object is destroyed



def parse_build_log(log_path):

    flags={'nocheck': 0, 'patch': 0, 'oldconfig': 0, 'haslog': 1, 'skippgp': 0, 'skiphash': 0, 'fail': 1, 'startbuild': 0}
    fail_stage = 0
    global builder
    global timecost
    log_entry = [
        ("nocheck",  r"\x1b.*==>.*\[1m Build with --nocheck"),
        ("patch",    r"\x1b.*==>.*\[1m Loong's patch applied."),
        ("oldconfig",r"\x1b.*==>.*\[1m Updating config."),
        ("fail",     r"\x1b.*==>.*\[1m Finished making:"),
        ("skippgp",  r"\x1b.*==>.*\[1m Build with --skippgpcheck"),
        ("skiphash", r"\x1b.*==>.*\[1m Build with --skipchecksum"),
        ("startbuild", r"\x1b.*==>.*\[1m Building in chroot for"),
    ]
    error_entry = [
        (1, r"\x1b.*==>.*\[1m Fail to apply loong's patch"),
        # No. 2 is reserved for "not start to build" for errors happen before building.
        (3, r"\x1b.*==> ERROR:.*\[1m Failure while downloading"),
        (4, r"\x1b.*==> ERROR:.*\[1m One or more files did not pass the validity check"),
        (5, r"\x1b.*==> ERROR:.*\[1m One or more PGP signatures"),
        (6, r"\x1b.*==> ERROR:.*\[1m Could not resolve all dependencies"),
        (7, r"\x1b.*==> ERROR:.*\[1m A failure occurred in prepare"),
        (8, r"\x1b.*==> ERROR:.*\[1m A failure occurred in build"),
        (9, r"\x1b.*==> ERROR:.*\[1m A failure occurred in check"),
        (10, r"\x1b.*==> ERROR:.*\[1m A failure occurred in package"),
        (11, "configure: error: cannot guess build type;"),
    ]

    try:
        with open(log_path, 'r') as log_file:
            for line in log_file:
                for stage, prefix in log_entry:
                    if re.search(prefix, line):
                        if stage == 'fail':
                            flags[stage] = 0
                        else:
                            flags[stage] = 1
                for idx, err in error_entry:
                    if re.search(err, line):
                        fail_stage = idx;
        # parse the last line
        match = re.search(r'built on (\w+), time cost: (\d+)', line)
        if match:
            builder = match.group(1)
            timecost = match.group(2)
        return flags, fail_stage

    except FileNotFoundError:
        print(f"Error: File '{log_path}' not found.")
        return None, -1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <pkgbase>")
        sys.exit(1)

    pkgbase = sys.argv[1]
    logpath='/home/arch/loong-status/build_logs'
    flags,stage = parse_build_log(f"{logpath}/{pkgbase}/all.log")

    add_bit = 0;
    rm_bit = 0;

    if flags is None:
        quit()
    for bit in flags.keys():
        if not bit in BIT_MAP:
            continue
        if flags[bit] == 0:
            rm_bit |= BIT_MAP[bit]
        else:
            add_bit |= BIT_MAP[bit]
    rm_bit |= (0xff << 16)
    if (flags['startbuild'] == 0) and (stage == 0):
        stage = 2;
    add_bit |= (stage << 16) # Error stage number
    db_manager = DatabaseManager()
    db_manager.update_bits(pkgbase, add_bit, rm_bit)
    db_manager.insert_log(pkgbase, builder, add_bit)

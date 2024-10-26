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
                new_flags = (current_flags | add_bits) & ~remove_bits
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
            print(bid)
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

    flags={'nocheck': 0, 'patch': 0, 'oldconfig': 0, 'haslog': 1, 'skippgp': 0, 'skiphash': 0, 'fail': 1}
    fail_stage = 0
    log_entry = [
        ("nocheck", "==>\x1b[m\x0f\x1b[1m Build with --nocheck"),
        ("patch", "==>\x1b[m\x0f\x1b[1m Loong's patch applied."),
        ("oldconfig", "==>\x1b[m\x0f\x1b[1m Updating config."),
        ("fail", "==>\x1b[m\x0f\x1b[1m Finished making:"),
        ("skippgp", "==>\x1b[m\x0f\x1b[1m Build with --skippgpcheck"),
        ("skiphash", "==>\x1b[m\x0f\x1b[1m Build with --skipchecksum"),
    ]
    error_entry = [
        "==> ERROR:\x1b[m\x0f\x1b[1m Failure while downloading",
        "==> ERROR:\x1b[m\x0f\x1b[1m One or more files did not pass the validity check",
        "==> ERROR:\x1b[m\x0f\x1b[1m One or more PGP signatures",
        "==> ERROR:\x1b[m\x0f\x1b[1m Could not resolve all dependencies",
        "==> ERROR:\x1b[m\x0f\x1b[1m A failure occurred in prepare().",
        "==> ERROR:\x1b[m\x0f\x1b[1m A failure occurred in build().",
        "==> ERROR:\x1b[m\x0f\x1b[1m A failure occurred in check().",
        "==> ERROR:\x1b[m\x0f\x1b[1m A failure occurred in package",
        "configure: error: cannot guess build type; ",
    ]

    try:
        with open(log_path, 'r') as log_file:
            for line in log_file:
                for stage, prefix in log_entry:
                    if prefix in line:
                        if stage == 'fail':
                            flags[stage] = 0
                        else:
                            flags[stage] = 1
                for idx in range(len(error_entry)):
                    if error_entry[idx] in line:
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
        if flags[bit] == 0:
            rm_bit |= BIT_MAP[bit]
        else:
            add_bit |= BIT_MAP[bit]
    rm_bit |= (0xff << 16)
    add_bit |= (stage << 16) # Error stage number
    db_manager = DatabaseManager()
    db_manager.update_bits(pkgbase, add_bit, rm_bit)
    db_manager.insert_log(pkgbase, builder, add_bit)

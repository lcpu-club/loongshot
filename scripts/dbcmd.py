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
    'fail': 1 << 15,
}

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

    def get_bits(self, base):
        """Fetch the bitmask from the database and print the integer value."""
        cursor = self.conn.cursor()

        try:
            # Query to get the bitmask from the database
            cursor.execute("SELECT flags FROM packages WHERE base = %s", (base,))
            result = cursor.fetchone()

            if result:
                flags = result[0]
                print(flags)  # Print the integer value of the bitmask
            else:
                print(f"No entry found for pkgbase '{base}'")

        except Exception as e:
            print(f"Error retrieving bits: {e}")

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
    bit_parser.add_argument("pkgbase", type=str, nargs='?', help="The pkgbase to update")

    # Sub-command: task
    bit_parser = subparsers.add_parser("task", help="Manage building task")

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
    if args.command == "bit" and args.get:
        if args.pkgbase:
            db_manager.get_bits(args.pkgbase)
        else:
            print("Error: 'pkgbase' argument is required for --get.")
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

if __name__ == "__main__":
    main()

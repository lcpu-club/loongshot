#!/usr/bin/env python3
import sys
import re
import os
import dbcmd

LOG_KEY_TO_FLAG = {
    'patch': dbcmd.PkgFlags.PATCH,
    'nocheck': dbcmd.PkgFlags.NOCHECK,
    'oldconfig': dbcmd.PkgFlags.OLDCONFIG,
    'haslog': dbcmd.PkgFlags.HASLOG,
    'skippgp': dbcmd.PkgFlags.SKIPPGP,
    'skiphash': dbcmd.PkgFlags.SKIPHASH,
    'testing': dbcmd.PkgFlags.TESTING,
    'staging': dbcmd.PkgFlags.STAGING,
    'fail': dbcmd.PkgFlags.FAIL,
}

# Regex patterns
LOG_PATTERNS = [
    ("nocheck",    r"\x1b.*==>.*\[1m Build with --nocheck"),
    ("patch",      r"\x1b.*==>.*\[1m Loong's patch applied."),
    ("oldconfig",  r"\x1b.*==>.*\[1m Updating config."),
    ("fail",       r"\x1b.*==>.*\[1m Finished making:"),
    ("skippgp",    r"\x1b.*==>.*\[1m Build with --skippgpcheck"),
    ("skiphash",   r"\x1b.*==>.*\[1m Build with --skipchecksum"),
    ("startbuild", r"\x1b.*==>.*\[1m Building in chroot for"),
]

ERROR_PATTERNS = [
    (1,  r"\x1b.*==>.*\[1m Fail to apply loong's patch"),
    (3,  r"\x1b.*==> ERROR:.*\[1m Failure while downloading"),
    (4,  r"\x1b.*==> ERROR:.*\[1m One or more files did not pass the validity check"),
    (5,  r"\x1b.*==> ERROR:.*\[1m One or more PGP signatures"),
    (6,  r"\x1b.*==> ERROR:.*\[1m Could not resolve all dependencies"),
    (7,  r"\x1b.*==> ERROR:.*\[1m A failure occurred in prepare"),
    (8,  r"\x1b.*==> ERROR:.*\[1m A failure occurred in build"),
    (9,  r"\x1b.*==> ERROR:.*\[1m A failure occurred in check"),
    (10, r"\x1b.*==> ERROR:.*\[1m A failure occurred in package"),
    (11, "configure: error: cannot guess build type;"),
]

def parse_build_log(log_path):
    """
    Parses the log file to extract flags, error stage, builder name, and time cost.
    """
    # Initialize flags state
    # 0 = not present, 1 = present. 'fail' starts as 1 (failed) until proven 0 (success)
    found_flags = {k: 0 for k in LOG_KEY_TO_FLAG.keys()}
    found_flags['fail'] = 1
    found_flags['startbuild'] = 0 # Helper flag, not in DB

    fail_stage = 0
    builder_name = ""
    time_cost = 0

    try:
        with open(log_path, 'r', errors="ignore") as log_file:
            line = ""
            for line in log_file:
                # Check standard flags
                for stage, prefix in LOG_PATTERNS:
                    if re.search(prefix, line):
                        if stage == 'fail':
                            found_flags[stage] = 0 # "Finished making" means success -> fail=0
                        else:
                            found_flags[stage] = 1

                        if stage == 'startbuild':
                            if 'extra-testing' in line:
                                found_flags['testing'] = 1
                            if 'extra-staging' in line:
                                found_flags['staging'] = 1

                # Check error codes
                for idx, err in ERROR_PATTERNS:
                    if re.search(err, line):
                        fail_stage = idx

            # Parse the footer line for builder stats
            # Looks like: "[built|failed] on <buildername>, time cost: <seconds>"
            match = re.search(r'(?:built|failed) on (\w+), time cost: (\d+)', line)
            if match:
                builder_name = match.group(1)
                time_cost = int(match.group(2))

        return found_flags, fail_stage, builder_name, time_cost

    except FileNotFoundError:
        print(f"Error: File '{log_path}' not found.", file=sys.stderr)
        return None, -1, "", 0

def get_logversion(filepath):
    """Extracts package version from the log header."""
    pattern = re.compile(r'\x1b.*==>.*\[1m Making package: (\S+) (\S+)')
    try:
        with open(filepath, 'r', errors='ignore') as file:
            for line in file:
                match = pattern.search(line)
                if match:
                    pkg_name = match.group(1)
                    version = match.group(2)
                    return pkg_name, version
    except FileNotFoundError:
        pass
    return 'no_pkg_version_found', 'null'

def update_database_from_log(db_manager, pkgbase, add_bits, rm_bits, builder_name, raw_time, log_ver):
    """
    Performs all database updates in a single transaction.
    """
    try:
        with db_manager.transaction() as cursor:
            # 1. Get Builder Info (ID and Time Scale)
            cursor.execute("SELECT id, time_scale FROM builder WHERE name = %s", (builder_name,))
            res = cursor.fetchone()

            builder_id = 1 # Default to unknown/generic
            scale = 1.0

            if res:
                builder_id = res[0]
                if res[1] is not None:
                    scale = res[1]

            final_timecost = raw_time * scale

            # 2. Update Package Flags and Timecost
            cursor.execute("SELECT flags FROM packages WHERE base = %s FOR UPDATE", (pkgbase,))
            res = cursor.fetchone()

            if res:
                current_flags = res[0] or 0
                new_flags = (current_flags & ~rm_bits) | add_bits

                cursor.execute(
                    "UPDATE packages SET flags=%s, timecost=%s WHERE base=%s",
                    (new_flags, final_timecost, pkgbase)
                )

                # 3. Update Log Version if applicable
                if log_ver:
                    cursor.execute("UPDATE packages SET log_version=%s WHERE base=%s", (log_ver, pkgbase))

                print(f"Updated '{pkgbase}': Flags={new_flags}, Time={final_timecost}")
            else:
                print(f"Warning: No package entry found for '{pkgbase}'")

            # 4. Insert into Logs
            cursor.execute(
                "INSERT INTO logs (pkgbase, builder, build_result) VALUES (%s, %s, %s)",
                (pkgbase, builder_id, add_bits)
            )

    except Exception as e:
        print(f"Database update failed: {e}", file=sys.stderr)
        # Transaction context handles rollback

def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <pkgbase>")
        sys.exit(1)

    pkgbase = sys.argv[1]
    # Configuration for paths
    log_base_path = '/home/arch/loong-status/build_logs'
    full_log_path = f"{log_base_path}/{pkgbase}/all.log"

    # 1. Parse Text Logs
    flags, stage, builder_name, time_cost = parse_build_log(full_log_path)

    if flags is None:
        sys.exit(1)

    # 2. Calculate Bitmasks
    add_bit = 0
    rm_bit = 0

    for key, is_set in flags.items():
        if key not in LOG_KEY_TO_FLAG:
            continue

        flag_val = LOG_KEY_TO_FLAG[key]
        if is_set == 0:
            rm_bit |= flag_val
        else:
            add_bit |= flag_val

    # Handle Error Codes (stored in high bits)
    # Clear existing error code (0xff << 16)
    rm_bit |= (0xff << 16)

    # If it didn't start building and no specific error stage was found, assume stage 2
    if (flags['startbuild'] == 0) and (stage == 0):
        stage = 2

    # Set new error code
    add_bit |= (stage << 16)

    # 3. Get Version Info
    log_pkg_name, version = get_logversion(full_log_path)
    version_to_update = version if log_pkg_name == pkgbase else None

    # 4. Database Operations
    with dbcmd.DatabaseManager() as db_manager:
        update_database_from_log(
            db_manager,
            pkgbase,
            add_bit,
            rm_bit,
            builder_name,
            time_cost,
            version_to_update
        )

if __name__ == "__main__":
    main()

"""The `dbcmd.py bit` sub-command: read and write the package flag bits.

The flag definitions, the bit names and the error messages live in dbcmd.py,
which is the entry point and the shared core; this module only implements the
operations on them.
"""

import sys


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
                    if (new_flags & dbcmd.PkgFlags.FAIL) == 0:
                        new_flags &= 0xffff

                    cursor.execute("UPDATE packages SET flags = %s WHERE base = %s", (new_flags, base))
                    print(f"Updated flags for '{base}': {new_flags}")
                else:
                    print(f"No entry found for pkgbase '{base}'")
        except Exception as e:
            print(f"Update bits failed: {e}", file=sys.stderr)


def parse_bits(bit_arg):
    bitmask = 0
    for bit in bit_arg.split(','):
        bit = bit.strip()
        if not bit: continue
        if bit in dbcmd.BIT_MAP:
            bitmask |= dbcmd.BIT_MAP[bit]
        else:
            print(f"Unknown bit: {bit}")
    return bitmask

# dbcmd imports this module in turn, so it comes last: the classes above read
# its names at call time, never while they are being defined.
import dbcmd

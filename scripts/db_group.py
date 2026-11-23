"""The `dbcmd.py group` sub-command: the named lists in the grouplist table.

A group is a name plus the pkgbases in it (`bigmem` for the builders, `black`
for filterpkg.py, ...), optionally with a note.  The connection handling lives
in dbcmd.py, which is the entry point and the shared core; this module only
implements the operations on the table.
"""

import sys


class GroupManager:
    """Handles the package groups stored in the grouplist table."""

    def __init__(self, db_manager):
        self.db = db_manager

    @staticmethod
    def parse_pkgs(pkgs):
        """Split a --add/--remove argument: 'a, b' -> ['a', 'b'], duplicates dropped."""
        return list(dict.fromkeys(
            pkg.strip() for pkg in (pkgs or '').split(',') if pkg.strip()))

    def list_groups(self):
        """Print every group name with the number of packages in it."""
        try:
            with self.db.transaction() as cursor:
                cursor.execute("""
                    SELECT group_name, count(*)
                    FROM grouplist
                    GROUP BY group_name
                    ORDER BY group_name
                """)
                rows = cursor.fetchall()
        except Exception as e:
            print(f"List groups failed: {e}", file=sys.stderr)
            return

        if not rows:
            print("No group in database")
            return
        for group_name, count in rows:
            print(f"{group_name:22} {count}")

    def list_packages(self, group_name, info=None):
        """Print the packages of one group, in pkgbase order.

        `info` keeps only the packages whose note contains it, ignoring case;
        packages without a note never match.
        """
        query = "SELECT base, info FROM grouplist WHERE group_name=%s"
        params = [group_name]
        if info:
            query += " AND info ILIKE %s"
            params.append(f"%{info}%")
        query += " ORDER BY base"

        try:
            with self.db.transaction() as cursor:
                cursor.execute(query, tuple(params))
                rows = cursor.fetchall()
        except Exception as e:
            print(f"List group failed: {e}", file=sys.stderr)
            return

        if not rows:
            if info:
                print(f"No package in group '{group_name}' with info matching '{info}'")
            else:
                print(f"No package in group '{group_name}'")
            return
        for base, note in rows:
            print(f"{base:34} {note}" if note else base)

    def add_packages(self, group_name, pkgs, info=None):
        """Add packages to a group, skipping the ones already in it."""
        bases = self.parse_pkgs(pkgs)
        if not bases:
            print("Error: '--add' requires package names.", file=sys.stderr)
            return

        try:
            with self.db.transaction() as cursor:
                # grouplist has no unique constraint, so a repeated --add would
                # otherwise leave the package in the group twice.
                cursor.execute("SELECT base FROM grouplist"
                               " WHERE group_name=%s AND base = ANY(%s)",
                               (group_name, bases))
                present = {row[0] for row in cursor.fetchall()}
                new = [base for base in bases if base not in present]

                if new and info:
                    cursor.executemany(
                        "INSERT INTO grouplist(base, group_name, info)"
                        " VALUES (%s, %s, %s)",
                        [(base, group_name, info) for base in new])
                elif new:
                    cursor.executemany(
                        "INSERT INTO grouplist(base, group_name) VALUES (%s, %s)",
                        [(base, group_name) for base in new])
        except Exception as e:
            print(f"Add group packages failed: {e}", file=sys.stderr)
            return

        print(f"Added {len(new)} package(s) to group '{group_name}'")
        if len(new) < len(bases):
            print(f"Skipped {len(bases) - len(new)} package(s) already in the group")

    def remove_packages(self, group_name, pkgs):
        """Remove packages from a group."""
        bases = self.parse_pkgs(pkgs)
        if not bases:
            print("Error: '--remove' requires package names.", file=sys.stderr)
            return

        try:
            with self.db.transaction() as cursor:
                cursor.execute("DELETE FROM grouplist"
                               " WHERE group_name=%s AND base = ANY(%s)",
                               (group_name, bases))
                removed = cursor.rowcount
        except Exception as e:
            print(f"Remove group packages failed: {e}", file=sys.stderr)
            return

        print(f"{removed} package(s) removed from group '{group_name}'")

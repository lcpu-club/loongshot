#!/usr/bin/env python3
"""Manage the loongarch Archlinux package database.

This file is the entry point and the shared core: the connection handling, the
package flag bits, the error messages and the build dependency index live here.
The sub-commands are implemented in db_bit.py (`bit`), db_task.py (`task`) and
db_group.py (`group`) on top of it.
"""

import argparse
import glob
import psycopg2
import json
import os
import re
import sys
from enum import IntFlag
from contextlib import contextmanager

if __name__ == '__main__':
    # db_bit and db_task import this module for the shared core below.  Run
    # as a script this module is called __main__, so let that import find it
    # instead of loading a second copy.
    sys.modules['dbcmd'] = sys.modules['__main__']

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

# x86_64 pacman sync databases used to resolve build dependencies.  Every
# builder must look at the same snapshot; compare86.py refreshes it before a
# build run starts.
DEPDB_DEFAULT = os.path.join(os.path.expanduser('~'), '.cache', 'compare86', 'x86')
DEP_REPOS = ('core', 'extra', 'core-testing', 'extra-testing',
             'core-staging', 'extra-staging')

# Key of the advisory lock that serializes task picking between builders.
PICK_LOCK_KEY = 0x1d0b

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

def dep_name(spec):
    """Strip a version constraint: 'libfoo>=1.2' -> 'libfoo'."""
    return re.split(r'[<>=]', spec, maxsplit=1)[0]


def parse_pkgbase(entry):
    """Split a task entry into (pkgbase, nocheck).

    Entries look like 'foo', 'foo:nocheck', 'foo:1.2-3' or
    'foo:1:1.2-3:nocheck'; only the first field is the pkgbase.
    """
    parts = entry.split(':')
    return parts[0], 'nocheck' in parts[1:]


class DepIndex:
    """Build dependency lookup taken from the x86_64 pacman sync databases.

    A queued package may only be built once the packages it needs at build
    time (depends + makedepends + checkdepends) are built as well.  Only
    names matter here, versions do not: a dependency is irrelevant unless its
    provider is queued too.
    """

    def __init__(self, dbpath=None):
        try:
            import pyalpm
        except ImportError:
            raise RuntimeError("pyalpm is required to resolve build dependencies")

        dbpath = dbpath or os.environ.get('DEPDB', DEPDB_DEFAULT)
        handle = pyalpm.Handle('.', dbpath)

        self.real = {}                      # package name -> pkgbase
        self.provides = {}                  # provide name -> {pkgbase}
        self.kinds = {}                     # pkgbase -> {kind: {dep specs}}
        self._cache = {}                    # (pkgbase, nocheck) -> {pkgbase}
        self._closure = {}                  # (pkgbase, runtime) -> {pkgbase}
        self._rev = {}                      # pkgbase -> {pkgbase} (runtime rdeps)
        self._rdeps = {}                    # pkgbase -> {pkgbase}

        available = {os.path.basename(f)[:-3]
                     for f in glob.glob(os.path.join(dbpath, 'sync', '*.db'))}
        provides = []
        for repo in [r for r in DEP_REPOS if r in available]:
            try:
                db = handle.register_syncdb(repo, 0)
            except pyalpm.error as e:
                print(f"Skip dep db {repo}: {e}", file=sys.stderr)
                continue
            for pkg in db.pkgcache:
                base = pkg.base
                self.real[pkg.name] = base
                kinds = self.kinds.setdefault(
                    base, {k: set() for k in
                           ('depends', 'makedepends', 'checkdepends')})
                for kind in kinds:
                    kinds[kind] |= set(getattr(pkg, kind) or ())
                provides.append((base, pkg.provides))

        # Silently ignoring the dependencies would build packages in the wrong
        # order, so a missing/empty database is an error; set DEPDB or run
        # compare86.py first.
        if not self.real:
            raise RuntimeError(f"no package database found in {dbpath}/sync")

        # A dependency name may be satisfied by a real package or by a
        # provider; only fall back to providers when no real package exists.
        for base, specs in provides:
            for spec in specs or ():
                name = dep_name(spec)
                if name and name not in self.real:
                    self.provides.setdefault(name, set()).add(base)

    def dep_bases(self, base, nocheck=False, runtime=False):
        """All pkgbases `base` needs before it can be built.

        runtime=True only follows what the package links against.  The
        build and check dependencies have to be there to build it, but they
        are not part of its package: a rebuild of a tool it used at build
        time (`fmt` makedepends on `mkdocs-material` for its docs) does not
        invalidate its result.
        """
        key = (base, nocheck, runtime)
        if key in self._cache:
            return self._cache[key]

        kinds = self.kinds.get(base, {})
        specs = set(kinds.get('depends', ()))
        if not runtime:
            specs |= set(kinds.get('makedepends', set()))
            if not nocheck:
                specs |= kinds.get('checkdepends', set())

        deps = set()
        for spec in specs:
            name = dep_name(spec)
            if name in self.real:
                deps.add(self.real[name])
            else:
                deps |= self.provides.get(name, set())
        deps.discard(base)

        self._cache[key] = frozenset(deps)
        return self._cache[key]

    def runtime_rdeps(self, base):
        """Packages whose soname changes when `base` is rebuilt.

        Rebuilding a package can change the soname it exports; everything
        that links it, directly or through another library, then has to be
        rebuilt too.  Only runtime dependencies matter here - a package that
        merely used `base` to build is unaffected.

        `is_haskell()` decides whether that applies at all: a non-haskell
        rebuild keeps the soname it gets from the upstream version info.
        """
        if not self._rev:
            for b in self.kinds:
                for d in self.dep_bases(b, runtime=True):
                    self._rev.setdefault(d, set()).add(b)
        if base not in self._rdeps:
            seen, frontier = set(), {base}
            while frontier:
                nxt = set()
                for x in frontier:
                    for r in self._rev.get(x, ()):
                        if r not in seen:
                            seen.add(r)
                            nxt.add(r)
                frontier = nxt
            self._rdeps[base] = frozenset(seen)
        return self._rdeps[base]

    def is_haskell(self, base):
        """Whether rebuilding `base` can change the soname it exports.

        Haskell libraries embed the GHC package ABI hash in the soname
        (libHSfoo-<ver>-<abi>-ghc<ver>.so), so every rebuild breaks the
        packages linking them.  The marker is a runtime dependency on ghc,
        exactly what genrebuild's is_haskell() uses (its --haskell-check
        filter, is_arch_haskell(), also drops arch=any packages): ghc-libs is a
        subpackage of ghc, so normalisation turns "depends ghc-libs" into the
        pkgbase "ghc".  A package that merely uses ghc as a build tool carries
        no libHS, and a rebuilt non-haskell package keeps the soname from its
        version info.  ghc itself is not haskell either (it does not depend on
        its own pkgbase), same as in genrebuild, which handles it through
        --ignore ghc,ghc-static.
        """
        return "ghc" in self.dep_bases(base, runtime=True)

    def chroot_bases(self, base):
        """Everything installed when `base` is built.

        Its dependencies of any kind, plus everything those link against:
        pacman installs the runtime closure of what the build needs, not the
        build dependencies of those tools.
        """
        out = set()
        for d in self.dep_bases(base):
            out.add(d)
            out |= self.dep_closure(d, runtime=True)
        return out

    def dep_closure(self, base, runtime=False):
        """Everything `base` needs, directly or through another package."""
        key = (base, runtime)
        if key not in self._closure:
            seen, frontier = set(), set(self.dep_bases(base, runtime=runtime))
            while frontier:
                seen |= frontier
                frontier = set().union(
                    *(self.dep_bases(b, runtime=runtime) for b in frontier)) - seen
            self._closure[key] = frozenset(seen)
        return self._closure[key]


_dep_index = None


def get_dep_index():
    global _dep_index
    if _dep_index is None:
        _dep_index = DepIndex()
    return _dep_index


# The sub-commands live in their own modules; db_bit and db_task import this
# one back for the core names, so they are imported last.
from db_bit import BitManager, parse_bits
from db_task import TaskManager
from db_group import GroupManager


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
    task_parser.add_argument("--block", nargs='?', const='', metavar='PKGBASE',
                             help="Show the failed tasks that keep waiting tasks out;"
                                  " with a pkgbase, one line for that failed task")
    task_parser.add_argument("--cost", action="store_true", help="Show queue by time cost")
    task_parser.add_argument("--remove", type=str, help="Remove package")
    task_parser.add_argument("--get", action="store_true", help="Get one package")
    task_parser.add_argument("--done", type=str, help="Mark finished")
    task_parser.add_argument("--build", action="store_true", help="Get for build")
    task_parser.add_argument("--list", type=int, default=1)
    task_parser.add_argument("--hist", type=int, default=-1)
    task_parser.add_argument("--stag", action="store_true", help="Staging repo")
    task_parser.add_argument("--test", action="store_true", help="Testing repo")
    task_parser.add_argument("--taskno", type=int, default=0)
    task_parser.add_argument("--eta", action="store_true", help="Show ETA for remaining tasks")
    task_parser.add_argument("--small", action="store_true",
                             help="With --get: skip packages in the bigmem group")

    # Group Command
    group_parser = subparsers.add_parser("group", help="Manage package groups")
    group_parser.add_argument("--add", action="store_true",
                              help="Add --pkg to the group")
    group_parser.add_argument("--remove", action="store_true",
                              help="Remove --pkg from the group")
    group_parser.add_argument("--list", action="store_true",
                              help="List the packages of the group")
    group_parser.add_argument("--list_group", action="store_true",
                              help="List all group names")
    group_parser.add_argument("--pkg", type=str, help="Packages, comma separated")
    group_parser.add_argument("--info", type=str,
                              help="Note stored with --add, or matched by --list")
    group_parser.add_argument("group_name", type=str, nargs='?', help="Group name")

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
        group_mgr = GroupManager(db)

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
                print(task_mgr.get_task(args.list, args.build, args.small))
            if args.remove: task_mgr.remove_task(args.remove, args.list, True, args.taskno)
            if args.done: task_mgr.remove_task(args.done, args.list, False, args.taskno)
            if args.show: task_mgr.show_task(args.list)
            if args.block is not None:
                task_mgr.show_block(args.list, args.block or None)
            if args.hist >= 0: task_mgr.show_hist(args.hist)
            if args.cost: task_mgr.show_task_by_cost(args.list)
            if args.eta: task_mgr.show_eta(args.list)

        elif args.command == "group":
            if args.list_group:
                group_mgr.list_groups()

            if args.list or args.add or args.remove:
                if not args.group_name:
                    print("Error: 'group_name' required.", file=sys.stderr)
                    return

                if args.list: group_mgr.list_packages(args.group_name, args.info)
                if args.add: group_mgr.add_packages(args.group_name, args.pkg, args.info)
                if args.remove: group_mgr.remove_packages(args.group_name, args.pkg)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)

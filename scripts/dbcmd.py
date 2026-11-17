#!/usr/bin/env python3

import argparse
import glob
import psycopg2
import json
import os
import re
import sys
from datetime import datetime, timedelta
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
                cursor.execute("SELECT min(taskno) FROM tasks WHERE tasklist=%s AND info IS NULL", (tasklist,))
                res = cursor.fetchone()
                first = res[0] if res and res[0] is not None else None

                if first is None:
                    cursor.execute("SELECT max(taskno) FROM tasks WHERE tasklist=%s", (tasklist,))
                    res = cursor.fetchone()
                    first = (res[0] + 1) if res and res[0] is not None else 1

                cursor.execute("SELECT max(taskid) FROM tasks WHERE tasklist=%s", (tasklist,))
                res = cursor.fetchone()
                maxid = (res[0] - 1) if res and res[0] is not None else 0
                if maxid < 1:
                    cursor.execute("SELECT max(taskid) FROM tasks WHERE tasklist!=%s", (tasklist,))
                    res = cursor.fetchone()
                    maxid = res[0] if res and res[0] is not None else 0

                # 4. Insert
                if insert:
                    # Insert at the requested position, shifting every row at or
                    # after it (regardless of info/state) to make room.
                    if taskno > 0:
                        first = taskno
                    cursor.execute("UPDATE tasks SET taskno=taskno+%s WHERE tasklist=%s AND taskno>=%s",
                                   (len(pkgbase_list), tasklist, first))
                else:
                    # Append after the highest taskno in this tasklist, including
                    # finished/failed rows, so we never collide with them.
                    cursor.execute("SELECT max(taskno) FROM tasks WHERE tasklist=%s", (tasklist,))
                    res = cursor.fetchone()
                    first = (res[0] + 1) if res and res[0] is not None else 1

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

                    if taskno == 0:
                        cursor.execute("""
                            UPDATE tasks SET info=%s, logid=%s
                            WHERE pkgbase=%s AND tasklist=%s AND info='building'
                        """, (done, logid, pkgbase, tasklist))
                    else:
                        cursor.execute("""
                            UPDATE tasks SET info=%s, logid=%s
                            WHERE pkgbase=%s AND tasklist=%s AND taskno=%s
                        """, (done, logid, pkgbase, tasklist, taskno))
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

    def show_task_by_cost(self, tasklist):
        try:
            with self.db.transaction() as cursor:
                cursor.execute("""
                    SELECT p.name, p.timecost, t.taskno
                    FROM tasks t
                    JOIN packages p ON t.pkgbase=p.name
                    WHERE t.tasklist=%s AND t.info IS NULL
                    ORDER BY p.timecost DESC NULLS LAST
                """, (tasklist,))
                for row in cursor.fetchall():
                    name = row[0]
                    timecost = row[1] if row[1] is not None else "N/A"
                    taskno = row[2]
                    print(f"{taskno:5} {name:34} {timecost}")
        except Exception as e:
            print(f"Show task by cost failed: {e}", file=sys.stderr)

    def show_eta(self, tasklist):
        try:
            with self.db.transaction() as cursor:
                cursor.execute("""
                    SELECT SUM(p.timecost) AS total_timecost
                    FROM tasks t
                    JOIN packages p ON t.pkgbase = p.name
                    WHERE t.tasklist = %s AND t.info IS NULL
                """, (tasklist,))
                result = cursor.fetchone()
                total_seconds = result[0] if result and result[0] is not None else 0

                if total_seconds == 0:
                    print("No remaining tasks or no time cost data available.")
                else:
                    hours = int(total_seconds // 3600)
                    minutes = int((total_seconds % 3600) // 60)
                    seconds = int(total_seconds % 60)
                    end_time = (datetime.now() + timedelta(seconds=total_seconds)).strftime("%Y-%m-%d %H:%M:%S")
                    print(f"ETA: {hours:02d}:{minutes:02d}:{seconds:02d} (total: {total_seconds} seconds)")
                    print(f"Expected end time: {end_time}")
        except Exception as e:
            print(f"Show ETA failed: {e}", file=sys.stderr)

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

    def show_block(self, tasklist):
        """Print why the waiting tasks in front of the running ones wait.

        A failed task is not finished: the operator fixes the package and sets
        the row back to waiting, and until then its dependents would only be
        built against the old package.  This names the failed row behind each
        waiting row a builder skipped over, so it can be handled first.  Only
        rows in front of the first `building` row are reported: the ones behind
        it are not what the builders passed over.
        """
        try:
            with self.db.transaction() as cursor:
                cursor.execute("SELECT taskno, pkgbase, info FROM tasks WHERE tasklist=%s ORDER BY taskno ASC",
                               (tasklist,))
                rows = cursor.fetchall()

            failed = {}             # pkgbase -> [(taskno, info)]
            waiting = []            # (taskno, pkgbase, nocheck)
            first_building = None
            for taskno, pkgbase, info in rows:
                base, nocheck = parse_pkgbase(pkgbase)
                if info is None:
                    if not pkgbase.startswith('%'):
                        waiting.append((taskno, base, nocheck))
                elif info == 'building':
                    if first_building is None:
                        first_building = taskno
                elif info.startswith('failed:'):
                    failed.setdefault(base, []).append((taskno, info))

            report = []
            if waiting and failed:
                dep_index = get_dep_index()
                failed_bases = set(failed)
                # pkgbase of a skipped row in front -> the failed pkgbases that
                # keep it (and therefore everything below it) out
                blocked = {}
                for taskno, base, nocheck in waiting:
                    if first_building is not None and taskno > first_building:
                        break
                    deps = dep_index.dep_bases(base, nocheck)
                    roots = set(deps & failed_bases)
                    if base in failed_bases:
                        # another pass of this pkgbase failed
                        roots.add(base)
                    for dep in deps:
                        roots |= blocked.get(dep, set())
                    if roots:
                        blocked[base] = roots
                        report.append((taskno, base, sorted(roots)))

            if not report:
                print("No waiting task is blocked by a failed task.")
                return

            print("task pkgbase                            blocked by")
            print("-" * 72)
            for taskno, base, roots in report:
                why = ", ".join(f"{root} (task {no}, {info})"
                                for root in roots for no, info in failed[root])
                print(f"{taskno:4} {base:34} {why}")
        except Exception as e:
            print(f"Show blocked tasks failed: {e}", file=sys.stderr)

    def get_task(self, tasklist, building=False):
        """Pick the next task to build in a way that is safe for parallel builders.

        The tasklist order is authoritative (genrebuild already sorted it and
        broke dependency cycles on the way), so the earliest waiting task wins.
        A task is skipped while

        * a pkgbase it depends on (depends + makedepends + checkdepends, taken
          from the x86_64 sync databases) has an unfinished task *in front of
          it*, i.e. a lower taskno that is still waiting or building, or one
          that failed - a failure is fixed by hand and its row set back to
          waiting, and until then a dependent would only be built against the
          old package and have to be rebuilt afterwards.  A failed row blocks
          from behind as well, since the row stays where it is; the retry
          reuses it, so it is not blocked by itself.
        * the same pkgbase is already building, or an earlier instance of it is
          still waiting (some packages are built several times, e.g. a first
          :nocheck pass), or
        * a task of the same wave in front of it is exposed to this package
          being rebuilt: one that is still waiting and whose build would
          install a package that links this one, or one that is being built
          and either links this one or has such a package installed in its
          build environment.  Only for packages whose rebuild can change the
          soname they export (see is_haskell()), which means haskell: their
          soname embeds the GHC ABI hash, and everything installed afterwards
          fails with "broken packages must be rebuilt before they can be
          used" until the reverse dependencies are rebuilt.  A non-haskell
          rebuild keeps its soname and its reverse dependencies are ordered
          behind it, so there is nothing to wait for.

        The wave is the part of the list between the previous build of the
        same package and this one: earlier passes have already been ordered
        against each other, and for a package built only once the whole list
        in front of it counts.

        A task that is merely waiting does not block: it is built after this
        one, so it gets the new build.  In this wave check, finished rows (done,
        failed, nolog) do not block either: their build is over, so the rebuild
        cannot break it, and the list has already ordered the reverse
        dependencies behind this one.

        Waiting and building tasks are in front of the candidate, so the queue
        can always make progress by starting them.  A failed task is different:
        only the operator can unblock it, so a task held back by one is reported
        as '%stop' instead of being built against a package that is about to be
        rebuilt.

        Only earlier tasks are considered, which keeps dependencies pointing
        backwards in time: a cycle broken by the sorter cannot deadlock the
        queue, because whatever blocks a task is either a waiting task in front
        of it (eventually started), a build in progress (eventually finished), or
        a failed task, which stops the queue for the operator instead of hanging
        silently.  A single builder still walks the list in exactly the written
        order.

        Returns the task entry, '%wait' when nothing may start right now because
        another builder is working or the tasklist could not be read, '%stop'
        when the run cannot continue without the operator (a failed task keeps
        the remaining ones out), or None when the tasklist is really finished.
        """
        try:
            with self.db.transaction() as cursor:
                # Serialize picking between builders: the decision below must
                # see a consistent picture of what is pending/building.
                cursor.execute("SELECT pg_advisory_xact_lock(%s, %s)",
                               (PICK_LOCK_KEY, tasklist))
                cursor.execute("SELECT taskno, pkgbase, info FROM tasks WHERE tasklist=%s ORDER BY taskno ASC",
                               (tasklist,))
                rows = cursor.fetchall()

                pending = []
                pending_bases = set()
                busy_bases = set()
                failed_bases = set()
                busy = False
                bases = []          # pkgbase of every row, in list order
                previous = []       # row of the previous build of that pkgbase
                last = {}
                for i, (taskno, pkgbase, info) in enumerate(rows):
                    base, nocheck = parse_pkgbase(pkgbase)
                    bases.append(base)
                    previous.append(last.get(base, -1))
                    last[base] = i
                    if info is None:
                        pending.append((i, taskno, pkgbase, base, nocheck))
                        if not pkgbase.startswith('%'):
                            pending_bases.add(base)
                    elif info == 'building':
                        busy_bases.add(base)
                        busy = True
                    elif info.startswith('failed:'):
                        # Unfinished too: the package is fixed by hand and its
                        # row is set back to waiting, so a dependent built now
                        # would only have to be rebuilt afterwards.  The retry
                        # reuses the same row, so there is no duplicate to worry
                        # about.
                        failed_bases.add(base)

                dep_index = get_dep_index() if pending_bases else None
                # Bases of unfinished tasks seen so far.  The ones in front are
                # the ordering rules below; the initially added busy and failed
                # bases cover rows *behind* the candidate as well, which
                # genrebuild's topological order should never need (a dependency
                # behind its dependent only comes from a hand-edited or resumed
                # list).  That part is defensive: for genrebuild's own lists it
                # changes no pick, but it keeps a broken order from running two
                # related builds at once.
                earlier = set(busy_bases) | failed_bases
                chosen = None
                for i, taskno, pkgbase, base, nocheck in pending:
                    # Command entries ('%...') are not packages and keep their
                    # place in the queue, exactly like before.
                    if pkgbase.startswith('%'):
                        chosen = (taskno, pkgbase)
                        break
                    # `base in earlier` is the one-build-per-pkgbase rule.  It
                    # is defensive: a repeated pkgbase normally sits inside a
                    # wave whose dependency edges serialise the instances, and
                    # only adjacent repeats need this check (an entry of a
                    # manual loop_list order next to the pass2 rebuild of the
                    # same package).  It still has to stay: buildbot.sh closes a
                    # task with `task --done <pkgbase>`, whose SQL marks *every*
                    # 'building' row of that pkgbase as finished, so two live
                    # builds of one pkgbase would corrupt the queue.
                    blocked = (base in earlier or
                               dep_index.dep_bases(base, nocheck) & earlier)
                    if not blocked:
                        # A rebuild can change the soname of this package, and
                        # then everything that links it has to be rebuilt too.
                        # Skip the task while a task of this wave in front of it
                        # would be exposed to that change:
                        #
                        # * still waiting: its build would install a package
                        #   linking this one.  This is the run 1027 failure (13
                        #   builds died on a broken ansi-terminal in their
                        #   chroots) and the only part of this rule that pays
                        #   for itself; it costs parallelism, which is accepted.
                        # * already building: its own package links this one, so
                        #   its result would be stale as soon as this lands, or
                        #   its build environment has such a package installed.
                        #   The chroot is a private copy whose dependencies are
                        #   installed when the build starts, so the real exposure
                        #   is only the window between handing the task out and
                        #   installing them; the queue cannot see that window, so
                        #   it assumes the worst.  Behind the window the wait
                        #   only avoids a build that would have to be redone.
                        # Only a haskell rebuild can change the soname it
                        # exports (see is_haskell()); anything else keeps it,
                        # and its reverse dependencies are ordered behind it by
                        # genrebuild, so there is nothing to be exposed to.
                        risky = (dep_index.runtime_rdeps(base)
                                 if dep_index.is_haskell(base) else frozenset())
                        if risky:
                            for j in range(previous[i] + 1, i):
                                state = rows[j][2]
                                if state is None:
                                    exposed = dep_index.chroot_bases(bases[j]) & risky
                                elif state == 'building':
                                    exposed = (bases[j] in risky or
                                               dep_index.chroot_bases(bases[j]) & risky)
                                else:
                                    # finished, or failed: nothing of that row
                                    # can break any more.  A haskell failure
                                    # stops every builder anyway (buildbot.sh
                                    # inserts %stop), so failures never need to
                                    # be a wave blocker; the dependency rule
                                    # takes care of the rest.
                                    continue
                                if exposed:
                                    blocked = True
                                    break
                    if blocked:
                        earlier.add(base)
                        continue
                    chosen = (taskno, pkgbase)
                    break

                if chosen is not None:
                    taskno, pkgbase = chosen
                    if building and not pkgbase.startswith('%'):
                        cursor.execute("UPDATE tasks SET info='building' WHERE tasklist=%s AND taskno=%s",
                                       (tasklist, taskno))
                    return pkgbase

                if busy:
                    # Somebody is still building: that may unblock what is left.
                    return "%wait"
                if pending:
                    # Nobody is building and nothing can start: what is left
                    # waits for a failed task to be dealt with (fixed, then its
                    # row set back to waiting by hand).  Stop with an error so
                    # that the master does not move the build repo as if the run
                    # had finished; `task --block` names the failed ones.
                    return "%stop"

                # Cleanup and stop logic
                if building:
                    cursor.execute("UPDATE tasks SET tasklist=0 WHERE tasklist=%s AND info IS NOT NULL", (tasklist,))

                cursor.execute("SELECT count(*) from tasks WHERE tasklist!=%s AND tasklist!=0", (tasklist,))
                remain = cursor.fetchone()[0]
                # Wait for other tasklist to finish if remain > 0
                return "%stop" if remain > 0 else None
        except Exception as e:
            # Never report 'finished' on an error: the master builder would
            # move the built packages into the repo while other builders are
            # still running.  Report 'wait' rather than 'stop' so that a
            # transient database or dependency index problem looks like what
            # it is (keep polling, error on stderr) instead of a request to
            # stop the run.
            print(f"Get task failed, retrying: {e}", file=sys.stderr)
            return "%wait"

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
    task_parser.add_argument("--block", action="store_true",
                             help="Show the waiting tasks a failed task keeps out")
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
            if args.done: task_mgr.remove_task(args.done, args.list, False, args.taskno)
            if args.show: task_mgr.show_task(args.list)
            if args.block: task_mgr.show_block(args.list)
            if args.hist >= 0: task_mgr.show_hist(args.hist)
            if args.cost: task_mgr.show_task_by_cost(args.list)
            if args.eta: task_mgr.show_eta(args.list)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)

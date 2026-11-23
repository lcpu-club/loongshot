"""The `dbcmd.py task` sub-command: the build task queue.

The database connection, the flag bits, the error messages and the build
dependency index live in dbcmd.py, which is the entry point and the shared
core; this module only implements the queue operations on top of them.
"""

import sys
from datetime import datetime, timedelta


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
                            info = f"failed: {dbcmd.ERROR_MESSAGES[int(info.split(':')[1])]}"
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
                            info = f"failed: {dbcmd.ERROR_MESSAGES[int(info.split(':')[1])]}"
                        except: pass
                    print(f"{row[0]:34} {repo:10} {info}")
        except Exception as e:
            print(f"Show history failed: {e}", file=sys.stderr)

    def show_block(self, tasklist, only=None):
        """Print the failed tasks that keep waiting tasks out of the queue.

        A failed task is not finished: the operator fixes the package and sets
        the row back to waiting, and until then its dependents would only be
        built against the old package.  This names each failed task that holds
        others back, the waiting rows a builder already skipped over for it
        (the ones in front of the first `building` row), and how many further
        waiting rows in the queue it will hold back.  A dependency chain is
        reported under its root cause: a task kept out only through another
        waiting task is attributed to the failed task behind that one.

        `only` names the failed pkgbase to report and reduces the output to
        one line: `pkgbase failed, will block N more tasks`.  A builder passes
        the package it just failed; the failure with the newest log is not
        used, since another builder's failure may be newer.
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
                base, nocheck = dbcmd.parse_pkgbase(pkgbase)
                if info is None:
                    if not pkgbase.startswith('%'):
                        waiting.append((taskno, base, nocheck))
                elif info == 'building':
                    if first_building is None:
                        first_building = taskno
                elif info.startswith('failed:'):
                    failed.setdefault(base, []).append((taskno, info))

            latest = None
            if only is not None:
                # The pkgbase may appear several times (a :nocheck pass, a
                # retry): report it only if one of its rows really failed.
                latest, _ = dbcmd.parse_pkgbase(only)
                if latest not in failed:
                    print(f"No failed task for {latest} in the queue.")
                    return

            held = {}               # failed pkgbase -> waiting rows kept out
            skipped = {}            # failed pkgbase -> [rows a builder skipped]
            if waiting and failed:
                dep_index = dbcmd.get_dep_index()
                failed_bases = set(failed)
                if latest is not None:
                    failed_bases &= {latest}
                # pkgbase of a skipped row -> the failed pkgbases that keep it
                # (and therefore everything below it) out
                blocked = {}
                for taskno, base, nocheck in waiting:
                    deps = dep_index.dep_bases(base, nocheck)
                    roots = set(deps & failed_bases)
                    if base in failed_bases:
                        # another pass of this pkgbase failed
                        roots.add(base)
                    for dep in deps:
                        roots |= blocked.get(dep, set())
                    if not roots:
                        continue
                    blocked[base] = roots
                    for root in roots:
                        held[root] = held.get(root, 0) + 1
                        if first_building is None or taskno < first_building:
                            skipped.setdefault(root, []).append(base)

            if latest is not None:
                print(f"{latest} failed, will block {held.get(latest, 0)}"
                      " more tasks in queue")
                return

            if not held:
                print("No waiting task is blocked by a failed task.")
                return

            for root in sorted(held, key=lambda b: failed[b][0][0]):
                info = failed[root][0][1]
                try:
                    code = int(info.split(':', 1)[1])
                    reason = (dbcmd.ERROR_MESSAGES[code]
                              if 0 < code < len(dbcmd.ERROR_MESSAGES) else '')
                except (IndexError, ValueError):
                    reason = ''
                names = skipped.get(root, [])
                print(f"{root} ({reason or info})")
                print("    blocks: " +
                      (", ".join(names) if names else "(none)"))
                print(f"    will block {held[root] - len(names)} more tasks in queue")
        except Exception as e:
            print(f"Show blocked tasks failed: {e}", file=sys.stderr)

    def get_task(self, tasklist, building=False, small=False):
        """Pick the next task to build in a way that is safe for parallel builders.

        The tasklist order is authoritative (genrebuild already sorted it and
        broke dependency cycles on the way), so the earliest waiting task wins.
        A task is skipped while

        * `small` is set and the package is in the 'bigmem' group of the
          grouplist table: it needs a big-memory machine, so this builder
          leaves it for one.  The task keeps its place in the list and its
          dependents behind it are held back as if it were building, so they
          are never built against the old package;
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
        another builder is working, a --small builder is holding back for a
        big-memory one, or the tasklist could not be read, '%stop'
        when the run cannot continue without the operator (a failed task keeps
        the remaining ones out), or None when the tasklist is really finished.
        """
        try:
            with self.db.transaction() as cursor:
                # Serialize picking between builders: the decision below must
                # see a consistent picture of what is pending/building.
                cursor.execute("SELECT pg_advisory_xact_lock(%s, %s)",
                               (dbcmd.PICK_LOCK_KEY, tasklist))
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
                    base, nocheck = dbcmd.parse_pkgbase(pkgbase)
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

                dep_index = dbcmd.get_dep_index() if pending_bases else None
                # Bases that need a big-memory machine.  The group is small,
                # so read it whole; only a --small builder filters on it.
                bigmem = set()
                if small:
                    cursor.execute("SELECT base FROM grouplist"
                                   " WHERE group_name='bigmem'")
                    bigmem = {row[0] for row in cursor.fetchall()}
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
                    # A --small builder leaves the bigmem packages to a
                    # big-memory one.  Held back like a blocked task: its
                    # dependents behind it wait for it instead of building
                    # against the old package.
                    if base in bigmem:
                        earlier.add(base)
                        continue
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
                    if small and not failed_bases:
                        # Nothing waits for the operator: without a failed task
                        # the only reason nothing can start is a bigmem package
                        # this --small builder leaves to a big-memory one, so
                        # wait for it (another builder is not required to be
                        # building right now for it to exist).
                        return "%wait"
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

# dbcmd imports this module in turn, so it comes last: the classes above read
# its names at call time, never while they are being defined.
import dbcmd

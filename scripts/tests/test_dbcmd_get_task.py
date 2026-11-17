#!/usr/bin/env python3
"""Regression tests for dbcmd.TaskManager.get_task and dbcmd.DepIndex.

get_task() decides which task a builder gets when several builders work on the
same tasklist.  The important properties are:

  * a package is only started once the packages it needs (depends +
    makedepends + checkdepends) that are queued *in front of it* are finished,
  * the same pkgbase never runs twice at the same time,
  * a package is not rebuilt while a task of its wave in front of it is
    exposed to the soname change (the haskell ABI problem, run 1027),
  * the queue makes progress and ends with %stop/None, never with a silent
    %wait deadlock.

The tests use the real DepIndex together with a hand-written pacman sync
database, so both halves of the decision are exercised; only the PostgreSQL
task queue is faked (it is a small SQL surface).

Run on an Arch Linux machine (pyalpm is required):

    python3 -m pytest scripts/tests/test_dbcmd_get_task.py -v
"""

import random
import sys
import tarfile
from contextlib import contextmanager
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import dbcmd


# --------------------------------------------------------------------------
# Fake task queue
# --------------------------------------------------------------------------

class FakeCursor:
    """Implements exactly the SQL that TaskManager.get_task() issues."""

    def __init__(self, db):
        self.db = db
        self.rows = []
        self.rowcount = 0

    def execute(self, sql, params=()):
        stmt = " ".join(sql.split())
        self.rows = []
        self.rowcount = 0

        if stmt.startswith("SELECT pg_advisory_xact_lock"):
            return

        if stmt.startswith("SELECT taskno, pkgbase, info FROM tasks"
                           " WHERE tasklist=%s ORDER BY taskno ASC"):
            (tasklist,) = params
            self.rows = [(t["taskno"], t["pkgbase"], t["info"])
                         for t in sorted(self.db.tasks, key=lambda t: t["taskno"])
                         if t["tasklist"] == tasklist]
            return

        if stmt.startswith("UPDATE tasks SET info='building'"
                           " WHERE tasklist=%s AND taskno=%s"):
            tasklist, taskno = params
            for t in self.db.tasks:
                if t["tasklist"] == tasklist and t["taskno"] == taskno:
                    t["info"] = "building"
                    self.db.last_picked = taskno
                    self.rowcount += 1
            return

        if stmt.startswith("UPDATE tasks SET tasklist=0"
                           " WHERE tasklist=%s AND info IS NOT NULL"):
            (tasklist,) = params
            for t in self.db.tasks:
                if t["tasklist"] == tasklist and t["info"] is not None:
                    t["tasklist"] = 0
                    self.rowcount += 1
            return

        if stmt.startswith("SELECT count(*) from tasks"
                           " WHERE tasklist!=%s AND tasklist!=0"):
            (tasklist,) = params
            self.rows = [(sum(1 for t in self.db.tasks
                              if t["tasklist"] not in (tasklist, 0)),)]
            return

        raise AssertionError(f"unexpected SQL: {stmt}")

    def fetchall(self):
        return list(self.rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def close(self):
        pass


class FakeDatabase:
    """Minimal stand-in for DatabaseManager."""

    def __init__(self, rows):
        # rows are copied so a test case owns its queue
        self.tasks = [dict(row) for row in rows]
        self.last_picked = None

    @contextmanager
    def transaction(self):
        snapshot = [dict(t) for t in self.tasks]
        cursor = FakeCursor(self)
        try:
            yield cursor
        except Exception:
            self.tasks = snapshot
            raise

    def set_info(self, taskno, info):
        for t in self.tasks:
            if t["taskno"] == taskno:
                t["info"] = info
                return
        raise AssertionError(f"no task {taskno}")


def rows_of(*entries, tasklist=1):
    """Build queue rows from 'pkgbase' or ('pkgbase', 'info') entries."""
    rows = []
    for i, entry in enumerate(entries, 1):
        if isinstance(entry, tuple):
            pkgbase, info = entry
        else:
            pkgbase, info = entry, None
        rows.append({"taskno": i, "pkgbase": pkgbase,
                     "info": info, "tasklist": tasklist})
    return rows


# --------------------------------------------------------------------------
# Synthetic pacman sync database
# --------------------------------------------------------------------------

def write_syncdb(dbpath, pkgs, repo="core"):
    """Write <dbpath>/sync/<repo>.db that pyalpm can read.

    pkgs maps pkgbase -> {'depends': [...], 'makedepends': [...],
    'checkdepends': [...], 'provides': [...], 'arch': 'x86_64'}.  Every
    entry is one package named like its pkgbase.
    """
    syncdir = dbpath / "sync"
    workdir = dbpath / "mk"
    syncdir.mkdir(parents=True, exist_ok=True)
    workdir.mkdir(parents=True, exist_ok=True)

    members = []
    for base, info in pkgs.items():
        name = info.get("name", base)
        version = info.get("version", "1-1")
        member = f"{name}-{version}"
        (workdir / member).mkdir(exist_ok=True)
        desc = [
            f"%NAME%\n{name}\n",
            f"%BASE%\n{base}\n",
            f"%VERSION%\n{version}\n",
            f"%ARCH%\n{info.get('arch', 'x86_64')}\n",
        ]
        for field in ("provides", "depends", "makedepends", "checkdepends"):
            values = info.get(field) or []
            if values:
                desc.append(f"%{field.upper()}%\n" + "\n".join(values) + "\n")
        (workdir / member / "desc").write_text("\n".join(desc))
        members.append(member)

    with tarfile.open(syncdir / f"{repo}.db", "w:gz") as tar:
        for member in members:
            tar.add(workdir / member, arcname=member)


def make_env(monkeypatch, tmp_path, pkgs, rows):
    dbpath = tmp_path / "x86"
    write_syncdb(dbpath, pkgs)
    index = dbcmd.DepIndex(str(dbpath))
    db = FakeDatabase(rows)
    monkeypatch.setattr(dbcmd, "get_dep_index", lambda: index)
    return db, dbcmd.TaskManager(db), index


def pick(mgr, building=True, tasklist=1):
    return mgr.get_task(tasklist, building)


# --------------------------------------------------------------------------
# DepIndex
# --------------------------------------------------------------------------

def test_dep_name_strips_version_constraints():
    assert dbcmd.dep_name("libfoo") == "libfoo"
    assert dbcmd.dep_name("libfoo>=1.2") == "libfoo"
    assert dbcmd.dep_name("libfoo.so=1-64") == "libfoo.so"
    assert dbcmd.dep_name("foo<2") == "foo"


def test_parse_pkgbase():
    assert dbcmd.parse_pkgbase("foo") == ("foo", False)
    assert dbcmd.parse_pkgbase("foo:nocheck") == ("foo", True)
    assert dbcmd.parse_pkgbase("foo:1.2-3") == ("foo", False)
    assert dbcmd.parse_pkgbase("foo:1:1.2-3:nocheck") == ("foo", True)


def test_dep_bases_kinds_and_nocheck(monkeypatch, tmp_path):
    pkgs = {"d": {}, "m": {}, "c": {},
            "p": {"depends": ["d"], "makedepends": ["m"],
                  "checkdepends": ["c"]}}
    _, _, index = make_env(monkeypatch, tmp_path, pkgs, [])
    assert index.dep_bases("p") == {"d", "m", "c"}
    assert index.dep_bases("p", nocheck=True) == {"d", "m"}
    assert index.dep_bases("p", runtime=True) == {"d"}


def test_provides_only_used_when_the_real_name_is_absent(monkeypatch, tmp_path):
    pkgs = {
        "rust": {"provides": ["cargo"]},
        "cargo": {},
        "uses-real": {"depends": ["cargo"]},
        "uses-provider": {"depends": ["rustup"]},
        "rustup": {"provides": ["rustup"]},
    }
    _, _, index = make_env(monkeypatch, tmp_path, pkgs, [])
    # a real package name always wins over a provider
    assert index.dep_bases("uses-real") == {"cargo"}
    assert index.dep_bases("uses-provider") == {"rustup"}


def test_runtime_rdeps_are_transitive_and_follow_only_runtime_deps(
        monkeypatch, tmp_path):
    pkgs = {
        "base": {},
        "lib": {"depends": ["base"]},
        "app": {"depends": ["lib"]},
        "tool": {"makedepends": ["base"], "checkdepends": ["base"]},
    }
    _, _, index = make_env(monkeypatch, tmp_path, pkgs, [])
    # a rebuild of base changes the soname of lib and (transitively) app
    assert index.runtime_rdeps("base") == {"lib", "app"}
    # tool only used base at build time, its own soname does not change
    assert "tool" not in index.runtime_rdeps("base")
    assert index.runtime_rdeps("app") == set()


def test_runtime_rdeps_resolve_through_provides(monkeypatch, tmp_path):
    pkgs = {
        "rust": {"provides": ["cargo"]},
        "tool": {"depends": ["cargo"]},
    }
    _, _, index = make_env(monkeypatch, tmp_path, pkgs, [])
    # nobody is called cargo, so the provide of rust satisfies it
    assert index.dep_bases("tool") == {"rust"}
    assert index.runtime_rdeps("rust") == {"tool"}

    # a real package of that name must win over the provider
    pkgs["cargo"] = {}
    _, _, index = make_env(monkeypatch, tmp_path, pkgs, [])
    assert index.dep_bases("tool") == {"cargo"}
    assert index.runtime_rdeps("rust") == set()


def test_dep_closure(monkeypatch, tmp_path):
    pkgs = {
        "a": {"depends": ["b"]},
        "b": {"makedepends": ["c"]},
        "c": {},
    }
    _, _, index = make_env(monkeypatch, tmp_path, pkgs, [])
    assert index.dep_closure("a") == {"b", "c"}
    assert index.dep_closure("a", runtime=True) == {"b"}


# --------------------------------------------------------------------------
# get_task: basic queue handling
# --------------------------------------------------------------------------

def test_first_waiting_task_is_picked(monkeypatch, tmp_path):
    db, mgr, _ = make_env(monkeypatch, tmp_path,
                          {"a": {}, "b": {}}, rows_of("a", "b"))
    assert pick(mgr) == "a"
    assert db.tasks[0]["info"] == "building"
    assert db.tasks[1]["info"] is None


def test_get_without_build_does_not_claim_the_task(monkeypatch, tmp_path):
    db, mgr, _ = make_env(monkeypatch, tmp_path, {"a": {}}, rows_of("a"))
    assert pick(mgr, building=False) == "a"
    assert db.tasks[0]["info"] is None


def test_get_without_build_never_touches_the_queue(monkeypatch, tmp_path):
    # %wait: another builder holds the only task
    db, mgr, _ = make_env(monkeypatch, tmp_path, {"a": {}},
                          rows_of(("a", "building")))
    assert pick(mgr, building=False) == "%wait"
    assert db.tasks[0]["info"] == "building"

    # %stop: a different tasklist is unfinished
    rows = rows_of(("a", "done")) + rows_of("b", tasklist=2)
    db, mgr, _ = make_env(monkeypatch, tmp_path, {"a": {}, "b": {}}, rows)
    assert pick(mgr, building=False) == "%stop"
    assert db.tasks[0]["tasklist"] == 1

    # None: this tasklist is done, but the history rows stay where they are
    db, mgr, _ = make_env(monkeypatch, tmp_path, {"a": {}},
                          rows_of(("a", "done")))
    assert pick(mgr, building=False) is None
    assert db.tasks[0]["tasklist"] == 1


def test_version_and_nocheck_tag_are_returned_verbatim(monkeypatch, tmp_path):
    _, mgr, _ = make_env(
        monkeypatch, tmp_path,
        {"foo": {"depends": ["bar"]}},
        rows_of("foo:1:1.2-3:nocheck"))
    assert pick(mgr) == "foo:1:1.2-3:nocheck"


def test_busy_builder_means_wait(monkeypatch, tmp_path):
    _, mgr, _ = make_env(monkeypatch, tmp_path, {"a": {}},
                         rows_of(("a", "building")))
    assert pick(mgr) == "%wait"


def test_finished_tasklist_returns_none(monkeypatch, tmp_path):
    db, mgr, _ = make_env(monkeypatch, tmp_path, {"a": {}},
                          rows_of(("a", "done")))
    assert pick(mgr) is None
    assert db.tasks[0]["tasklist"] == 0


def test_other_tasklist_keeps_the_master_waiting(monkeypatch, tmp_path):
    rows = rows_of(("a", "done"))
    rows += rows_of("b", tasklist=2)
    _, mgr, _ = make_env(monkeypatch, tmp_path, {"a": {}, "b": {}}, rows)
    assert pick(mgr) == "%stop"


def test_stop_command_keeps_its_place(monkeypatch, tmp_path):
    _, mgr, _ = make_env(monkeypatch, tmp_path, {"a": {}},
                         rows_of("a", "%stop"))
    assert pick(mgr) == "a"


def test_stop_command_stops_a_blocked_queue(monkeypatch, tmp_path):
    # This is how buildbot stops all builders after a broken GHC package db:
    # the packages before %stop cannot start, so the command is reached.
    _, mgr, _ = make_env(
        monkeypatch, tmp_path,
        {"blocker": {}, "stuck": {"depends": ["blocker"]}},
        rows_of(("blocker", "building"), "stuck", "%stop"))
    assert pick(mgr) == "%stop"


# --------------------------------------------------------------------------
# get_task: dependency ordering
# --------------------------------------------------------------------------

def test_unfinished_dependency_in_front_blocks(monkeypatch, tmp_path):
    _, mgr, _ = make_env(
        monkeypatch, tmp_path,
        {"stale": {}, "app": {"depends": ["stale"]}},
        rows_of(("stale", "building"), "app"))
    assert pick(mgr) == "%wait"


def test_dependency_done_in_front_does_not_block(monkeypatch, tmp_path):
    _, mgr, _ = make_env(
        monkeypatch, tmp_path,
        {"lib": {}, "app": {"depends": ["lib"]}},
        rows_of(("lib", "done"), "app"))
    assert pick(mgr) == "app"


def test_waiting_dependency_of_a_blocked_task_blocks(monkeypatch, tmp_path):
    pkgs = {"blocker": {}, "a": {"depends": ["blocker"]},
            "b": {"depends": ["a"]}}
    _, mgr, _ = make_env(monkeypatch, tmp_path, pkgs,
                         rows_of(("blocker", "building"), "a", "b"))
    assert pick(mgr) == "%wait"


def test_checkdepends_are_ignored_for_a_nocheck_pass(monkeypatch, tmp_path):
    pkgs = {"blocker": {}, "chk": {"depends": ["blocker"]},
            "pkg": {"checkdepends": ["chk"]}}
    rows = rows_of(("blocker", "building"), "chk", "pkg:nocheck")
    _, mgr, _ = make_env(monkeypatch, tmp_path, pkgs, rows)
    assert pick(mgr) == "pkg:nocheck"

    # without :nocheck the check dependency has to be built first
    rows = rows_of(("blocker", "building"), "chk", "pkg")
    _, mgr, _ = make_env(monkeypatch, tmp_path, pkgs, rows)
    assert pick(mgr) == "%wait"


def test_done_dependency_of_a_skipped_task_does_not_block(monkeypatch, tmp_path):
    """Regression: 1d09ac6c asked the wrong direction.

    The wave check compared the task in front against the dependency closure
    of the *candidate*, so an already built dependency of the candidate
    blocked the queue.  With a %stop behind it, every builder exited.
    """
    pkgs = {"blocker": {}, "stuck": {"depends": ["blocker"]},
            "lib": {}, "app": {"depends": ["lib"]}}
    rows = rows_of(("blocker", "building"), "stuck",
                   ("lib", "done"), "app", "%stop")
    _, mgr, _ = make_env(monkeypatch, tmp_path, pkgs, rows)
    assert pick(mgr) == "app"


def test_unrelated_building_task_does_not_block(monkeypatch, tmp_path):
    _, mgr, _ = make_env(monkeypatch, tmp_path, {"busy": {}, "app": {}},
                         rows_of(("busy", "building"), "app"))
    assert pick(mgr) == "app"


def test_dependency_held_by_another_builder_blocks(monkeypatch, tmp_path):
    # a is blocked by the busy task, so z behind it is handed out first; the
    # dependency on z has to keep a waiting even though z is later in the list.
    pkgs = {"busy": {}, "a": {"depends": ["busy", "z"]}, "z": {}}
    _, mgr, _ = make_env(monkeypatch, tmp_path, pkgs,
                         rows_of(("busy", "building"), "a", "z"))
    assert pick(mgr) == "z"
    assert pick(mgr) == "%wait"


def test_dependency_index_failure_returns_wait(monkeypatch, tmp_path):
    # Never report finished or stop when the dependency data cannot be read:
    # the master builder would move the repo while builders are still running.
    db = FakeDatabase(rows_of("a"))

    def broken():
        raise RuntimeError("no package database found")

    monkeypatch.setattr(dbcmd, "get_dep_index", broken)
    assert pick(dbcmd.TaskManager(db)) == "%wait"


# --------------------------------------------------------------------------
# get_task: the same package
# --------------------------------------------------------------------------

def test_same_package_is_never_picked_twice_at_once(monkeypatch, tmp_path):
    db, mgr, _ = make_env(monkeypatch, tmp_path, {"pkg": {}},
                          rows_of("pkg:nocheck", "pkg"))
    assert pick(mgr) == "pkg:nocheck"
    # the clean rebuild has to wait for the first pass
    assert pick(mgr) == "%wait"
    db.set_info(1, "done")
    assert pick(mgr) == "pkg"


def test_busy_same_package_blocks(monkeypatch, tmp_path):
    _, mgr, _ = make_env(monkeypatch, tmp_path, {"pkg": {}},
                         rows_of(("pkg", "building"), "pkg"))
    assert pick(mgr) == "%wait"


# --------------------------------------------------------------------------
# get_task: haskell ABI / wave rule (run 1027)
# --------------------------------------------------------------------------

ABI_PKGS = {
    "blocker": {},
    "stuck": {"depends": ["blocker"]},
    "colour": {},
    "ansi-terminal": {"depends": ["colour"]},
    "haskell-tool": {"depends": ["ansi-terminal"]},
}


def test_done_reverse_dependency_does_not_block(monkeypatch, tmp_path):
    """A finished package linking the candidate does not keep it out.

    Its build is over, so the rebuild cannot break it; the waiting rows are
    what the rule looks at.  Blocking here only delayed ansi-terminal's
    rebuild until the tasks in front had started, so it was removed.
    """
    rows = rows_of(("blocker", "building"), "stuck",
                   ("ansi-terminal", "done"), "colour")
    _, mgr, _ = make_env(monkeypatch, tmp_path, ABI_PKGS, rows)
    assert pick(mgr) == "colour"


def test_building_reverse_dependency_in_wave_blocks(monkeypatch, tmp_path):
    rows = rows_of(("ansi-terminal", "building"), "colour")
    _, mgr, _ = make_env(monkeypatch, tmp_path, ABI_PKGS, rows)
    assert pick(mgr) == "%wait"


def test_first_waiting_task_is_not_blocked_by_finished_rows(monkeypatch, tmp_path):
    rows = rows_of(("ansi-terminal", "done"), "colour")
    _, mgr, _ = make_env(monkeypatch, tmp_path, ABI_PKGS, rows)
    assert pick(mgr) == "colour"


def test_wave_starts_after_the_previous_build_of_the_same_package(
        monkeypatch, tmp_path):
    # ansi-terminal belongs to the previous wave of colour's rebuild, so it
    # does not block the second colour task.
    rows = rows_of(("ansi-terminal", "done"), ("colour", "done"), "colour")
    _, mgr, _ = make_env(monkeypatch, tmp_path, ABI_PKGS, rows)
    assert pick(mgr) == "colour"


def test_waiting_task_that_would_install_a_risky_package_blocks(
        monkeypatch, tmp_path):
    # stuck waits in front of colour and needs ansi-terminal (directly or
    # through another package).  Building it now would link the old colour.
    pkgs = dict(ABI_PKGS)
    pkgs["stuck"] = {"depends": ["blocker", "haskell-tool"]}
    rows = rows_of(("blocker", "building"), "stuck", "colour")
    _, mgr, _ = make_env(monkeypatch, tmp_path, pkgs, rows)
    assert pick(mgr) == "%wait"


def test_building_task_whose_build_needs_a_risky_package_blocks(
        monkeypatch, tmp_path):
    # Another builder is already building a tool that makedepends on
    # ansi-terminal.  Rebuilding colour now breaks ansi-terminal inside that
    # build environment before the tool can finish.
    pkgs = dict(ABI_PKGS)
    pkgs["tool"] = {"makedepends": ["ansi-terminal"]}
    rows = rows_of(("tool", "building"), "colour")
    _, mgr, _ = make_env(monkeypatch, tmp_path, pkgs, rows)
    assert pick(mgr) == "%wait"


def test_done_task_that_used_a_risky_package_does_not_block(
        monkeypatch, tmp_path):
    # The build environment of a finished task is gone; only its own package
    # matters and that does not link colour.
    pkgs = dict(ABI_PKGS)
    pkgs["tool"] = {"makedepends": ["ansi-terminal"]}
    rows = rows_of(("blocker", "building"), "stuck",
                   ("tool", "done"), "colour")
    _, mgr, _ = make_env(monkeypatch, tmp_path, pkgs, rows)
    assert pick(mgr) == "colour"


def test_chroot_bases_is_deps_of_any_kind_plus_their_runtime_closure(
        monkeypatch, tmp_path):
    pkgs = {
        "lib": {},
        "libdep": {"depends": ["lib"]},
        "buildtool": {"depends": ["tool-lib"], "makedepends": ["tool-lib-make"]},
        "tool-lib": {},
        "tool-lib-make": {},
        "checkthing": {},
        "pkg": {"depends": ["libdep"], "makedepends": ["buildtool"],
                "checkdepends": ["checkthing"]},
    }
    _, _, index = make_env(monkeypatch, tmp_path, pkgs, [])
    # what pacman installs for the build: the deps of any kind, plus the
    # runtime closure of each of them
    assert index.chroot_bases("pkg") == {"libdep", "lib", "buildtool",
                                         "checkthing", "tool-lib"}
    # tool-lib-make is only needed to build buildtool, it is not installed
    assert "tool-lib-make" not in index.chroot_bases("pkg")


def test_makedepend_of_a_makedepend_is_not_a_build_environment(
        monkeypatch, tmp_path):
    """Regression: run 1027 blocked mkdocs-material.

    `fmt` has mkdocs-material in its makedepends, so the full dependency
    closure of every package that build-depends on fmt contained it.  A
    rebuild of mkdocs-material cannot break such a build: it is never
    installed, and nothing links it.
    """
    pkgs = {"colour": {}, "ansi-terminal": {"depends": ["colour"]},
            "docgen": {"makedepends": ["colour"]},
            "fmt": {"makedepends": ["docgen"]},
            "nickel": {"makedepends": ["fmt"]}}
    rows = rows_of(("nickel", "building"), "colour")
    _, mgr, index = make_env(monkeypatch, tmp_path, pkgs, rows)
    assert "colour" not in index.chroot_bases("nickel")
    assert pick(mgr) == "colour"


def test_risky_package_pulled_in_by_a_checkdepends_chain_blocks(
        monkeypatch, tmp_path):
    # run 1027: mockery itself does not link colour, but its checkdepends
    # (hspec) does, so colour landing breaks the ghc package db of its build
    pkgs = dict(ABI_PKGS)
    pkgs["checklib"] = {"depends": ["blocker"], "checkdepends": ["haskell-tool"]}
    rows = rows_of(("blocker", "building"), "checklib", "colour")
    _, mgr, index = make_env(monkeypatch, tmp_path, pkgs, rows)
    # haskell-tool links ansi-terminal links colour: rebuilding colour leaves
    # checklib's build environment with a broken ansi-terminal
    assert index.chroot_bases("checklib") & index.runtime_rdeps("colour")
    assert pick(mgr) == "%wait"


def test_failed_and_nolog_rows_do_not_block(monkeypatch, tmp_path):
    # A failed or log-less row is history: its build is over and cannot be
    # broken by the rebuild, so it does not keep colour out of the queue.
    for state in ("failed:8", "nolog"):
        rows = rows_of(("blocker", "building"), "stuck",
                       ("ansi-terminal", state), "colour")
        _, mgr, _ = make_env(monkeypatch, tmp_path, ABI_PKGS, rows)
        assert pick(mgr) == "colour", state


def test_command_row_inside_the_wave_is_ignored(monkeypatch, tmp_path):
    # A consumed %stop row sits in colour's wave.  It is not a package, so it
    # must not crash the build environment lookup, and it must not block.
    rows = rows_of(("%stop", "done"), ("blocker", "building"), "stuck",
                   ("ansi-terminal", "done"), "colour")
    _, mgr, index = make_env(monkeypatch, tmp_path, ABI_PKGS, rows)
    assert index.chroot_bases("%stop") == set()
    assert index.runtime_rdeps("%stop") == set()
    assert pick(mgr) == "colour"


def test_risky_set_is_transitive(monkeypatch, tmp_path):
    # haskell-tool only links ansi-terminal, but it still breaks when colour
    # changes, so it is part of the risky set and blocks colour.
    pkgs = dict(ABI_PKGS)
    _, _, index = make_env(monkeypatch, tmp_path, pkgs, [])
    assert "haskell-tool" in index.runtime_rdeps("colour")


# --------------------------------------------------------------------------
# Simulation: several builders on one tasklist
# --------------------------------------------------------------------------

def _check_pick(db, index, picked, snapshot):
    """Assert the safety properties of one pick on the current queue."""
    rows = sorted(db.tasks, key=lambda t: t["taskno"])
    i = next(k for k, t in enumerate(rows) if t["taskno"] == picked)
    base, nocheck = dbcmd.parse_pkgbase(rows[i]["pkgbase"])
    bases = [dbcmd.parse_pkgbase(t["pkgbase"])[0] for t in rows]

    # 1. every queued build dependency in front is finished
    deps = index.dep_bases(base, nocheck)
    for j in range(i):
        if bases[j] in deps and snapshot[j] != "done":
            raise AssertionError(
                f"task {picked} ({base}) started while dependency "
                f"{bases[j]} is {snapshot[j]!r} (row {j})")

    # 2. no two occurrences of a pkgbase run at the same time, and an earlier
    #    occurrence has to be finished first
    for j in range(len(rows)):
        if j == i or bases[j] != base:
            continue
        if snapshot[j] == "building" or (j < i and snapshot[j] is None):
            raise AssertionError(
                f"task {picked} ({base}) started while {bases[j]} is "
                f"{snapshot[j]!r} (row {j})")

    # 3. soname wave rule: nothing unfinished of the wave in front may be
    #    exposed.  The build environment is what the rule looks at
    #    (chroot_bases), not the whole dependency closure: a makedepend of a
    #    makedepend is not installed and cannot break.  Finished rows are not
    #    checked: their build is over.
    risky = index.runtime_rdeps(base)
    if risky:
        previous = max((j for j in range(i) if bases[j] == base), default=-1)
        for j in range(previous + 1, i):
            state = snapshot[j]
            if state is None:
                if index.chroot_bases(bases[j]) & risky:
                    raise AssertionError(
                        f"task {picked} ({base}) started while waiting "
                        f"{bases[j]} would install a package from {sorted(risky)}")
            elif state == "building":
                if bases[j] in risky or index.chroot_bases(bases[j]) & risky:
                    raise AssertionError(
                        f"task {picked} ({base}) started while {bases[j]} "
                        "is being built with a package it would rebuild")


def simulate(monkeypatch, tmp_path, pkgs, order, builders, seed, rounds=10000):
    rng = random.Random(seed)
    db, mgr, index = make_env(monkeypatch, tmp_path, pkgs, rows_of(*order))
    started = []
    active = []
    finished = False

    for _ in range(rounds):
        if active and (len(active) >= builders or rng.random() < 0.5):
            taskno = rng.choice(active)
            active.remove(taskno)
            db.set_info(taskno, "done")
            continue

        rows = sorted(db.tasks, key=lambda t: t["taskno"])
        snapshot = [t["info"] for t in rows]

        picked = pick(mgr)
        if picked is None:
            finished = True
            break
        if picked == "%stop":
            raise AssertionError("unexpected %stop: another tasklist exists")
        if picked == "%wait":
            if not active:
                raise AssertionError(
                    f"deadlock: %wait with no running builder; queue={snapshot}")
            continue

        taskno = db.last_picked
        _check_pick(db, index, taskno, snapshot)
        if taskno in started:
            raise AssertionError(f"task {taskno} picked twice")
        started.append(taskno)
        active.append(taskno)

    assert finished, "simulation did not finish"
    assert sorted(t["taskno"] for t in db.tasks if t["info"] == "done") == \
        sorted(t["taskno"] for t in db.tasks)
    return started


DAG = {
    # three independent roots so that several builders really work at once
    "libc": {},
    "rust": {},
    "python": {},
    "zlib": {"depends": ["libc"]},
    "openssl": {"depends": ["libc"]},
    "cargo": {"depends": ["rust"]},
    "libpng": {"depends": ["zlib"]},
    "setuptools": {"depends": ["python"]},
    "curl": {"depends": ["openssl", "zlib"]},
    "ripgrep": {"depends": ["cargo"]},
    "pytest": {"depends": ["setuptools"]},
    "app1": {"depends": ["curl", "libpng"]},
    "app2": {"depends": ["openssl", "pytest"]},
    "app3": {"depends": ["libpng", "ripgrep"]},
    "app4": {"depends": ["app1"]},
}
DAG_ORDER = ["libc", "rust", "python", "zlib", "openssl", "cargo", "libpng",
             "setuptools", "curl", "ripgrep", "pytest", "app1", "app2",
             "app3", "app4"]


@pytest.mark.parametrize("seed", range(20))
@pytest.mark.parametrize("builders", [1, 3])
def test_simulation_follows_dependency_order(monkeypatch, tmp_path, seed, builders):
    simulate(monkeypatch, tmp_path, DAG, DAG_ORDER, builders, seed)


def test_simulation_with_a_package_built_twice(monkeypatch, tmp_path):
    # A bootstrap pass (:nocheck) followed by a clean rebuild of the same
    # pkgbase, like genrebuild emits for broken cycles.
    pkgs = dict(DAG)
    pkgs["bootstrap"] = {"depends": ["libc"]}
    order = ["libc", "bootstrap:nocheck", "zlib", "bootstrap", "openssl",
             "libpng", "curl", "app1", "app2", "app3", "app4"]
    simulate(monkeypatch, tmp_path, pkgs, order, 3, seed=0)


# Task lists that still contain a dependency cycle after genrebuild gave up on
# it and a manual order from loop_list.lst was used.  A manual order can always
# satisfy at most one direction of the cycle, so some dependency edges point
# forward in the list.  get_task() has to keep making progress anyway.
CYCLE_CASES = [
    ("2-cycle", {"a": {"depends": ["b"]},
                 "b": {"depends": ["a"]}},
     ["a", "b"]),
    ("3-cycle", {"a": {"depends": ["b"]},
                 "b": {"depends": ["c"]},
                 "c": {"depends": ["a"]}},
     ["a", "b", "c"]),
    ("bootstrap", {"a": {"depends": ["b"]},
                   "b": {"depends": ["a"]}},
     ["a:nocheck", "b", "a"]),
    ("bootstrap and repeat", {"a": {"depends": ["b"]},
                              "b": {"depends": ["a"]}},
     ["a:nocheck", "b", "a", "b"]),
    ("make/check cycle", {"a": {"makedepends": ["b"]},
                          "b": {"checkdepends": ["a"]}},
     ["a:nocheck", "b", "a"]),
    ("cycle with ABI rdeps", {"a": {"depends": ["b"]},
                              "b": {"depends": ["a"]},
                              "c": {"depends": ["b"]},
                              "d": {"depends": ["c"]}},
     ["a", "b", "c", "d"]),
]


@pytest.mark.parametrize("name,pkgs,order", CYCLE_CASES,
                         ids=[case[0] for case in CYCLE_CASES])
@pytest.mark.parametrize("builders", [1, 3])
def test_cyclic_tasklist_still_finishes(monkeypatch, tmp_path, name, pkgs,
                                        order, builders):
    # No deadlock: the first waiting task is always startable because only
    # dependencies in front of a task are waited for, so the edge that points
    # forward in the manual cycle order is ignored.
    simulate(monkeypatch, tmp_path, pkgs, order, builders, seed=0)


def test_parallel_builders_get_different_tasks(monkeypatch, tmp_path):
    # Independent packages: no builder may get a task another one holds.
    pkgs = {"a": {}, "b": {}, "c": {}}
    db, mgr, _ = make_env(monkeypatch, tmp_path, pkgs, rows_of("a", "b", "c"))
    picked = [pick(mgr) for _ in range(3)]
    assert picked == ["a", "b", "c"]
    assert {t["info"] for t in db.tasks} == {"building"}

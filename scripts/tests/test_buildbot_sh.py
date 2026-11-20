#!/usr/bin/env python3
"""Regression tests for buildbot.sh: the parts around dbcmd.py.

Covered here:

  * %stop stops the builder and says why,
  * %wait keeps the builder polling instead of exiting,
  * None (queue finished) exits 0 silently,
  * a haskell build failure stops the other builders only when the log really
    shows a build failure ("A failure occurred in ..."), not when the package
    has no log at all (arch=any packages, broken builder setup),
  * a missing log does not break the retry heuristics of the script.

The script is run for real; dbcmd.py, 0build.sh, ssh and sleep are small
stubs in a temporary directory, so this needs nothing but bash and needs no
package database.  Run with:

    python3 -m pytest scripts/tests/test_buildbot_sh.py -v
"""

import os
import stat
import sys
from pathlib import Path

import pytest

BUILDBOT = Path(__file__).resolve().parents[1] / "buildbot.sh"

DBSTUB = """#!/usr/bin/env python3
import pathlib, sys

here = pathlib.Path(__file__).resolve().parent
with open(here / "calls.log", "a") as f:
    f.write("dbcmd " + " ".join(sys.argv[1:]) + "\\n")

queue = here / "queue.txt"
lines = queue.read_text().splitlines() if queue.exists() else []
answer = lines.pop(0) if lines else "None"
queue.write_text("".join(l + "\\n" for l in lines))
print(answer)
"""

BUILDSTUB = """#!/bin/bash
here=$(cd "$(dirname "$0")" && pwd)
echo "0build $*" >> "$here/calls.log"
if [[ -n ${FAKE_LOG-} ]]; then
    printf '%s\\n' "$FAKE_LOG" > "all.log.loong1"
fi
exit "${FAKE_STATUS:-0}"
"""

NOOPSTUB = """#!/bin/sh
exit 0
"""

PKGBUILD = """pkgver=1.0
pkgrel=1
"""


def sandbox(tmp_path, answers, log=None, status=0):
    """Create the stub directory and return the environment for one run."""
    sandbox = tmp_path
    (sandbox / "dbcmd.py").write_text(DBSTUB)
    (sandbox / "0build.sh").write_text(BUILDSTUB)
    for name in ("sleep", "ssh"):
        (sandbox / name).write_text(NOOPSTUB)
    for name in ("dbcmd.py", "0build.sh", "sleep", "ssh"):
        (sandbox / name).chmod((sandbox / name).stat().st_mode | stat.S_IEXEC)
    (sandbox / "queue.txt").write_text("".join(a + "\n" for a in answers))
    (sandbox / "calls.log").write_text("")
    for pkg in ("haskell-tools", "cc-tool", "any-package"):
        (sandbox / "work" / pkg).mkdir(parents=True, exist_ok=True)
        (sandbox / "work" / pkg / "PKGBUILD").write_text(PKGBUILD)
    (sandbox / "logs").mkdir(exist_ok=True)

    env = dict(os.environ)
    env.update({
        "SCRIPTSPATH": str(sandbox),
        "WORKDIR": str(sandbox / "work"),
        "ZSTLOGDIR": str(sandbox / "logs"),
        "BUILDER": "loong1",
        "BUILDDIR": "/tmp",
        "BUILDLIST": "1",
        "PATH": f"{sandbox}:{env['PATH']}",
        "FAKE_STATUS": str(status),
    })
    if log is not None:
        env["FAKE_LOG"] = log
    else:
        env.pop("FAKE_LOG", None)
    return env


def run_buildbot(tmp_path, env):
    import subprocess
    return subprocess.run(["bash", str(BUILDBOT), "--builder", "loong1:/tmp",
                           "--", "--skippgpcheck"],
                          cwd=str(tmp_path), env=env,
                          capture_output=True, text=True, timeout=60)


def calls(tmp_path):
    return (tmp_path / "calls.log").read_text().splitlines()


def test_stop_exits_with_a_message(tmp_path):
    proc = run_buildbot(tmp_path, sandbox(tmp_path, ["%stop"]))
    assert proc.returncode == 1
    assert "%stop" in proc.stderr
    assert "stopping this builder" in proc.stderr
    assert "%stop entry is in the queue" in proc.stderr


def test_finished_queue_exits_quietly(tmp_path):
    proc = run_buildbot(tmp_path, sandbox(tmp_path, ["None"]))
    assert proc.returncode == 0
    assert proc.stdout == "" and proc.stderr == ""


def test_wait_keeps_the_builder_alive(tmp_path):
    proc = run_buildbot(tmp_path, sandbox(tmp_path, ["%wait", "%wait", "None"]))
    assert proc.returncode == 0
    assert len([c for c in calls(tmp_path) if "--get" in c]) == 3


def test_haskell_build_failure_stops_the_others(tmp_path):
    log = "Configuring x...\n==> ERROR: A failure occurred in build().\n"
    proc = run_buildbot(tmp_path, sandbox(tmp_path, ["haskell-tools", "None"],
                                          log=log, status=1))
    assert proc.returncode == 0
    assert any("--insert %stop" in c for c in calls(tmp_path))
    assert any("--done haskell-tools" in c for c in calls(tmp_path))


def test_haskell_failure_without_a_log_still_stops(tmp_path):
    # The decision does not look at the log: any status other than 0 and 2
    # means a broken build environment, even when there is no log to inspect.
    # A missing log must not make the retry heuristics print stat/[ errors.
    proc = run_buildbot(tmp_path, sandbox(tmp_path, ["haskell-tools", "None"],
                                          log=None, status=1))
    assert proc.returncode == 0
    assert any("--insert %stop" in c for c in calls(tmp_path))
    assert "stat:" not in proc.stderr
    assert "unary operator" not in proc.stderr


def test_non_haskell_failure_never_stops_the_others(tmp_path):
    log = "==> ERROR: A failure occurred in build().\n"
    proc = run_buildbot(tmp_path, sandbox(tmp_path, ["cc-tool", "None"],
                                          log=log, status=1))
    assert proc.returncode == 0
    assert not any("--insert" in c for c in calls(tmp_path))


def test_signature_failure_stops_without_retrying(tmp_path):
    # 0build.sh exits 3 when the package itself built but gpg --detach-sign
    # failed on the builder: not a build failure, so no retry, but the other
    # builders would hit the same signing problem.
    proc = run_buildbot(tmp_path, sandbox(tmp_path, ["cc-tool", "None"], status=3))
    assert proc.returncode == 0
    assert len([c for c in calls(tmp_path) if c.startswith("0build")]) == 1
    assert any("--done cc-tool" in c for c in calls(tmp_path))
    assert any("--insert %stop" in c for c in calls(tmp_path))


def test_signature_failure_on_haskell_inserts_stop_once(tmp_path):
    proc = run_buildbot(tmp_path, sandbox(tmp_path, ["haskell-tools", "None"], status=3))
    assert proc.returncode == 0
    assert len([c for c in calls(tmp_path) if "--insert %stop" in c]) == 1


def test_successful_build_marks_done_and_continues(tmp_path):
    proc = run_buildbot(tmp_path, sandbox(tmp_path, ["any-package", "None"]))
    assert proc.returncode == 0
    assert any("--done any-package" in c for c in calls(tmp_path))
    assert not any("--insert" in c for c in calls(tmp_path))

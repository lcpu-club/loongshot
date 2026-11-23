#!/usr/bin/env python3
"""Regression tests for buildstag.sh: the repo switch it hands to buildbot.

TESTING decides where a package lands (temp repo, debug pool, chroot), and the
only script that sets it is 0build.sh, which reads `--stag` / `--test`.
buildstag.sh does not call 0build.sh itself: it passes the switch to buildbot.sh
as REPOSWITCH, which has to stay in the spelling 0build.sh understands.  A
`-staging` there would be silently ignored and the staging build would land in
the plain repo.

The whole script is run; everything it calls is a stub in a temporary
directory, so this needs nothing but bash.  The move-repo half is not reached
because the buildbot.sh stub fails.

    python3 -m pytest scripts/tests/test_buildstag_sh.py -v
"""

import os
import stat
import subprocess
from pathlib import Path

import pytest

BUILDSTAG = Path(__file__).resolve().parents[1] / "buildstag.sh"

SSHSTUB = """#!/bin/sh
echo "ssh $*" >> "$(dirname "$0")/calls.log"
exit 0
"""

COMPARESTUB = """#!/bin/sh
for a in "$@"; do
    [[ $a == "-BEC" ]] && echo "pk1" && exit 0
done
exit 0
"""

FILTERSTUB = """#!/bin/sh
cat
"""

ADDVERSTUB = """#!/bin/sh
for a in "$@"; do last=$a; done
echo "$last"
"""

GENREBUILDSTUB = """#!/bin/sh
echo pk1
"""

NOOPSTUB = """#!/bin/sh
exit 0
"""

DBCMDSTUB = """#!/bin/bash
echo "dbcmd $*" >> "$(dirname "$0")/calls.log"
exit 0
"""

BUILDBOTSTUB = """#!/bin/bash
echo "buildbot $*" >> "$(dirname "$0")/calls.log"
exit 1
"""


def sandbox(tmp_path):
    for name, body in (("ssh", SSHSTUB),
                       ("compare86.py", COMPARESTUB),
                       ("dbinit.py", NOOPSTUB),
                       ("filterpkg.py", FILTERSTUB),
                       ("addver.py", ADDVERSTUB),
                       ("genrebuild", GENREBUILDSTUB),
                       ("dbcmd.py", DBCMDSTUB),
                       ("buildbot.sh", BUILDBOTSTUB)):
        path = tmp_path / name
        path.write_text(body)
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
    (tmp_path / "calls.log").write_text("")

    env = dict(os.environ)
    env.update({"SCRIPTSPATH": str(tmp_path),
                "BUILDER": "loong1",
                "BUILDDIR": "/tmp",
                # the stubs above must win over the real ssh/compare86.py
                "PATH": f"{tmp_path}:{env['PATH']}"})
    return env


def run_buildstag(tmp_path, env, args):
    return subprocess.run(["bash", str(BUILDSTAG), *args],
                          cwd=str(tmp_path), env=env,
                          capture_output=True, text=True, timeout=60)


def buildbot_call(tmp_path):
    """Arguments buildstag.sh handed to buildbot.sh, split into words."""
    line = [line for line in (tmp_path / "calls.log").read_text().splitlines()
            if line.startswith("buildbot ")][0]
    return line.split()[1:]


def forwarded(tmp_path):
    """The part buildbot.sh passes on to 0build.sh, i.e. before `--`."""
    args = buildbot_call(tmp_path)
    return args[:args.index("--")]


def dbcmd_args(tmp_path):
    return [line.split()[1:] for line in
            (tmp_path / "calls.log").read_text().splitlines()
            if line.startswith("dbcmd ")]


def test_staging_switch_reaches_buildbot(tmp_path):
    env = sandbox(tmp_path)
    proc = run_buildstag(tmp_path, env, ["--stag"])
    assert proc.returncode == 0, proc.stderr
    assert "--stag" in forwarded(tmp_path)
    # the tasklist is derived from the switch, not taken from the environment
    assert [a for a in dbcmd_args(tmp_path) if "--add" in a][0][-1] == "3"


def test_testing_switch_reaches_buildbot(tmp_path):
    env = sandbox(tmp_path)
    proc = run_buildstag(tmp_path, env, ["--test"])
    assert proc.returncode == 0, proc.stderr
    assert "--test" in forwarded(tmp_path)
    assert [a for a in dbcmd_args(tmp_path) if "--add" in a][0][-1] == "2"


def test_plain_run_passes_no_switch(tmp_path):
    env = sandbox(tmp_path)
    proc = run_buildstag(tmp_path, env, [])
    assert proc.returncode == 0, proc.stderr
    args = forwarded(tmp_path)
    for arg in ("-staging", "--stag", "-testing", "--test"):
        assert arg not in args
    assert [a for a in dbcmd_args(tmp_path) if "--add" in a][0][-1] == "1"

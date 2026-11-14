#!/usr/bin/python3
"""Regression tests for genrebuild.

Requires pyalpm / networkx and a real pacman sync db, e.g. on arch3:

    python3 test_genrebuild.py --dbpath=/home/pluto/.cache/compare86/x86

Options:
    --dbpath PATH       pacman sync db directory (required, or GENREBUILD_DBPATH)
    --genrebuild PATH   script under test (default: genrebuild next to this file)
    --lst-dir DIR       directory holding openssl.lst (default: same as this file)
    --no-big            skip the big-batch tests (slow, ~2 min in total otherwise)
    --timeout SEC       per-invocation timeout, default 300
    --keep              keep the temporary work directory

Exit code: 0 when every test passes or skips, 1 when something fails.
"""

import argparse
import contextlib
import io
import itertools
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))

# Real dependency cycles: the gstreamer/ffmpeg multimedia stack (hard deps only)
# and the dotnet SDK bootstrap. Both need a manual build order.
MEDIA = ["ffmpeg", "gstreamer", "pipewire", "pulseaudio", "wireplumber"]
DOTNET = ["dotnet-core", "dotnet-core-9.0"]
# curl makedepends git, git depends curl: the smallest cycle with one soft edge,
# used to exercise pass1 breaking plus pass2 rebuilds.
CURL_GIT = ["curl", "git"]

MEDIA_MANUAL = ("[ffmpeg,gstreamer,pipewire,pulseaudio,wireplumber]"
                "->[ffmpeg,gstreamer,pipewire,pulseaudio,wireplumber]")
DOTNET_MANUAL = "[dotnet-core,dotnet-core-9.0]->[dotnet-core-9.0,dotnet-core]"
BIG_LOOP_LIST = MEDIA_MANUAL + "\n" + DOTNET_MANUAL + "\n"

BIG_LST = "openssl.lst"

RESULTS = []
_CACHE = {}
_SANDBOX_ID = itertools.count(1)


class Skip(Exception):
    pass


def record(name, status, secs, detail=""):
    RESULTS.append((name, status, secs, detail))
    line = "[%s] %s (%.1fs)" % (status, name, secs)
    if detail:
        line += "  " + detail
    print(line, flush=True)


def case(fn):
    name = fn.__name__[2:].replace("_", " ")
    start = time.time()
    try:
        detail = fn() or ""
    except Skip as e:
        record(name, "SKIP", time.time() - start, str(e))
    except Exception as e:
        msg = str(e) or traceback.format_exc(limit=2)
        record(name, "FAIL", time.time() - start, msg.splitlines()[0][:300])
    else:
        record(name, "PASS", time.time() - start, detail)
    return fn


# ---------------------------------------------------------------- helpers

def sandbox(loop_list=None, name=None):
    d = os.path.join(WORK, name or ("case%02d" % next(_SANDBOX_ID)))
    os.makedirs(d, exist_ok=True)
    if loop_list is not None:
        with open(os.path.join(d, "loop_list.lst"), "w") as f:
            f.write(loop_list)
    return d


def gb(args, cwd, seed=0, exe=None):
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = str(seed)
    cmd = [sys.executable, exe or GB] + [str(a) for a in args]
    try:
        return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True,
                              text=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        raise AssertionError("timeout (>%ss): %s" % (TIMEOUT, " ".join(cmd[:3])))


def ok(p, label=""):
    assert p.returncode == 0, "%s exited with %d\nstdout=%r\nstderr=\n%s" % (
        label, p.returncode, p.stdout[:500], p.stderr[-2000:])
    return p.stdout.split()


def bad(p, rc, label=""):
    assert p.returncode == rc, "%s: expected exit %d, got %d\nstderr=\n%s" % (
        label, rc, p.returncode, p.stderr[-2000:])


def run_db(args, cwd, label="", seed=0, exe=None):
    return gb(["--dbpath", DB] + list(args), cwd, seed=seed, exe=exe)


def run_with_looplist(manual, pkgs, name, extra=()):
    d = sandbox(manual, name=name)
    lp = os.path.join(d, "loop_list.lst")
    return ok(run_db(["--loop-list", lp] + list(extra) + list(pkgs), d, name), name)


_NS = None


def internals():
    """Load the first half of genrebuild (everything before `result = []`).

    genrebuild is a script, not a module, so white-box tests have to load it
    this way to reach package_db and the helper functions.
    """
    global _NS
    if _NS is not None:
        return _NS
    with open(GB) as f:
        head = f.read().split("result = []")[0]
    old_argv = sys.argv
    sys.argv = ["genrebuild", "--dbpath=" + DB,
                "--loop-list=" + os.path.join(WORK, "internal-nonexistent.lst")] + CURL_GIT
    ns = {"__name__": "__main__", "__file__": GB}
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            exec(compile(head, GB, "exec"), ns)
    finally:
        sys.argv = old_argv
    # Only the curl/git closure was resolved above, so reverse_deps is incomplete.
    # Rebuild a full hard reverse table from package_db; hard_rdeps() reads it.
    rd = defaultdict(set)
    for pkg, fields in ns["package_db"].items():
        if not isinstance(pkg, str):
            continue
        for dep in fields["depends"]:
            if isinstance(dep, str):
                rd[dep].add(pkg)
    ns["reverse_deps"] = rd
    _NS = ns
    return ns


def big_pkgs():
    path = os.path.join(LST_DIR, BIG_LST)
    if not os.path.exists(path):
        raise Skip("missing %s" % path)
    with open(path) as f:
        pkgs = f.read().split()
    if not pkgs:
        raise Skip("%s is empty" % path)
    return pkgs


def big(mode="haskell", seed=0, fresh=False):
    """Run the big batch once and cache the result."""
    key = (mode, seed)
    if not fresh and key in _CACHE:
        return _CACHE[key]
    pkgs = big_pkgs()
    d = sandbox(BIG_LOOP_LIST, name="big")
    lp = os.path.join(d, "loop_list.lst")
    args = ["--dbpath", DB, "--loop-list", lp, "--propagate=" + mode]
    p = gb(args + pkgs, d, seed=seed)
    if not fresh:
        _CACHE[key] = p
    return p


def manual_members(*texts):
    out = set()
    for text in texts:
        for line in text.splitlines():
            line = line.strip()
            if "->" not in line:
                continue
            left, right = line.split("->", 1)
            for part in (left.strip("[]"), right.strip("[]")):
                out |= {x.strip().removesuffix(":nocheck") for x in part.split(",") if x.strip()}
    return out


def invariant_report(p, mode):
    """Check the four hard invariants and return a printable summary."""
    ns = internals()
    pdb, is_haskell = ns["package_db"], ns["is_haskell"]
    toks = ok(p, "invariant: " + mode)
    names = [t.removesuffix(":nocheck") for t in toks]
    idx = defaultdict(list)
    for i, n in enumerate(names):
        idx[n].append(i)

    def deps(n):
        return {d for d in pdb[n]["depends"] if isinstance(d, str) and d != n}

    unknown = sorted(n for n in idx if n not in pdb)
    assert not unknown, "output contains packages missing from the db: %s" % unknown[:5]

    pkgs = big_pkgs()
    missing = [p_ for p_ in pkgs if p_.removesuffix(":nocheck") not in idx]
    assert not missing, "requested packages missing from output: %s" % missing[:5]

    members = manual_members(BIG_LOOP_LIST)

    # Invariant 1: a haskell dependency's last build must precede the dependent's last build,
    # otherwise the dependent links a src that no longer exists at runtime.
    bad_hs = [(n, d) for n, pos in idx.items() for d in deps(n)
              if d in idx and is_haskell(d) and idx[d][-1] > pos[-1]]
    assert not bad_hs, "haskell dependency order violated: %s" % bad_hs[:5]

    # Invariant 2: outside manually ordered cycles, every build must see all its hard deps.
    bad_boot = [(i, n) for i, n in enumerate(names)
                if n not in members
                and not all(any(j < i for j in idx[d]) for d in deps(n) if d in idx)]
    assert not bad_boot, "bootstrap order violated: %s" % bad_boot[:5]

    # Invariant 3: with --propagate=all, outside manually ordered cycles nothing may be stale.
    if mode == "all":
        stale = [(n, d) for n, pos in idx.items() for d in deps(n)
                 if d in idx and n not in members and idx[d][-1] > pos[-1]]
        assert not stale, "all mode left unpropagated rebuilds: %s" % stale[:5]

    # Informational: in haskell mode stale builds are expected, but only for non-haskell deps.
    info = ""
    if mode == "haskell":
        stale = [(n, d) for n, pos in idx.items() for d in deps(n)
                 if d in idx and idx[d][-1] > pos[-1]]
        info = "%d stale build(s), all due to non-haskell deps" % len(stale)
    return "%d entries / %d packages; %s" % (len(toks), len(idx), info or "all invariants hold")


# ---------------------------------------------------------------- tests

def t_help():
    p = gb(["--help"], WORK)
    ok(p, "help")
    for opt in ("--loop-list", "--propagate", "--dbpath", "--dep"):
        assert opt in p.stdout, "%s missing from --help" % opt
    assert "haskell" in p.stdout and "all" in p.stdout, "--propagate choices not documented"
    return "all options present"


def t_empty_input():
    p = run_db([], sandbox(), "empty")
    assert ok(p, "empty") == [], "empty input should print nothing"
    return "empty input -> empty output, exit 0"


def t_unknown_package():
    p = run_db(["no-such-package-xyz-42"], sandbox(), "unknown")
    bad(p, 1, "unknown")
    assert "not found" in p.stderr, "missing 'not found' message"
    assert p.stdout.strip() == "", "no package list on failure"
    return "unknown package -> exit 1 + not found"


def t_invalid_propagate():
    p = run_db(["--propagate=bogus", "curl"], sandbox(), "badprop")
    bad(p, 2, "bad --propagate")
    assert "invalid choice" in p.stderr, "argparse did not reject the value"
    return "invalid --propagate -> argparse exit 2"


def t_curl_git_default():
    toks = ok(run_db(CURL_GIT, sandbox(), "curlgit"), "curl git")
    assert toks == ["curl:nocheck", "git", "curl"], \
        "expected curl:nocheck git curl, got %s" % toks
    return " ".join(toks)


def t_curl_git_propagate_all():
    toks = ok(run_db(["--propagate=all"] + CURL_GIT, sandbox(), "curlgit-all"), "curl git all")
    assert toks == ["curl:nocheck", "git", "curl", "git"], \
        "expected old behaviour curl:nocheck git curl git, got %s" % toks
    return " ".join(toks)


def t_cycle_autotemplate():
    d = sandbox(name="auto")
    lp = os.path.join(d, "loop_list.lst")
    p = run_db(["--loop-list", lp] + MEDIA, d, "auto-template")
    bad(p, 1, "auto-template")
    assert p.stdout.strip() == "", "no partial output when unresolvable"
    assert "unresolvable dependency cycle" in p.stderr, "missing cycle report"
    assert "loop_list.lst" in p.stderr, "missing next-step hint"
    assert os.path.exists(lp), "loop_list template was not created"
    lines = [l.strip() for l in open(lp) if l.strip()]
    assert lines == ["[ffmpeg,gstreamer,pipewire,pulseaudio,wireplumber]->[]"], \
        "unexpected template: %s" % lines
    return "exit 1 + empty template appended"


def t_cycle_manual_ok():
    toks = run_with_looplist(MEDIA_MANUAL, MEDIA, "media")
    assert toks == MEDIA, "cycle order must follow the config, got %s" % toks
    return " ".join(toks)


def t_cycle_manual_reordered():
    manual = ("[wireplumber,pulseaudio,pipewire,gstreamer,ffmpeg]"
              "->[gstreamer,ffmpeg,pulseaudio,pipewire,wireplumber]")
    want = ["gstreamer", "ffmpeg", "pulseaudio", "pipewire", "wireplumber"]
    toks = run_with_looplist(manual, MEDIA, "media2")
    assert toks == want, "left side order-insensitive / right side order not honoured: %s" % toks
    return "left side order-insensitive, right side order applied"


def t_cycle_manual_mismatch():
    # Correct cycle members on the left, but the order is missing a package:
    # must fail instead of silently building in a wrong order.
    manual = "[ffmpeg,gstreamer,pipewire,pulseaudio,wireplumber]->[ffmpeg,gstreamer,pipewire,pulseaudio]"
    d = sandbox(manual, name="mismatch")
    lp = os.path.join(d, "loop_list.lst")
    before = open(lp).read()
    p = run_db(["--loop-list", lp] + MEDIA, d, "mismatch")
    bad(p, 1, "mismatch")
    assert "does not match its members" in p.stderr, "member mismatch was not detected"
    assert p.stdout.strip() == "", "no package list on failure"
    assert open(lp).read() == before, "a mismatched entry must not be appended again"
    return "member mismatch -> exit 1, no silent acceptance"


def t_manual_repeat():
    """A package may appear twice in the manual order: bootstrap with :nocheck,
    then a clean rebuild at the end. The sequence is emitted verbatim."""
    cases = [
        # Repeated package, the extra edge falls on a soft dep
        ("ffmpeg,gstreamer:nocheck,pipewire,pulseaudio,wireplumber,gstreamer",
         ["ffmpeg", "gstreamer:nocheck", "pipewire", "pulseaudio", "wireplumber", "gstreamer"]),
        # Repeated package, the extra edge falls on a hard dep
        ("ffmpeg,gstreamer,wireplumber,pulseaudio,pipewire,pulseaudio",
         ["ffmpeg", "gstreamer", "wireplumber", "pulseaudio", "pipewire", "pulseaudio"]),
        # Three occurrences of the same package
        ("gstreamer:nocheck,ffmpeg,pipewire,gstreamer,pulseaudio,wireplumber,gstreamer",
         ["gstreamer:nocheck", "ffmpeg", "pipewire", "gstreamer", "pulseaudio",
          "wireplumber", "gstreamer"]),
    ]
    for i, (order, want) in enumerate(cases):
        manual = "[ffmpeg,gstreamer,pipewire,pulseaudio,wireplumber]->[" + order + "]"
        d = sandbox(manual, name="repeat-%d" % i)
        lp = os.path.join(d, "loop_list.lst")
        before = open(lp).read()
        p = run_db(["--loop-list", lp] + MEDIA, d, "repeat-%d" % i)
        toks = ok(p, "repeat-%d" % i)
        assert toks == want, "manual sequence not emitted verbatim:\n  want %s\n  got  %s" % (want, toks)
        assert open(lp).read() == before, "loop_list must not be touched"
        assert not any("unresolvable" in line for line in p.stderr.splitlines()), \
            "a repeated package must not be reported as an unresolvable cycle"
    return "repeated packages expanded verbatim (soft edge / hard edge / 3 occurrences)"


def t_looplist_unknown_cycle():
    # Wrong cycle key (one member missing) falls through to
    # "unresolvable + append the correct template".
    manual = "[ffmpeg,gstreamer,pipewire,pulseaudio]->[ffmpeg,gstreamer,pipewire,pulseaudio]"
    d = sandbox(manual, name="unknown-cycle")
    lp = os.path.join(d, "loop_list.lst")
    p = run_db(["--loop-list", lp] + MEDIA, d, "unknown-cycle")
    bad(p, 1, "unknown-cycle")
    lines = [l.strip() for l in open(lp) if l.strip()]
    add = "[ffmpeg,gstreamer,pipewire,pulseaudio,wireplumber]->[]"
    assert add in lines, "correct template not appended for the real cycle: %s" % lines
    return "wrong cycle key -> exit 1 + correct template appended"


def t_manual_version_tag():
    """A manual entry may carry a git tag: pkg:<tag>[:nocheck], passed through
    verbatim so buildbot can turn it into --ver."""
    cases = [
        # tag + :nocheck, and two different tags for the same package
        ("ffmpeg,gstreamer:3.4.56:nocheck,pipewire,pulseaudio,wireplumber,gstreamer:4.0.1",
         ["ffmpeg", "gstreamer:3.4.56:nocheck", "pipewire", "pulseaudio",
          "wireplumber", "gstreamer:4.0.1"]),
        # tag only
        ("ffmpeg,gstreamer:v9,pipewire,pulseaudio,wireplumber",
         ["ffmpeg", "gstreamer:v9", "pipewire", "pulseaudio", "wireplumber"]),
        # :nocheck only (no tag), mixed with a tagged entry
        ("gstreamer:nocheck,ffmpeg,pipewire,pulseaudio,wireplumber,pipewire:1.0",
         ["gstreamer:nocheck", "ffmpeg", "pipewire", "pulseaudio",
          "wireplumber", "pipewire:1.0"]),
    ]
    for i, (order, want) in enumerate(cases):
        manual = "[ffmpeg,gstreamer,pipewire,pulseaudio,wireplumber]->[" + order + "]"
        toks = run_with_looplist(manual, MEDIA, "tag-%d" % i)
        assert toks == want, "tagged entries not passed through:\n  want %s\n  got  %s" % (want, toks)

    # An empty version would emit a broken build token, so it must be rejected.
    manual = "[ffmpeg,gstreamer,pipewire,pulseaudio,wireplumber]->[ffmpeg,gstreamer:,pipewire,pulseaudio,wireplumber]"
    d = sandbox(manual, name="tag-empty")
    lp = os.path.join(d, "loop_list.lst")
    p = run_db(["--loop-list", lp] + MEDIA, d, "tag-empty")
    bad(p, 1, "tag-empty")
    assert "empty version" in p.stderr, "empty version not reported"
    return "pkg:<tag>[:nocheck] passed through, empty version rejected"


def t_looplist_parse_tolerance():
    manual = "\n".join([
        "# comment line",
        "",
        "this is not a valid record",
        "[wireplumber,pulseaudio,pipewire,gstreamer,ffmpeg]"
        "->[ffmpeg,gstreamer,pipewire,pulseaudio,wireplumber]",
        "",
    ])
    toks = run_with_looplist(manual, MEDIA, "parse")
    assert toks == MEDIA, "valid entry not honoured, got %s" % toks
    return "comments, blank lines and invalid lines tolerated"


def t_manual_nocheck_suffix():
    manual = "[dotnet-core,dotnet-core-9.0]->[dotnet-core-9.0,dotnet-core:nocheck]"
    toks = run_with_looplist(manual, DOTNET, "nocheck")
    assert toks == ["dotnet-core-9.0", "dotnet-core:nocheck"], \
        ":nocheck suffix from loop_list not honoured, got %s" % toks
    return " ".join(toks)


def t_dotnet_manual():
    toks = run_with_looplist(DOTNET_MANUAL, DOTNET, "dotnet")
    assert toks == ["dotnet-core-9.0", "dotnet-core"], "dotnet cycle order wrong: %s" % toks
    return " ".join(toks)


def t_template_not_duplicated():
    d = sandbox(name="dup")
    lp = os.path.join(d, "loop_list.lst")
    run_db(["--loop-list", lp] + MEDIA, d, "dup1")
    first = open(lp).read()
    p = run_db(["--loop-list", lp] + MEDIA, d, "dup2")
    bad(p, 1, "dup2")
    assert open(lp).read() == first, "second run appended the template again"
    assert first.count("ffmpeg,gstreamer") == 1, "template duplicated: %r" % first
    return "repeated runs do not duplicate the template"


def t_whitelist_is_haskell():
    ns = internals()
    is_haskell = ns["is_haskell"]
    cases = {"haskell-aeson": True, "pandoc-cli": True, "haskell-hsopenssl": True,
             "curl": False, "git": False, "systemd": False, "ghc": False}
    wrong = []
    for pkg, want in cases.items():
        if pkg not in ns["package_db"]:
            raise Skip("db has no %s" % pkg)
        got = is_haskell(pkg)
        if got != want:
            wrong.append("%s: %s != %s" % (pkg, got, want))
    assert not wrong, "wrong classification: %s" % wrong
    # ghc-libs is a subpackage of ghc, so after pkgbase normalization it never
    # appears under its own name in depends, and the self reference is stripped.
    assert "ghc-libs" not in ns["package_db"]["ghc"]["depends"], "ghc-libs not normalized to ghc"
    assert "ghc" not in ns["package_db"]["ghc"]["depends"], "self reference not removed"
    return "ghc itself is not haskell (same-version rebuild keeps its soname); haskell pkgs detected"


def t_whitelist_propagation():
    ns = internals()
    prop = ns["rebuild_propagation"]
    old_mode = ns["args"].propagate
    try:
        # Real chain: pandoc-cli(haskell) <- python-pypandoc(non) <- apostrophe(non)
        NG = {"pandoc-cli", "python-pypandoc", "apostrophe"}
        ns["args"].propagate = "haskell"
        got = prop("pandoc-cli", NG)
        assert got == {"python-pypandoc"}, \
            "haskell mode must stop at the first non-haskell node, got %s" % sorted(got)
        ns["args"].propagate = "all"
        got_all = prop("pandoc-cli", NG)
        assert got_all == {"python-pypandoc", "apostrophe"}, \
            "all mode must return the full closure, got %s" % sorted(got_all)

        # A rebuilt non-haskell package propagates nothing.
        NG2 = {"curl", "git", "postgresql", "openssh"}
        ns["args"].propagate = "haskell"
        assert prop("curl", NG2) == set(), "non-haskell rebuild must not propagate"

        # Packages in manual_ordered are never pulled back in.
        ns["manual_ordered"].add("python-pypandoc")
        ns["args"].propagate = "haskell"
        assert prop("pandoc-cli", NG) == set(), "manual_ordered not filtered"
        ns["manual_ordered"].discard("python-pypandoc")

        # Reverse deps outside NG do not participate.
        ns["args"].propagate = "all"
        assert prop("pandoc-cli", {"pandoc-cli"}) == set(), "packages outside NG were pulled in"
    finally:
        ns["args"].propagate = old_mode
    return "all four semantics hold"


def t_big_propagate_all_semantics():
    """With --propagate=all every rebuilt package must pull its hard reverse deps
    along, inside the cycle, so nothing may stay stale there."""
    if NO_BIG:
        raise Skip("--no-big")
    return invariant_report(big("all"), "all")


def t_big_default_vs_all():
    if NO_BIG:
        raise Skip("--no-big")
    hs, al = ok(big("haskell"), "haskell"), ok(big("all"), "all")
    name = lambda toks: {t.removesuffix(":nocheck") for t in toks}
    assert name(hs) == name(al), "package sets differ between modes: %s" % (
        sorted(name(hs) ^ name(al))[:5])
    assert len(hs) < len(al), "haskell mode saved nothing: %d vs %d" % (len(hs), len(al))
    dup = lambda toks: len(toks) - len(name(toks))
    return "same %d packages, rebuild entries %d -> %d (saved %d, duplicate rate %d -> %d)" % (
        len(name(hs)), len(al), len(hs), len(al) - len(hs), dup(al), dup(hs))


def t_big_invariants():
    if NO_BIG:
        raise Skip("--no-big")
    return invariant_report(big("all"), "all") + " | " + invariant_report(big("haskell"), "haskell")


def t_big_determinism():
    if NO_BIG:
        raise Skip("--no-big")
    first = big("haskell", seed=0, fresh=True)
    second = big("haskell", seed=0, fresh=True)
    a, b = ok(first, "seed0-1"), ok(second, "seed0-2")
    assert a == b, "two runs with the same PYTHONHASHSEED differ"

    other = big("haskell", seed=12345, fresh=True)
    c = ok(other, "seed12345")
    name = lambda toks: {t.removesuffix(":nocheck") for t in toks}
    assert name(a) == name(c), "package set changed with the hash seed: %s" % (
        sorted(name(a) ^ name(c))[:5])
    return "same seed byte-identical; other seed only reorders (%d vs %d entries)" % (len(a), len(c))


TESTS = [
    t_help,
    t_empty_input,
    t_unknown_package,
    t_invalid_propagate,
    t_curl_git_default,
    t_curl_git_propagate_all,
    t_cycle_autotemplate,
    t_cycle_manual_ok,
    t_cycle_manual_reordered,
    t_cycle_manual_mismatch,
    t_manual_repeat,
    t_manual_version_tag,
    t_looplist_unknown_cycle,
    t_looplist_parse_tolerance,
    t_manual_nocheck_suffix,
    t_dotnet_manual,
    t_template_not_duplicated,
    t_whitelist_is_haskell,
    t_whitelist_propagation,
    t_big_propagate_all_semantics,
    t_big_default_vs_all,
    t_big_invariants,
    t_big_determinism,
]


def main():
    global DB, GB, WORK, TIMEOUT, NO_BIG, LST_DIR
    ap = argparse.ArgumentParser(description="genrebuild regression tests")
    ap.add_argument("--dbpath", default=os.environ.get("GENREBUILD_DBPATH", ""),
                    help="pacman sync db directory (required)")
    ap.add_argument("--genrebuild", default=os.path.join(HERE, "genrebuild"))
    ap.add_argument("--lst-dir", default=HERE)
    ap.add_argument("--no-big", action="store_true")
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--keep", action="store_true", help="keep the temporary directory")
    args = ap.parse_args()

    if not args.dbpath or not os.path.isdir(args.dbpath):
        ap.error("--dbpath must point at a real pacman sync db directory")
    if not os.path.exists(args.genrebuild):
        ap.error("script under test not found: %s" % args.genrebuild)

    DB = args.dbpath
    GB = os.path.abspath(args.genrebuild)
    LST_DIR = args.lst_dir
    TIMEOUT = args.timeout
    NO_BIG = args.no_big
    WORK = os.path.join(tempfile.mkdtemp(prefix="gb-regress-"), "gb-regress")
    os.makedirs(WORK, exist_ok=True)

    print("script under test: %s" % GB)
    print("db               : %s" % DB)
    print("work dir         : %s\n" % WORK, flush=True)

    for fn in TESTS:
        case(fn)

    passed = [r for r in RESULTS if r[1] == "PASS"]
    failed = [r for r in RESULTS if r[1] == "FAIL"]
    skipped = [r for r in RESULTS if r[1] == "SKIP"]

    print("\n" + "=" * 72)
    print("%d tests: %d PASS / %d FAIL / %d SKIP in %.1fs" % (
        len(RESULTS), len(passed), len(failed), len(skipped),
        sum(r[2] for r in RESULTS)))
    if failed:
        print("\nfailures:")
        for name, _, _, detail in failed:
            print("  - %s: %s" % (name, detail))
    if skipped:
        print("\nskipped:")
        for name, _, _, detail in skipped:
            print("  - %s: %s" % (name, detail))

    if not args.keep:
        shutil.rmtree(os.path.dirname(WORK), ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

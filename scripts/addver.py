#!/usr/bin/env python3
"""Add version parameters to packages that appear multiple times in a build list.

Reads a build list (comma and/or whitespace separated; entries may carry
":flag" suffixes such as ":nocheck") and, for every package that has to be
built more than once, assigns increasing release versions based on the gap
between the x86_64 and loong64 repositories, so that the same version is
not built twice.

Versions are queried with::

    compare86.py [switch] -p <pkgname>

which prints lines like::

    haskell-random found in repo extra of x86_64 with ver=1.2.1.3-307
    haskell-random found in repo extra of loong64 with ver=1.2.1.3-304

Only the release number after "-" is used, and only when the pkgver part
(including any epoch) matches on both sides.  Versions are inserted into
the task string right after the package name; buildbot.sh parses
"pkgname:version:nocheck" as name + --ver + --nocheck.

Rules (N = number of builds, G = version gap between the two repos):

* N == 1 or G <= 1: no version parameter is added (default = latest).
* otherwise        : the first min(N-1, G) builds get loong+1 ..
                     loong+min(N-1,G) (never above upstream), the
                     remaining builds - including the last one - stay
                     default and build the latest version.

Note: the default build (no version parameter) always builds the latest
upstream version, so intermediate versions such as 1.2.1.3-305 must exist
as git tags in the upstream package repository (pkgver-pkgrel) for this
to work.

Usage: addver.py [options] <pkglist>
  -s, --stag            query staging repos (also accepts "-stag")
  -T, --test            query testing repos (also accepts "-test")
  -c, --compare86 PATH  compare86.py executable (default: $SCRIPTSPATH/compare86.py)
  -v, --verbose         print per-package decisions to stderr
"""

import os
import re
import subprocess
import sys
from collections import Counter

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_COMPARE86 = os.path.join(
    os.environ.get('SCRIPTSPATH', SCRIPT_DIR), 'compare86.py')

VER_LINE = re.compile(r'^\S+ found in repo \S+ of (x86_64|loong64) with ver=(\S+)$')


def warn(msg):
    print(f"addver: {msg}", file=sys.stderr)


def split_version(ver):
    """Split "pkgver-rel" into (pkgver, rel). None if not usable."""
    if '-' not in ver:
        return None
    pkgver, rel = ver.rsplit('-', 1)
    if not pkgver or not rel.isdigit():
        return None
    return pkgver, int(rel)


def get_versions(compare86, switch, name):
    """Query x86_64 and loong64 versions via compare86.py -p.

    Returns (x86_version, loong64_version) as strings, or (None, None)
    when the lookup fails for any reason.
    """
    cmd = [compare86]
    if switch:
        cmd.append(switch)
    cmd += ['-p', name]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        warn(f"cannot run {compare86}: {e}")
        return None, None
    if proc.returncode != 0:
        warn(f"{compare86} exited with {proc.returncode}")
        return None, None
    x86 = loong = None
    for line in proc.stdout.splitlines():
        m = VER_LINE.match(line)
        if not m:
            continue
        if m.group(1) == 'x86_64':
            x86 = m.group(2)
        else:
            loong = m.group(2)
    return x86, loong


def plan_versions(name, n, compare86, switch, verbose):
    """Return a list of n version strings (None = no version parameter)."""
    x86, loong = get_versions(compare86, switch, name)
    if x86 is None or loong is None:
        warn(f"{name}: version lookup failed (x86={x86}, loong={loong}), "
             "leaving unchanged")
        return [None] * n
    xv = split_version(x86)
    lv = split_version(loong)
    if xv is None or lv is None:
        warn(f"{name}: cannot parse versions x86={x86}, loong={loong}, "
             "leaving unchanged")
        return [None] * n
    xpkgver, xrel = xv
    lpkgver, lrel = lv
    if xpkgver != lpkgver:
        warn(f"{name}: pkgver differs (x86={x86}, loong={loong}), "
             "leaving unchanged")
        return [None] * n
    gap = xrel - lrel
    if gap <= 1:
        if verbose:
            print(f"addver: {name}: {n} builds, gap={gap}, "
                  "no versions needed", file=sys.stderr)
        return [None] * n
    # The last build never gets a version parameter (default = latest);
    # at most gap versions are available (never above upstream).
    count = min(n - 1, gap)
    versions = [f"{xpkgver}-{lrel + i + 1}" if i < count else None
                for i in range(n)]
    if verbose:
        shown = ", ".join(v if v else 'default' for v in versions)
        print(f"addver: {name}: {n} builds, gap={gap}, versions: {shown}",
              file=sys.stderr)
    return versions


def parse_entries(text):
    """Parse the input into [(name, [flags...]), ...] in order."""
    entries = []
    for item in re.split(r'[,\s]+', text.strip()):
        if not item:
            continue
        parts = item.split(':')
        entries.append((parts[0], [p for p in parts[1:] if p]))
    return entries


def has_version(flags):
    """True when the entry already carries an explicit version
    (the second field starts with a digit, e.g. "name:1.2.1.3-305")."""
    return bool(flags) and flags[0][:1].isdigit()


def main():
    compare86 = DEFAULT_COMPARE86
    switch = None
    verbose = False
    args = []

    # Manual parsing: "-stag"/"-test" must be accepted and translated to
    # "-s"/"-T" (compare86.py's argparse rejects the combined forms).
    argv = sys.argv[1:]
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ('-s', '--stag', '-stag'):
            switch = '-s'
        elif a in ('-T', '--test', '-test'):
            switch = '-T'
        elif a in ('-c', '--compare86'):
            i += 1
            if i >= len(argv):
                warn("--compare86 requires a path")
                return 1
            compare86 = argv[i]
        elif a in ('-v', '--verbose'):
            verbose = True
        elif a in ('-h', '--help'):
            print(__doc__)
            return 0
        else:
            args.append(a)
        i += 1

    text = ' '.join(args)
    entries = parse_entries(text)
    if not entries:
        return 0

    counts = Counter(name for name, _ in entries)

    # Packages that already carry an explicit version are left untouched.
    skipped = {name for name, _ in entries
               if any(has_version(f) for _, f in entries if _ == name)}

    # Plan the versions per package.
    plan = {}  # name -> list of versions in entry order (None = default)
    for name, n in counts.items():
        if n <= 1 or name in skipped:
            continue
        plan[name] = plan_versions(name, n, compare86, switch, verbose)

    # Rebuild the list, inserting "name:version:flags...".
    out = []
    for name, flags in entries:
        ver = None
        if name in plan and plan[name]:
            ver = plan[name].pop(0)
        if ver is not None:
            out.append(':'.join([name, ver] + flags))
        else:
            out.append(':'.join([name] + flags))
    print(','.join(out))
    return 0


if __name__ == '__main__':
    sys.exit(main())

#!/usr/bin/env python3
import os
import pyalpm
import argparse
import requests
from datetime import datetime
from signal import signal, SIGPIPE, SIG_DFL

home_dir = os.path.expanduser("~")
cache_dir = os.path.join(home_dir, ".cache", "compare86")

# Define the repo file paths
x86_repo_path = "x86"
loong64_repo_path = "loong"
mirror_x86 = "https://mirrors.pku.edu.cn/archlinux/"
mirror_loong64 = "https://loongarchlinux.lcpu.dev/loongarch/archlinux/"
source_repos = ['core', 'extra']

pkgtime = {}

signal(SIGPIPE, SIG_DFL)


# Download repo db from mirrors.
def download_file(source, dest):
    headers = {"User-Agent": "Mozilla/5.0", }
    repo_path = os.path.dirname(dest)
    if not os.path.exists(repo_path):
        os.makedirs(repo_path)
    try:
        # Download the file and save it to dest_path
        response = requests.get(source, headers=headers)
        response.raise_for_status()
        with open(dest, 'wb') as out_file:
            out_file.write(response.content)
    except Exception as e:
        print(f"Error downloading file: {e}")


# cache all package buildtime
def get_builddate():
    for repo in source_repos:
        x86_db = load_repo(os.path.join(cache_dir, x86_repo_path), repo)
        for pkg in x86_db.pkgcache:
            pkgtime[pkg.base] = pkg.builddate


def update_repo():
    for repo in source_repos:
        download_file(f"{mirror_x86}{repo}/os/x86_64/{repo}.db",
                      f"{cache_dir}/{x86_repo_path}/sync/{repo}.db")
        download_file(f"{mirror_loong64}{repo}/os/loong64/{repo}.db",
                      f"{cache_dir}/{loong64_repo_path}/sync/{repo}.db")


# Load the repository database
def load_repo(repo_path, repo):
    handle = pyalpm.Handle("/", repo_path)
    try:
        db = handle.register_syncdb(repo, 0)
        return db
    except pyalpm.error as e:
        print(f"Failed to load repo {repo_path}: {e}")
        return None


# Find packages with all depends satisfied
def safe_tobuild():
    x86 = {}
    x86_repo = {}
    for repo in source_repos:
        x86_db = load_repo(os.path.join(cache_dir, x86_repo_path), repo)
        for pkg in x86_db.pkgcache:
            alldep = pkg.makedepends + pkg.checkdepends + pkg.depends
            alldep = {dep.split("=")[0].split(">")[0].split("<")[0] for dep in alldep}
            if (not pkg.base in x86):
                x86[pkg.base] = set()
            x86[pkg.base] |= alldep
            x86_repo[pkg.base] = repo
    loong = {}
    for repo in source_repos:
        loong_db = load_repo(os.path.join(cache_dir, loong64_repo_path), repo)
        loong_pkg = {pkg.base: pkg.version for pkg in loong_db.pkgcache}
        loong = {**loong, **loong_pkg}
    for pkg_name in x86:
        if (not pkg_name in loong) and (all(pkg in loong for pkg in x86[pkg_name])):
            print(f"{pkg_name:34} {x86_repo[pkg_name]}")


# Compare all packages in both repos
def compare_all():
    x86 = {}
    for repo in source_repos:
        x86_db = load_repo(os.path.join(cache_dir, x86_repo_path), repo)
        x86_pkg = {pkg.base: pkg.version for pkg in x86_db.pkgcache}
        x86 = {**x86, **x86_pkg}

    loong = {}
    for repo in source_repos:
        loong_db = load_repo(os.path.join(cache_dir, loong64_repo_path), repo)
        loong_pkg = {pkg.base: pkg.version for pkg in loong_db.pkgcache}
        loong = {**loong, **loong_pkg}

    allpkg = {**loong, **x86}
    for pkg_name in allpkg:
        if pkg_name in x86:
            x86_version = x86[pkg_name]
        else:
            x86_version = 'missing'
        if pkg_name in loong:
            loong64_version = loong[pkg_name]
        else:
            loong64_version = 'missing'
        print(f"{pkg_name:24} {x86_version:24} {loong64_version:24}")


# Compare the packages in one repos
def compare_repos(x86_db, loong64_db, showtime, show_newer=False):
    get_builddate()
    time_now = datetime.now()
    x86_pkg = {pkg.base: pkg.version for pkg in x86_db.pkgcache}
    loong64_pkg = {pkg.base: pkg.version for pkg in loong64_db.pkgcache}

    # Find common packages and compare their versions
    common_pkgs = set(x86_pkg.keys()) & set(loong64_pkg.keys())
    sorted_pkgs = sorted(common_pkgs, key=lambda pkg: pkgtime.get(pkg, 0))
    for pkg_name in sorted_pkgs:
        x86_version = x86_pkg[pkg_name]
        loong64_version = loong64_pkg[pkg_name]
        if pyalpm.vercmp(loong64_version, x86_version) >= 0 and (not show_newer):
            continue # loong64's version > x86's version: not outdated
        if x86_version == loong64_version:
            continue
        x86_pkgver, x86_relver = x86_version.split('-')
        loong_pkgver, loong_relver = loong64_version.split('-')
        loong_relver = loong_relver.split('.')[0]
        if x86_pkgver == loong_pkgver and x86_relver == loong_relver:
            continue
        if showtime:
            time_then = datetime.fromtimestamp(pkgtime[pkg_name])
            delta = (time_now - time_then).days
            print(f"{pkg_name:24} {x86_version:24} {loong64_version:24} {delta} days old")
        else:
            print(f"{pkg_name:24} {x86_version:24} {loong64_version:24}")


# compare one package
def show_package(pkg, repo):
    pkg = repo.get_pkg(pkg)
    if pkg:
        return pkg.version
    return None

def main():
    global source_repos

    parser = argparse.ArgumentParser(description="Compare packages between x86 and loong.")
    parser.add_argument("-S", "--sync", action="store_true", help="Sync the database.")
    parser.add_argument("-H", "--header", action="store_true", help="Output header.")
    parser.add_argument("-C", "--core", action="store_true", help="Compare core db.")
    parser.add_argument("-E", "--extra", action="store_true", help="Compare extra db.")
    parser.add_argument("-A", "--all", action="store_true", help="Compare all dbs.")
    parser.add_argument("-B", "--build", action="store_true", help="Find package to build.")
    parser.add_argument("-t", "--time", action="store_true", help="Show package freshness.")
    parser.add_argument("-p", "--package", type=str, help="Find package in dbs.")
    parser.add_argument("-s", "--stag", action="store_true", help="Consider staging db.")
    parser.add_argument("-T", "--test", action="store_true", help="Consider testing db.")
    parser.add_argument("-n", "--newer", action="store_true", help="Also show the packages that are newer than x86's.")

    args = parser.parse_args()

    if args.time is None:
        args.time = False

    if not os.path.exists(f"{cache_dir}/{x86_repo_path}"):
        args.sync = True

    if args.stag:
        source_repos = ["core-staging", "extra-staging"]

    if args.test:
        source_repos = ["core-testing", "extra-testing"]

    if args.sync:
        update_repo()

    if args.build:
        safe_tobuild()

    if args.header and (args.core or args.extra or args.all):
        print("Package                  x86_ver                  loong64_ver")
        print("-----------------------------------------------------------------")

    if args.all:
        compare_all()

    if args.core or args.extra:
        repo = source_repos[0] if args.core else source_repos[1]
        x86_db = load_repo(os.path.join(cache_dir, x86_repo_path), repo)
        loong64_db = load_repo(os.path.join(cache_dir, loong64_repo_path), repo)
        compare_repos(x86_db, loong64_db, args.time, args.newer)

    if args.package:
        if args.stag and args.test:
            all_repos = ["core", "extra", "core-staging", "extra-staging", "core-testing", "extra-testing"]
        else:
            all_repos = source_repos
        for r in all_repos:
            x86_db = load_repo(os.path.join(cache_dir, x86_repo_path), r)
            ver = show_package(args.package, x86_db)
            if ver:
                print(f"{args.package} found in repo {r} of x86_64 with ver={ver}")
        for r in all_repos:
            loong_db = load_repo(os.path.join(cache_dir, loong64_repo_path), r)
            ver = show_package(args.package, loong_db)
            if ver:
                print(f"{args.package} found in repo {r} of loong64 with ver={ver}")

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
import os
import pyalpm
import argparse
import urllib.request

pwd = os.getcwd()

# Define the repo file paths
x86_repo_path = "x86"
loong64_repo_path = "loong"
mirror_x86 = "https://mirrors.pku.edu.cn/archlinux/"
mirror_loong64 = "https://loongarchlinux.lcpu.dev/loongarch/archlinux/"

headers = { "User-Agent": "Mozilla/5.0", }

def download_file(source, dest):
    repo_path = os.path.dirname(dest)
    if not os.path.exists(repo_path):
        os.makedirs(repo_path)
    try:
        # Download the file and save it to dest_path
        request = urllib.request.Request(source, headers=headers)
        with urllib.request.urlopen(request) as response:
            with open(dest, 'wb') as out_file:
                out_file.write(response.read())
    except Exception as e:
        print(f"Error downloading file: {e}")


def update_repo():
    for repo in ['core', 'extra']:
        download_file(f"{mirror_x86}{repo}/os/x86_64/{repo}.db",
                      f"{x86_repo_path}/sync/{repo}.db")
    for repo in ['core-testing', 'extra-testing', 'core-staging', 'extra-staging']:
        download_file(f"{mirror_loong64}{repo}/os/loong64/{repo}.db",
                      f"{loong64_repo_path}/sync/{repo}.db")

# Load the repository database
def load_repo(repo_path, repo):
    handle = pyalpm.Handle("/", repo_path)
    try:
        db = handle.register_syncdb(repo, 0)
        return db
    except pyalpm.error as e:
        print(f"Failed to load repo {repo_path}: {e}")
        return None


# Compare the packages in both repos
def compare_repos(x86_db, loong64_db, loong64_db2):
    x86_pkg = {pkg.base: pkg.version for pkg in x86_db.pkgcache}
    loong64_pkg_dict = {pkg.base: pkg.version for pkg in loong64_db.pkgcache}
    loong64_pkg_dict2 = {pkg.base: pkg.version for pkg in loong64_db2.pkgcache}
    loong64_pkg = {**loong64_pkg_dict, **loong64_pkg_dict2}

    # Find common packages and compare their versions
    common_pkgs = set(x86_pkg.keys()) & set(loong64_pkg.keys())
    for pkg_name in common_pkgs:
        x86_version = x86_pkg[pkg_name]
        loong64_version = loong64_pkg[pkg_name]
        if x86_version == loong64_version:
            continue
        x86_pkgver, x86_relver = x86_version.split('-')
        loong_pkgver, loong_relver = loong64_version.split('-')
        loong_relver = loong_relver.split('.')[0]
        if x86_pkgver == loong_pkgver and x86_relver == loong_relver:
            continue
        print(f"{pkg_name:15} {x86_version:15} {loong64_version:15}")


# compare one package
def show_package(pkg, repo):
    pkg = repo.get_pkg(pkg)
    if pkg:
        return pkg.version
    return None

def main():
    parser = argparse.ArgumentParser(description="Compare packages between x86 and loong.")
    parser.add_argument("-S", "--sync", action="store_true", help="Sync the database.")
    parser.add_argument("-H", "--header", action="store_true", help="Output header.")
    parser.add_argument("-C", "--core", action="store_true", help="Compare core db.")
    parser.add_argument("-E", "--extra", action="store_true", help="Compare extra db.")
    parser.add_argument("-p", "--package", type=str, help="The name of the package to compare.")

    args = parser.parse_args()

    if args.sync:
        update_repo()

    if args.header and (args.core or args.extra):
        print("Package         x86_ver         loong64_ver")

    if args.core:
        x86_db = load_repo(os.path.join(pwd, x86_repo_path), "core")
        loong64_db = load_repo(os.path.join(pwd, loong64_repo_path), "core-testing")
        loong64_db2 = load_repo(os.path.join(pwd, loong64_repo_path), "core-staging")
        compare_repos(x86_db, loong64_db, loong64_db2)

    if args.extra:
        x86_db = load_repo(os.path.join(pwd, x86_repo_path), "extra")
        loong64_db = load_repo(os.path.join(pwd, loong64_repo_path), "extra-testing")
        loong64_db2 = load_repo(os.path.join(pwd, loong64_repo_path), "extra-staging")
        compare_repos(x86_db, loong64_db, loong64_db2)

    if args.package:
        for r in ['core', 'extra']:
            x86_db = load_repo(os.path.join(pwd, x86_repo_path), r)
            ver = show_package(args.package, x86_db)
            if ver:
                print(f"{args.package} found in repo {r} of x86_64 with ver={ver}")
        for r in ['core', 'extra', 'core-testing', 'extra-testing', 'core-staging', 'extra-staging']:
            loong_db = load_repo(os.path.join(pwd, loong64_repo_path), r)
            ver = show_package(args.package, loong_db)
            if ver:
                print(f"{args.package} found in repo {r} of loong64 with ver={ver}")

if __name__ == "__main__":
    main()

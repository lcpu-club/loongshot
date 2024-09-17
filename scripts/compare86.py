#!/usr/bin/env python3
import os
import pyalpm
import argparse
import subprocess

pwd = os.getcwd()

# Define the repo file paths
x86_repo_path = "x86"
loong64_repo_path = "loong"


def update_repo(arch, dbpath):
    pacman_command = [ "sudo", "pacman", "--arch", arch, "--dbpath", dbpath, "-Sy" ]
    if not os.path.exists(dbpath):
        os.makedirs(dbpath)
    try:
        result = subprocess.run(pacman_command, check=True, text=True, capture_output=True)
        # print("Pacman output:", result.stdout)
    except subprocess.CalledProcessError as e:
        print(f"Error occurred: {e}")
        print("Pacman error output:", e.stderr)
    current_user = subprocess.run("whoami", capture_output=True, text=True).stdout.strip()
    command = ["sudo", "chown", "-R", f"{current_user}:{current_user}", dbpath]
    subprocess.run(command, check=True)


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
        update_repo("x86_64", x86_repo_path)
        update_repo("loong64", loong64_repo_path)

    if args.header:
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

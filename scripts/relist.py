#!/usr/bin/env python3
import os
import pyalpm
import argparse
import sys

home_dir = os.path.expanduser("~")
cache_dir = os.path.join(home_dir, ".cache", "compare86")

# Define the repo file paths
x86_repo_path = "x86"
x86_repos = ['core', 'extra']

pkgbase = {}
pkgname = {}

whitelist={"mupdf":"libmupdf"}

# cache all package buildtime
def get_pkgbase():
    for repo in x86_repos:
        x86_db = load_repo(os.path.join(cache_dir, x86_repo_path), repo)
        for pkg in x86_db.pkgcache:
            pkgbase[pkg.name] = pkg.base
            pkgname[pkg.base] = pkg.name
    for key in whitelist:
        pkgname[key] = whitelist[key]


# Load the repository database
def load_repo(repo_path, repo):
    handle = pyalpm.Handle("/", repo_path)
    try:
        db = handle.register_syncdb(repo, 0)
        return db
    except pyalpm.error as e:
        print(f"Failed to load repo {repo_path}: {e}")
        return None


def read_and_convert_file(file_path, kvp):
    data = []
    # Read the file line by line and convert to dict
    if file_path is None:
        istream = sys.stdin
    else:
        istream = open(file_path, 'r')
    for line in istream:
        line = line.strip()  # Remove leading/trailing spaces
        if line.startswith("--"):
            data.append(line)
            continue
        if line:  # Skip empty lines
            if line.endswith(":nocheck"):
                pkg = line.split(":")[0]
                data.append(f"{kvp[pkg]}:nocheck")
            else:
                data.append(kvp[line])
    if file_path is None:
        for item in data:
            print(item)
    else:
        istream.close()
        # Write the updated data back to the file
        with open(file_path, 'w') as f:
            for item in data:
                f.write(f"{item}\n")

def main():
    parser = argparse.ArgumentParser(description="convert from pkgname to pkgbase and vice versa.")
    parser.add_argument("-b", "--name-to-base", action="store_true", help="From pkgname to pkgbase.")
    parser.add_argument("-n", "--base-to-name", action="store_true", help="From pkgbase to pkgname.")
    parser.add_argument("-f", "--file", type=str, help="The list file to process.")

    args = parser.parse_args()

    get_pkgbase()

    if args.name_to_base:
        read_and_convert_file(args.file, pkgbase)
    elif args.base_to_name:
        read_and_convert_file(args.file, pkgname)

if __name__ == "__main__":
    main()

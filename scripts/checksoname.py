#!/usr/bin/env python3

import os
import re
import requests
import argparse
from collections import defaultdict
import tarfile
import tempfile

mirror_loong64 = "https://loongarchlinux.lcpu.dev/loongarch/archlinux/"
repos = ['core', 'extra']

def extract_tar_gz(tar_gz_path, extract_path):
    with tarfile.open(tar_gz_path, "r:gz") as tar:
        tar.extractall(path=extract_path)

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

def extract_lib_name_and_version(lib_line):
    """Extract library name and version from the given line."""
    match = re.match(r'^(.*/)?(lib[a-zA-Z0-9_-]+)\.so((\.\d+)+)$', lib_line)
    if match:
        lib_name = match.group(2)  # Capture full library name with version
        version = match.group(3)  # Capture version segments
        return lib_name, version
    return None, None

def scan_directory_for_libs(dir_path, filename):
    """Scan the given directory for 'links' files and extract libraries and their versions."""
    lib_versions = defaultdict(lambda: defaultdict(set))

    for entry in os.listdir(dir_path):
        entry_path = os.path.join(dir_path, entry)
        if os.path.isdir(entry_path):
            links_file_path = os.path.join(entry_path, filename)
            if os.path.isfile(links_file_path):
                try:
                    with open(links_file_path, 'r') as f:
                        for line in f:
                            lib_name, version = extract_lib_name_and_version(line.strip())
                            if lib_name and version:  # Ignore non library lines
                                lib_versions[lib_name][entry].add(version)
                except Exception as e:
                    print(f"Error reading {links_file_path}: {e}")
    return lib_versions

def find_orphan_libs(links, files):
    for lib_name, pkg_name in links.items():
        for pkg, version in pkg_name.items():
            allversion = set().union(*files[lib_name].values())
            if not version.issubset(allversion):
                print(f"{pkg} links to orphan {lib_name}.so{list(version)[0]}")

def main():
    parser = argparse.ArgumentParser(description="Check file db and links db for orphans.")
    parser.add_argument("-C", "--core", action="store_true", help="Check core db.")

    args = parser.parse_args()
    if args.core:
        repo = 'core'
    else:
        repo = 'extra'

    temp_dir = tempfile.TemporaryDirectory()
    links_dir = os.path.join(temp_dir.name, 'links')
    os.makedirs(links_dir)
    files_dir = os.path.join(temp_dir.name, 'files')
    os.makedirs(files_dir)
    download_file(f"{mirror_loong64}core/os/loong64/core.files.tar.gz",
                  f"{temp_dir.name}/core.files.tar.gz")
    print(f"core.files.tar.gz has downloaded.")
    extract_tar_gz(f"{temp_dir.name}/core.files.tar.gz", files_dir)
    download_file(f"{mirror_loong64}extra/os/loong64/extra.files.tar.gz",
                  f"{temp_dir.name}/extra.files.tar.gz")
    print(f"extra.files.tar.gz has downloaded.")
    extract_tar_gz(f"{temp_dir.name}/extra.files.tar.gz", files_dir)

    download_file(f"{mirror_loong64}{repo}/os/loong64/{repo}.links.tar.gz",
                  f"{temp_dir.name}/{repo}.links.tar.gz")
    print(f"{repo}.links.tar.gz has downloaded.")
    extract_tar_gz(f"{temp_dir.name}/{repo}.links.tar.gz", links_dir)

    links_libs = scan_directory_for_libs(links_dir, 'links')
    files_libs = scan_directory_for_libs(files_dir, 'files')
    find_orphan_libs(links_libs, files_libs)


if __name__ == "__main__":
    main()

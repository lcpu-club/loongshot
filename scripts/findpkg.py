#!/usr/bin/env python3
import os
import sys
import tempfile
import pyalpm

def find_pkg(db, repo, package):
    dbpath = f"{db}/{repo}/os/loong64/{repo}.db"
    with tempfile.TemporaryDirectory() as d:
        sync_dir = os.path.join(d, "sync")
        os.mkdir(sync_dir)
        os.symlink(os.path.abspath(dbpath), os.path.join(sync_dir, f"{repo}.db"))

        handle = pyalpm.Handle(".", d)
        db_handle = handle.register_syncdb(repo, 0)
        pkg = db_handle.get_pkg(package)
        return pkg


repo_path, repo, package = sys.argv[1:4]

ver = find_pkg(repo_path, repo, package)
if ver is None and '-' in repo:
    ver = find_pkg(repo_path, repo.split('-')[0], package)
if ver is None:
    print("")
else:
    print(ver.version)

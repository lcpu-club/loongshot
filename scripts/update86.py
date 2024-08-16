#!/usr/bin/env python3

import pyalpm
import requests
import os

DBS = ['core', 'extra']
website_url = 'http://127.0.0.1/op/upx86/'

def get_package_versions():
    handle = pyalpm.Handle("/", "/var/lib/pacman")
    package_versions = {}
    for db in DBS:
        db_handle = handle.register_syncdb(db, 0)
        for pkg in db_handle.search(""):
            pkgname = pkg.name
            pkgver = pkg.version
            package_versions[pkgname] = pkgver

    return package_versions

def update_versions_to_website(package_versions):
    for pkgname, pkgver in package_versions.items():
        headers = {'User-Agent': 'python-app',
                   'Content-Type': 'application/x-www-form-urlencoded'}
        response = requests.post(f'{website_url}{pkgname}', data={'ver': pkgver}, headers=headers)
        if response.status_code == 200:
            try:
                result = response.json().get('result', 'Unknown')
            except:
                result = 'json error'
            print(f'Successfully updated {pkgname} to version {pkgver}, result: {result}')
        else:
            print(f'Failed to update {pkgname}. Status code: {response.status_code}')

def main():
    os.system(f'sudo pacman -Sy --noconfirm --needed')
    package_versions = get_package_versions()
    update_versions_to_website(package_versions)

if __name__ == "__main__":
    main()

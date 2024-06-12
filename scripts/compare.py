#!/bin/env python3
# 
# compare package db between x86_64 and loong64
# borrowed table style from felixonmars@github

import pyalpm
import os

DBS = ["core", "extra"]

common_header = '''
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="https://lib.baomitu.com/bulma/0.9.4/css/bulma.min.css">
<table class="table is-hoverable">
<thead><tr><th rowspan=2>Arch</th>
<th colspan=3>[core]</th><th colspan=3>[extra]</th>
<tr>
<th>Up-to-date (Ratio%)</th><th>Outdated</th><th>Missing</th>
<th>Up-to-date (Ratio%)</th><th>Outdated</th><th>Missing</th>
</tr></thead><tbody>'''

pkgdata = {}
pkgcount = {}

# x86_64 as baseline
html_content = common_header + "<tr><td>x86_64</td>"
handle = pyalpm.Handle("/", "/var/lib/pacman")
for repo in DBS:
    db_handle = handle.register_syncdb(repo, 0)
    pkgcount[repo] = 0
    for package in db_handle.search(""):
        pkgdata[package.name] = package.version
        pkgcount[repo] += 1
    html_content += f"<td>{pkgcount[repo]}</td><td>0</td><td>0</td>"
html_content += "</tr>"

# loong64 as comparison
arch="loong64"
html_content += f"<tr><td>{arch}</td>"
for repo in DBS:
    db_handle = handle.register_syncdb(f"{arch}-{repo}", 0)
    uptodate = 0
    outdated = 0
    for package in db_handle.search(""):
        if package.name in pkgdata:
            version = package.version.split("-")
            version[1] = version[1].split(".")[0]
            version = "-".join(version)
            if pkgdata[package.name] == version:
                uptodate += 1
            else:
                outdated += 1
    percent = round((uptodate * 100.0 / pkgcount[repo]), 2)
    html_content += f"<td><font color=green>{uptodate} ({percent}%)</font></td>"
    html_content += f"<td><font color=orange>{outdated}</font></td>"
    html_content += f"<td><font color=red>{pkgcount[repo] - uptodate - outdated}</font></td>"
html_content += "</tr></tbody></table></div>"

# Write the HTML content to a file
with open('compare.html', 'w') as f:
    f.write(html_content)

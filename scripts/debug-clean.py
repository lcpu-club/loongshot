#!/usr/bin/env python3

import os
import sys
import re
from dbcmd import DatabaseManager

def get_package_bases_from_db(db_manager):
    """Fetch all unique base names from database"""
    bases = set()
    try:
        with db_manager.transaction() as cursor:
            cursor.execute("SELECT DISTINCT base FROM packages")
            for row in cursor.fetchall():
                if row[0]:
                    bases.add(row[0])
    except Exception as e:
        print(f"Error fetching bases from database: {e}", file=sys.stderr)
    return bases

def find_zst_files(directory):
    """Find all *.zst files in the specified directory"""
    zst_files = []
    try:
        for filename in os.listdir(directory):
            if filename.endswith('.zst'):
                zst_files.append(filename)
    except Exception as e:
        print(f"Error reading directory {directory}: {e}", file=sys.stderr)
    return sorted(zst_files)

def extract_base_and_version_from_filename(filename):
    """
    Extract base name and version from filename
    Format: $(base)-debug-$(version)-[loong64|any].pkg.tar.zst
    """
    # Match pattern: base-debug-version-[loong64|any].pkg.tar.zst
    # Version can contain digits, dots, dashes (e.g., 0.6.1-3, 4.0.3-5)
    pattern = r'^(.+)-debug-(.+)-(loong64|any)\.pkg\.tar\.zst$'
    match = re.match(pattern, filename)
    if match:
        return match.group(1), match.group(2)
    return None, None

def find_multiversion_files(zst_files):
    """Find files with the same base but different versions"""
    from collections import defaultdict

    base_versions = defaultdict(list)
    for filename in zst_files:
        base, version = extract_base_and_version_from_filename(filename)
        if base:
            base_versions[base].append((filename, version))

    # Filter to only include bases with multiple versions
    multiversion = {base: files for base, files in base_versions.items() if len(files) > 1}
    return multiversion


def main():
    if len(sys.argv) < 2:
        print("Usage: python debug-clean.py <directory_path>", file=sys.stderr)
        print("Example: python debug-clean.py /path/to/packages", file=sys.stderr)
        sys.exit(1)

    directory = sys.argv[1]

    if not os.path.isdir(directory):
        print(f"Error: '{directory}' is not a valid directory", file=sys.stderr)
        sys.exit(1)

    # Create temporary directory for unmatched files
    import tempfile
    import shutil
    temp_dir = tempfile.mkdtemp(prefix='debug-clean-unmatched-')

    # Fetch bases from database
    print("Loading package bases from database...")
    with DatabaseManager() as db:
        db_bases = get_package_bases_from_db(db)
        print(f"Found {len(db_bases)} unique bases in database")

        # Find all zst files
        print(f"\nScanning directory: {directory}")
        zst_files = find_zst_files(directory)
        print(f"Found {len(zst_files)} .zst files\n")

        # Check each file
        print("Checking unmatched debug packages...")

        unmatched_files = []
        for filename in zst_files:
            base, version = extract_base_and_version_from_filename(filename)
            if base:
                if base not in db_bases:
                    unmatched_files.append(filename)
            else:
                print(f"  {filename} (Failed to parse base)")

        # Find files with multiple versions BEFORE moving
        multiversion = find_multiversion_files(zst_files)

        print(f"\nFound {len(unmatched_files)} files with base not in database")

        # Print unmatched files (only if not moving)
        if not unmatched_files:
            print("\nNo unmatched files found.")
        else:
            print("\nUnmatched files:")
            for f in unmatched_files:
                print(f"  {f}")

            # Move unmatched files and their .sig files to temp directory
            print(f"\nMoving unmatched files to: {temp_dir}")
            for filename in unmatched_files:
                src = os.path.join(directory, filename)
                dst = os.path.join(temp_dir, filename)
                if os.path.exists(src):
                    shutil.move(src, dst)
                    # Also move .sig file if exists
                    sig_src = src + '.sig'
                    sig_dst = dst + '.sig'
                    if os.path.exists(sig_src):
                        shutil.move(sig_src, sig_dst)
                        print(f"    Moved: {filename} and {filename}.sig")
                    else:
                        print(f"    Moved: {filename} (no .sig file)")

            print(f"Temporary directory for unmatched files: {temp_dir}")

        # Find files with multiple versions (already done above)
        if multiversion:
            for base, files in sorted(multiversion.items()):
                print(f"\nBase: {base}")
                for filename, version in sorted(files, key=lambda x: x[1]):
                    print(f"  {filename} (version: {version})")
            print(f"\nTotal: {len(multiversion)} base(s) with multiple versions")
        else:
            print("\nNo files with multiple versions found.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)

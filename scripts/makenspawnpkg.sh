#!/bin/bash
#
# SPDX-License-Identifier: GPL-3.0-or-later

usage() {
    echo "Usage: ${0##*/} [options] <PKGBUILD_ROOT>"
    echo "PKUBUILD_ROOT is the directory containing the PKGBUILD file."
    echo "Options:"
    echo "  -h, --help      Display this help message."
    echo "  -v, --verbose   Enable verbose output."
    echo "  --base          Base directory for image"
    echo "  --change        Writable directory for image"
    echo "  --update        Do pacman -Syyu before building"
    echo "  --install       Install package(s) in the image, can be used multiple times"
    echo "  --bind          Bind mount a directory into the image, can be used multiple times"
    echo "  --run           Run a command in the image before building, can be used multiple times"
    echo "  --output        Output directory for the image"
    echo "  --cpu           CPU limit for the image in percent, i.e. 1600 for 16 cores"
    echo "  --mem           Memory limit for the image, should include unit, i.e. 4G"
    echo "  --env           Set an environment variable in the image, can be used multiple times, i.e. --env VAR=value"
    echo "  --mkpkg-env     Set an environment variable for makepkg, can be used multiple times, i.e. --mkpkg-env VAR=value"
    echo "  --copy-log      Copy build log to output directory"
}

verbose=0   
base_dir=""
change_dir=""
update=0
install=""
bind=""
run=""
output_dir=""
pkgbuild_root=""
volatile="no"
cpu_limit=""
mem_limit=""
env=""
mkpkg_env=""
copy_log=0

# root check
if [ "$(id -u)" -ne 0 ]; then
    echo "Error: This script must be run as root."
    exit 1
fi

# loongarch qemu binfmt check
if [ ! -f /proc/sys/fs/binfmt_misc/qemu-loongarch64 ]; then
    echo "Error: qemu-loongarch binfmt_misc entry not found."
    echo "Please install qemu-user-static-binfmt package."
    exit 1
fi

run_command() {
    local command=$@
    machinectl shell $machine_name /usr/bin/bash -c "$command"
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            usage
            exit 0
            ;;
        -v|--verbose)
            verbose=1
            shift
            ;;
        --base)
            base_dir="$2"
            # convert to absolute path
            base_dir=$(realpath $base_dir)
            shift 2
            ;;
        --change)
            change_dir="$2"
            shift 2
            ;;
        --update)
            update=1
            shift
            ;;
        --install)
            install="$install $2"
            shift 2
            ;;
        --bind)
            bind="$bind $2"
            shift 2
            ;;
        --run)
            if [ -z "$run" ]; then
                run="$2"
            else
                run="$run; $2"
            fi
            shift 2
            ;;
        --output)
            output_dir="$2"
            shift 2
            ;;
        --cpu)
            cpu_limit="$2"
            shift 2
            ;;
        --mem)
            mem_limit="$2"
            shift 2
            ;;
        --env)
            env="$env $2"
            shift 2
            ;;
        --mkpkg-env)
            mkpkg_env="$mkpkg_env $2"
            shift 2
            ;;
        --copy-log)
            copy_log=1
            shift
            ;;
        *)
            pkgbuild_root="$1"
            shift
            ;;
    esac
done

if [ -z "$pkgbuild_root" ]; then
    echo "Error: PKGBUILD_ROOT is required."
    usage
    exit 1
fi

if [ ! -d "$pkgbuild_root" ]; then
    echo "Error: PKGBUILD_ROOT is not a directory."
    usage
    exit 1
fi

if [ ! -f "$pkgbuild_root/PKGBUILD" ]; then
    echo "Error: PKGBUILD not found in PKGBUILD_ROOT."
    exit 1
fi

if [ -z "$change_dir" ]; then
    echo "Warning: No change directory specified, using tmpfs"
    volatile="overlay"
fi

if [ -z "$cpu_limit" ]; then
    num_cores=$(nproc)
    cpu_limit=$((num_cores * 100))
    echo "Using CPU limit: $cpu_limit%"
fi

makepkg_jobs=$((cpu_limit / 100))

# default use 70% of total memory
if [ -z "$mem_limit" ]; then
    total_mem=$(awk '/MemTotal/ {print $2}' /proc/meminfo)
    mem_limit=$((total_mem * 70 / 100 / 1024 / 1024))
    mem_limit="${mem_limit}G"
    echo "Using memory limit: $mem_limit"
fi

if [ $verbose -eq 1 ]; then
    set -x
    echo "Verbose output enabled"
    echo "Base directory: $base_dir"
    echo "Change directory: $change_dir"
    echo "Update: $update"
    echo "Install: $install"
    echo "Bind: $bind"
    echo "Run: $run"
    echo "Output directory: $output_dir"
    echo "Volatile: $volatile"
    echo "CPU limit: $cpu_limit%"
    echo "Memory limit: $mem_limit"
fi

nspawn_build_args=(
    --boot
    --user=root
    --capability=all
    --system-call-filter=add_key,keyctl,bpf
    --private-users=0:65536
    --private-users-ownership=map
    --bind /proc:/run/proc
    --bind /sys:/run/sys
    --bind /dev/shm:/dev/shm
    --bind /dev/null:/dev/null
    --bind /dev/zero:/dev/zero
    --bind /dev/full:/dev/full
    --bind /dev/random:/dev/random
    --bind /dev/urandom:/dev/urandom
    --bind $pkgbuild_root:/build
    --console=interactive
    --template=$base_dir
    --setenv=MAKEFLAGS=-j$makepkg_jobs
)

if [ -z "$change_dir" ]; then
    nspawn_build_args+=(
        --volatile=overlay
    )
else
    change_dir="$change_dir-$RANDOM"
    echo "Using change directory: $change_dir to avoid conflicts"
    nspawn_build_args+=(
        --volatile=no
        --directory=$change_dir
    )
    rm -rf $change_dir
    change_dir=$(realpath $change_dir)
fi

# if copy log is enabled but no output directory is specified, echo error
if [ $copy_log -eq 1 ] && [ -z "$output_dir" ]; then
    echo "Error: --copy-log requires --output"
    exit 1
fi

for env_var in $env; do
    nspawn_build_args+=(--setenv=$env_var)
done

systemd-nspawn "${nspawn_build_args[@]}" &
nspawn_pid=$!
echo "nspawn PID: $nspawn_pid"

machine_name=$(basename $change_dir)

check_nspawn_up() {
    run_command "uname -m" | grep -q loongarch64
}

# Wait for nspawn to start, default timeout is 30s
timeout=30
echo "Waiting for systemd-nspawn to start..."
while [ $timeout -gt 0 ]; do
    if check_nspawn_up; then
        break
    fi
    sleep 1
    timeout=$((timeout - 1))
done

if [ $timeout -eq 0 ]; then
    echo "Error: systemd-nspawn failed to start."
    exit 1
fi

# modify resource limits
systemctl set-property systemd-nspawn@$machine_name.service CPUQuota=$cpu_limit%

# set memory limit
systemctl set-property systemd-nspawn@$machine_name.service MemoryLimit=$mem_limit

# first run update
if [ $update -eq 1 ]; then
    run_command "pacman --noconfirm -Syyu"
fi

# install packages
run_command "pacman -S --noconfirm $install"

# run commands
run_command "$run"

# create builduser, chwon build directory, and build package
run_command "useradd -m builduser"
run_command "chown -R builduser:builduser /build"

# setup builduser
tmp_file=$(mktemp)
cat > $tmp_file <<EOF
cat > "/etc/sudoers.d/builduser-pacman" <<EOF
builduser ALL = NOPASSWD: /usr/bin/pacman
"EOF"
chmod 440 "/etc/sudoers.d/builduser-pacman"
cat > "/etc/gitconfig" <<EOF
[safe]
	directory = *
"EOF"
echo "setup finished"
EOF
sed -i 's/"EOF"/EOF/g' $tmp_file

machinectl copy-to $machine_name $tmp_file /tmp/setup.sh
rm $tmp_file
run_command "bash /tmp/setup.sh"


echo "begin to build package, please wait..."
run_command "su - builduser -c 'cd /build && $mkpkg_env makepkg -s --noconfirm -C -L'"
echo "package build finished"
run_command "chown -R root:root /build"

# copy package to output directory
if [ -n "$output_dir" ]; then
    if [ ! -d "$output_dir" ]; then
        mkdir -p $output_dir
    fi
    # generate list of package files
    package_files=$(run_command "ls /build/*.pkg.tar.zst" | tr -d '\r')
    for package_file in $package_files; do
        echo "Copying package file: $package_file"
        machinectl copy-from $machine_name $package_file $output_dir/$(basename $package_file)
    done
fi

# copy build log
if [ $copy_log -eq 1 ]; then
    log_files=$(run_command "ls /build/*.log.*" | tr -d '\r')
    for log_file in $log_files; do
        echo "Copying log file: $log_file"
        machinectl copy-from $machine_name $log_file $output_dir/$(basename $log_file)
    done
fi

# shutdown machine
run_command "poweroff"
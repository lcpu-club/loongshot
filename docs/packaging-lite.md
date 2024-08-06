# 利用 Qemu 和 Systemd-nspawn 打包

## 1. 基本环境安装

需要安装 `qemu-user-binfmt` 和 `systemd-nspawn`。下面是一些常见发行版的安装命令。目前需要较高版本的`systemd`才具有这个[补丁](https://github.com/systemd/systemd/pull/28954/commits/837763c9b0d1bde8024e69c1e2ffaed6d5e31e73)，能使跨架构容器正常工作，因此我们推荐在`Arch Linux`, `Ubuntu 24.04`, `AOSC OS`或`Fedora 40`上进行打包。安装完对应包后，可以使用`cat /proc/sys/fs/binfmt_misc/qemu-loongarch64`查看是否已经注册了`qemu-loongarch64`的解释器。

### Arch Linux

```bash
sudo pacman -S qemu-user-static-binfmt # systemd-nsapwn is shipped with systemd
```

### Debian/Ubuntu

```bash
sudo apt install qemu-user-binfmt systemd-container
```

### AOSC OS

```bash
sudo oma install qemu # systemd-nspawn is shipped with systemd
```

### Fedora

```bash
sudo dnf install qemu-user-static systemd-container
```

## 2. 基础镜像获取

我们维护了打包基础文件系统的镜像仓库，每周会发布 Release 镜像，可以在[这里](https://github.com/lcpu-club/loongarchlinux-dockerfile/releases)下载。

如果你需要自己构建基础镜像，命令如下。构建完成后可以在 rootfs 文件夹中找到基础镜像。
```bash
git clone https://github.com/lcpu-club/loongarchlinux-dockerfile.git
make all
```

## 3. 打包

使用 `makenspawnpkg.sh`工具可以在干净的环境中打包软件。具体使用方法请参考[这里](makenspawnpkg.md)。

一个示例命令是：

```
sudo ./makensapwnpkg.sh --base ./base --change test --update --install cmake --run "echo hello world" --copy-log --output ./out ./core/glibc
```

这个命令会打包`glbc`，并且在容器中安装`cmake`，运行`echo hello world`，最后将打包的文件放在`./out`文件夹中。
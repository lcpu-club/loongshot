# 基础设施架构

## 管理方法

参考 archlinux 的[ansible 脚本](https://github.com/archlinux/infrastructure)，逐步构建我们自己的管理脚本。目的是为了公开透明、便于维护。服务器之间建立 WireGuard 虚拟网，便于安全可靠的数据传输。

## 服务器列表

1. web 服务，用于发布项目状态、进行项目推广。
2. tier0 镜像，用于提供最新 repo
3. 构建主机，用于二进制包的构建，可使用物理机也可以使用虚拟机

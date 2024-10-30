# 快速开始

## 前提条件

0. 必须具有一个安装 Arch Linux 发行版的主机（可以是云主机）
1. 安装龙平台的[开发者工具](https://github.com/lcpu-club/devtools-loong)
2. 安装相关脚本的依赖程序

## 基本工作流程(TLDR)

1. 克隆本代码仓库和[补丁仓库](https://github.com/lcpu-club/loongarch-packages)
1. 设置如下几个环境变量（如取值与 loong-build.sh 脚本相同则可以省略）：
  - LOONGREPO，指向补丁仓库的本地路径
  - WORKDIR，指向本地或者远程的工作路径
  - PACKAGER，设置为打包者的姓名和邮箱
  - SCRIPTSPATH，指向本仓库的脚本路径
  - LOCALREPO，本地包仓库地址
  - TIER0，TIER0 服务器的主机名或地址（不设置表示无 TIER0 的访问权限）
1. 使用 loong-build.sh <pkgbase> 进行打包
1. 使用 localup.sh 将本地仓库的包全部传递到 TIER0 服务器

## loong-build.sh 脚本介绍

loong-build.sh 对本项目的主要工作流程进行了封装，目标是简化打包流程，提高合作效率。

### 脚本执行流程
1. 建立打包的工作目录，复制或克隆 PKGBUILD 及相关文件
1. 根据上游 x86 的版本信息，切换到对应的发行标签（部分包仓库标签领先于上游发布版本）
1. 应用龙平台对应补丁
1. 检查 TIER0 服务器上的版本信息（如存在同版本包，应该增加 pkgrel 的小数值）
1. 自动对 PKGBUILD 的已知移植问题进行修改
1. 调用 extra$TESTING-loong64-build 进行打包，缺省是调用 extra-local-loong64-build，参考星外之神的博客[文章](https://wszqkzqk.github.io/2024/09/19/build-order-local-repo/)
1. 将打包好的文件加入到本地仓库
1. 将打包日志上传到 TIER0 服务器

### 脚本参数说明

- `--debug` 仅打包，不上传日志，用于调试。
- `--uplog` 仅上传日志。对于使用 --debug 完成的打包，当前目录会留有一个 `all.log` 文件，使用这个参数可以将其上传，避免重复打包。仅对上一次在同一目录下执行的打包操作有效，请谨慎使用。
- `--builder` 指定打包服务器名称，如不指定则在本机打包（对于龙平台和 x86 平台同样适用）。
- `--clean` 重新构建 chroot 环境（参考 `archbuild` 的 `-c` 参数）。
- `--delsrc` 清理工作目录，删除下载的源码和各种生成文件。
- `--test` 使用 testing 仓库，即使用 `extra-testing-loong64-build` 脚本。
- `--stag` 使用 staging 仓库，即使用 `extra-staging-loong64-build` 脚本。
- `--ver` 使用指定的发布标签，可在回退版本或者自举时使用
- `--` 附加参数，在 `--` 之后的参数将传递给 `makepkg`，例如可以传递 `--skipgpgcheck` 避免进行 PGP签名验证。

## 注意事项
1. 补丁仓库需要手动更新

# makenspawnpkg 文档

## 1. 介绍

目前 `qemu-user` 未能正确实现 `CLONE_NEWNS`的功能，因此无法在 `qemu-user` 构建的交叉编译容器中嵌套容器。由于其实只需要使用 `systemd-nspawn` 即可保证构建环境的干净，我们写了本工具，直接使用 `systemd-nspawn` 构建交叉编译环境。

为了避免许多的麻烦，该工具中很多操作都是特权操作，减少了容器的隔离性（比如直接把0:65536的用户映射到容器中）。请确保打包代码是安全的，推荐在虚拟中使用该工具。

具体使用文档请参考[packaging-lite.md](packaging-lite.md)。

## 2. 选项

### 输入： PKGBUILD_ROOT

指定 PKGBUILD 文件夹的路径，无默认值。这个文件夹会被挂载到容器中，容器中的工作目录为这个文件夹。

### --base

指定基础镜像的路径，无默认值。这个文件夹只会被读取，不会被修改。

### --change

指定可读写层的位置，默认为临时文件夹，可以指定为任意目录。

### --update

指定打包前是否更新基础镜像，默认为 `false`。

### --install

逗号分隔的安装包列表，可以指定多个。这些软件会被安装到容器中。

### --bind

指定挂载的目录，格式为 `host:container`，可以指定多个。默认会挂载: `/proc:/run/proc`, `/sys:/run/sys`，`/dev/shm:/dev/shm`, `/dev/null:/dev/null`，`/dev/zero:/dev/zero`，`/dev/full:/dev/full`，`/dev/random:/dev/random`，`/dev/urandom:/dev/urandom`。

### --run

指定打包前运行的命令，可以指定多个，按顺序执行。

### --output

默认为 `./output`，指定输出的目录，工作目录中所有的`*.pkg.tar.zst`文件都会被放在这个目录下，如果有相同内容将会被覆盖。

### --cpu

指定 `systemd-nspawn` 使用的 CPU 数量，默认为系统所有的 CPU 资源。传入的数据是你所希望的 CPU 限制 * 100%，不用加百分号。比如 `--cpu 50` 表示限制为 50% 的 CPU 资源，也就是半个 CPU 核心。

### --memory

指定 `systemd-nspawn` 使用的内存大小，默认为系统内存资源的 70%。传入的数据是你所希望的内存限制，需要带单位，比如 `--memory 1024M` 表示限制为 1024M 的内存。


### --env

指定环境变量，格式为 `key=value`，可以指定多个。

### --mkpkg-env

指定 `makepkg` 的环境变量，格式为 `key=value`，可以指定多个。

### --copy-log

是否从容器中拷贝 `makepkg` 的日志，默认为 `false`。


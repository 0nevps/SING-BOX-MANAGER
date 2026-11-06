# 安装与升级

## 安装

使用 Debian 12/13 或 Ubuntu 22.04/24.04，并确保系统使用 systemd。安装需要 root 权限，会修改系统软件包、systemd 和 `/opt/sbmanager` 等目录。

执行前，请先检查仓库中的安装脚本和 `main` 源码。确认后运行：

```bash
curl -fsSL https://raw.githubusercontent.com/0nevps/SING-BOX-MANAGER/main/install.sh | sudo bash -s -- 0nevps/SING-BOX-MANAGER
```

安装脚本只接收 `OWNER/REPOSITORY`，每次都获取该仓库 `main` 分支的当前源码，不需要版本参数或 tag，也不依赖本项目的 Release 附件。

脚本先通过 GitHub API 获取 `main` 当前 commit，再通过 HTTPS 从 `codeload.github.com/OWNER/REPO/tar.gz/COMMIT` 下载完整源码，安全检查后解压。其中包含 `main.py` 和 `sbmanager/` 下的 Python 模块，不需要手动下载。固定 commit 仅用于确保本次安装内容一致，不影响下次更新获取新代码。

安装完成后，有交互终端时会打开主菜单，不会自动设置节点；无交互终端时会提示稍后运行 `sudo sbmanager`，已在 root 终端中时可运行 `sbmanager`。重复运行安装器会重新获取源码，完成后也会打开主菜单。

安装器会准备 Python、curl、CA 证书、tar、iproute2 和 flock。sing-box 固定使用 1.14.4，兼容范围为 1.14.x；仍从 sing-box 官方 GitHub Release 下载，并按官方发布文件的摘要进行校验，管理程序的更新不依赖这些发布文件。下载失败、缺少官方摘要、压缩包异常或已有配置与新版本不兼容时，安装会停止。

## 安装后文件放在哪里

- `/opt/sbmanager/builds/`：每次安装或更新的程序目录，包含完整 Python 源码、sing-box 和 `.source-commit` 提交记录。
- `/opt/sbmanager/current`：指向当前使用的程序目录。
- `/usr/local/bin/sbmanager`：运行 `sbmanager` 时使用的命令入口。
- `/var/lib/sbmanager/`：用户、节点和出口等管理数据，以及恢复记录、备份和 ACME 证书缓存。
- `/etc/sbmanager/config.json`：程序生成的 sing-box 服务端配置。
- `sbmanager-sing-box.service`：本工具使用的 systemd 服务。

不要覆盖其他软件的 sing-box 配置或服务。管理数据和备份中含有明文密码、连接密钥（UUID 或密码）等敏感信息；敏感目录使用 `0700` 权限，文件使用 `0600` 权限，不要随意放宽权限或公开上传。

## 第一次设置

节点是手机或电脑连接的入口。每次运行 `sudo sbmanager` 都先显示主菜单，没有节点数据时也不会自动进入安装。需要设置时，选择“1 节点管理 → 4 首次设置向导”，输入要安装的节点编号：`1 REALITY`、`2 Hysteria2`、`3 WebSocket`。可用空格或逗号分隔多选，例如 `1 3`；`0` 取消，留空不会默认安装全部。向导只创建选中的节点和第一个用户，并仅为该用户开通所选节点。已有用户或节点时，向导不会覆盖数据，应使用管理菜单修改。

按所选协议准备，未选协议无需填写：

- VPS 的公网 IP 或域名。
- REALITY 握手目标域名，以及 SNI（握手时使用、需要与目标证书匹配的域名）。SNI 直接回车会使用握手目标域名。
- Hysteria2 和 WebSocket 的证书域名。
- 各节点要在 VPS 上使用的端口。

第一个用户名直接回车默认为 `default`，也可以自己填写。WebSocket 路径直接回车会随机生成，保存后会显示生成的路径。

每种协议只需要填写一次“在 VPS 上使用的端口”：

- REALITY 默认使用 TCP 443，手机或电脑连接同一个端口。
- Hysteria2 默认使用 UDP 443，手机或电脑连接同一个端口。
- WebSocket 先选择直接连接 VPS，还是经过 Cloudflare 代理，再填写 VPS 端口，默认 TCP 8443。直接连接 VPS 时，客户端使用同一个端口；经过 Cloudflare 时，客户端连接 HTTPS 443，你需要自行在 Cloudflare 设置回源到 VPS 所填端口的规则。

使用 HTTP-01 申请证书时，域名解析必须正确，公网 TCP 80 必须能到达 VPS 源站。DNS 解析成功或本机端口检查通过，都不能证明公网访问正常。程序不会自动设置 Cloudflare，也不支持 DNS-01。

保存后，选择“4 服务管理 → 2 检查配置并启动服务”。**安装完成、设置已保存或服务检查通过，都不代表客户端一定能连接。** 仍需通过“4 服务管理 → 4 检查证书”和“4 服务管理 → 3 查看日志”排查，并在手机或电脑上实际测试。

后续按分类进入菜单，选择用户、节点或出口时，按名称找到对象并输入列表编号，不需要复制 ID。各子菜单输入 `0` 返回，选择对象时输入 `0` 取消；切换出口时，直连也是明确的编号选项，不通过留空回车选择。默认显示友好列表，原始设置 JSON 在“6 高级与帮助 → 1 查看原始设置JSON”中查看。菜单和操作步骤见[使用指南](USER_GUIDE.md)。

## 升级

更新管理程序时，选择“4 服务管理 → 6 更新管理程序”，或重新运行上面的安装命令，自动获取 `main` 最新源码。菜单更新会从安装来源仓库的 `main` 下载最新 `install.sh`，复用安装器的确认、校验、备份和回滚流程；完成后重新加载管理菜单，不会继续使用内存中的旧程序。

安装器会要求你在交互终端确认，然后写入新的程序目录并切换 `current` 链接；即使提交未变化也不会跳过安装。用户、节点和配置不清空，旧程序目录及更新前的数据备份会保留。安装来源记录在每个程序目录的 `.source-repository` 中；旧安装没有该记录时，菜单更新默认使用 `0nevps/SING-BOX-MANAGER`，其他来源请先运行对应仓库的安装命令。

升级失败时，安装器会尝试恢复旧程序和原有服务设置。请检查服务状态和提示中的备份位置，不要把“尝试恢复”当作恢复成功的保证。

只升级 sing-box 时，使用“4 服务管理 → 5 升级sing-box”，填写明确的 1.14.x 版本；升级后的运行情况仍需检查。

## 卸载

选择“4 服务管理 → 7 卸载全部”。确认提示会列出以下删除范围：

- `/etc/systemd/system/sbmanager-sing-box.service` 及同名 `.d` 配置目录。
- `/etc/sbmanager/`：全部服务配置。
- `/var/lib/sbmanager/`：全部用户、节点、出口、密钥、证书缓存、恢复记录和备份。
- `/opt/sbmanager/`：当前及历史程序目录，包括随附的 sing-box。
- `/usr/local/bin/sbmanager`：命令入口。

**输入 `yes` 后会停止并禁用本工具的服务，再永久删除上述文件，无法撤销。** 请先将需要保留的备份复制到这些目录之外。其他输入取消卸载。服务停止失败时不删除安装文件；后续步骤失败会显示错误，应排查后重试，不要视为卸载成功。

不会删除其他软件的 sing-box、手动导出到任意目录的客户端文件、系统依赖或共享 systemd 日志。`/run/sbmanager-install.lock` 是空的并发协调文件，保留到系统重启，避免删除锁文件导致并发保护失效。卸载成功后自动退出；无需手动删除 `sbmanager` 指令。

## 从源码运行与开发测试

`sbmanager` 和从源码运行的 `python3 main.py` 都要求 Linux + root，统一使用 `/var/lib/sbmanager/` 和 `/etc/sbmanager/config.json`，会操作真实系统服务。从源码启动不能代替安装器准备依赖和 systemd 服务。可通过 `--sing-box /path/to/sing-box` 指定可执行的 1.14.x 程序文件；这不会隔离管理数据或系统服务。

开发测试需要 Python 3.10+，可在 macOS/Linux 上运行，不需要 root 或第三方 Python 包。测试中的系统操作使用模拟，不应通过启动管理程序进行隔离测试：

```bash
python3 -m unittest discover -s tests -v
bash -n install.sh
```

这些测试不能代替 Linux 上的安装、服务和客户端连接测试。

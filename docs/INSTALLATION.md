# 安装与升级

**当前是开发预发布版，只用于独立测试机。** 真实 Linux 安装、systemd 服务、证书申请和客户端连接尚未完成验收，不要用于正式服务。

## 在测试机上安装

使用 Debian 12/13 或 Ubuntu 22.04/24.04，并确保系统使用 systemd。安装需要 root 权限，会修改系统软件包、systemd 和 `/opt/sbmanager` 等目录。

执行前，请先检查仓库中的安装脚本和发布文件。确认后，在测试机运行：

```bash
curl -fsSL https://raw.githubusercontent.com/0nevps/SING-BOX-MANAGER/v0.1.0/install.sh | sudo bash -s -- 0nevps/SING-BOX-MANAGER v0.1.0
```

安装器会下载 GitHub Release 中的压缩包和 SHA-256 校验文件，检查下载文件是否一致。`v0.1.0` 是预发布版，必须明确写出版本号。安装完成后运行 `sudo sbmanager`；已在 root 终端中时可运行 `sbmanager`。

安装脚本的参数是 `OWNER/REPOSITORY` 和可选的 `v版本`。不指定版本时，会通过 GitHub API 选择最新稳定 Release，不会自动选择预发布版。安装脚本本身应来自已经审核的标签或提交。

安装器会准备 Python、curl、CA 证书、tar、iproute2 和 flock。sing-box 固定使用 1.14.4，并按官方 GitHub 发布文件的摘要进行校验；固定版本不代表已完成 Linux 实测。下载失败、缺少摘要、压缩包异常或已有配置与新版本不兼容时，安装会停止。

## 安装后文件放在哪里

- `/opt/sbmanager/releases/`：按版本保存管理程序和 sing-box。
- `/opt/sbmanager/current`：指向当前使用的程序版本。
- `/usr/local/bin/sbmanager`：运行 `sbmanager` 时使用的命令入口。
- `/var/lib/sbmanager/`：用户、节点和出口等管理数据，以及恢复记录、备份和 ACME 证书缓存。
- `/etc/sbmanager/config.json`：程序生成的 sing-box 服务端配置。
- `sbmanager-sing-box.service`：本工具使用的 systemd 服务。

不要覆盖其他软件的 sing-box 配置或服务。管理数据和备份中含有明文密码、连接密钥（UUID 或密码）等敏感信息；敏感目录使用 `0700` 权限，文件使用 `0600` 权限，不要随意放宽权限或公开上传。

## 第一次设置

节点是手机或电脑连接的入口。没有节点数据时，运行 `sudo sbmanager` 会进入首次设置向导，创建三种节点和第一个用户。已有用户或节点时，向导不会覆盖数据，应使用管理菜单修改。

请先准备：

- VPS 的公网 IP 或域名。
- REALITY 握手目标域名，以及 SNI（握手时使用、需要与目标证书匹配的域名）。SNI 直接回车会使用握手目标域名。
- Hysteria2 和 WebSocket 的证书域名。
- 各节点要在 VPS 上使用的端口。

第一个用户名直接回车默认为 `default`，也可以自己填写。WebSocket 路径直接回车会随机生成，保存后会显示生成的路径。

每种协议只需要填写一次“在 VPS 上使用的端口”：

- REALITY 默认使用 TCP 443，手机或电脑连接同一个端口。
- Hysteria2 默认使用 UDP 443，手机或电脑连接同一个端口。
- WebSocket 先选择直接连接 VPS，还是经过 Cloudflare 代理，再填写 VPS 端口，默认 TCP 8443。直接连接 VPS 时，客户端使用同一个端口；经过 Cloudflare 时，客户端连接 HTTPS 443，你需要自行在 Cloudflare 设置回源到 VPS 所填端口的规则。

使用 HTTP-01 申请证书时，域名解析必须正确，公网 TCP 80 必须能到达 VPS 源站。DNS 解析成功或本机端口检查通过，都不能证明公网访问正常。程序不会自动设置 Cloudflare，V1 也不支持 DNS-01。

保存后，选择“检查配置并启动服务”（菜单 14）。**安装完成、设置已保存或服务检查通过，都不代表客户端一定能连接。** 仍需检查证书、服务日志，并在手机或电脑上实际测试。

后续操作需要的用户、节点和出口 ID，都从“查看当前设置”中找到对应名称，再复制 `id`。字段说明和操作步骤见[使用指南](USER_GUIDE.md)。

## 升级

升级管理程序时，重新运行安装脚本并指定新版本。安装器会要求你在交互终端确认，并保留旧版本及数据备份。重复安装同一版本会保留已有部署，但脚本仍会先执行依赖准备和下载检查。

升级失败时，安装器会尝试恢复旧程序和原有服务设置。请检查服务状态和提示中的备份位置，不要把“尝试恢复”当作恢复成功的保证。

只升级 sing-box 时，使用“升级 sing-box”（菜单 27），填写明确的 1.14.x 稳定版本。系统模式下才能执行此操作；升级后的运行情况仍需检查。

## 本地开发或预览

需要 Python 3.10+，支持 macOS/Linux，不需要第三方 Python 包：

```bash
python3 main.py
python3 -m unittest discover -s tests -v
bash -n install.sh
```

本地模式只保存管理数据，不启动 systemd，也不应用系统服务配置。可通过 `--sing-box /path/to/sing-box` 指定 1.14.x 程序文件，使用首次设置、节点配置和导出等相关功能；需要调用 sing-box 的功能仍要求该文件可执行。本地运行不能代替 Linux 部署验收。

## 为 GitHub 发布打包（维护者使用）

```bash
python3 scripts/package.py v0.1.0
```

生成的文件是 `dist/sbmanager-v0.1.0.tar.gz` 和 `dist/SHA256SUMS`。GitHub 标签工作流会运行测试并创建预发布版 Release。完成[验证记录](VALIDATION.md)中的 Linux 验收后，才能将其作为稳定版宣传。

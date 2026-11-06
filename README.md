# Sing-Box Manager

面向 Linux VPS 的 sing-box 服务端管理工具，通过交互式 CLI 管理入站、用户、出口、证书和配置。

> **当前状态：开发预发布版，待 Linux 部署验收。** 已实现中文 CLI、初始化、用户授权、出口绑定、三种入站配置、部署事务与恢复、节点导出、证书诊断、备份及内核升级。真实 systemd、ACME 和客户端连通性尚未验证；请仅在独立的测试机上使用预发布版。

## 安装与使用

预发布版采用带 SHA-256 校验文件的 GitHub Release 分发。在独立的 Debian/Ubuntu 测试机上安装 v0.1.0：

```bash
curl -fsSL https://raw.githubusercontent.com/0nevps/SING-BOX-MANAGER/v0.1.0/install.sh | sudo bash -s -- 0nevps/SING-BOX-MANAGER v0.1.0
```

安装脚本会更改系统软件包、systemd 和 `/opt/sbmanager` 等目录。安装后运行 `sudo sbmanager`。请先查看[安装与升级](docs/INSTALLATION.md)及[待完成验收](docs/VALIDATION.md)；不指定版本时，安装器只选择 GitHub 最新的稳定版。

预期使用流程：

1. 在受支持的 Linux VPS 上以 root 权限执行一行安装命令。
2. 安装器检查环境，自动准备兼容的 Python 3 和系统依赖，下载并校验发布版本。
3. 安装完成后执行 `sbmanager`，首次启动进入初始化向导。
4. 完成域名、端口和节点配置后，通过菜单管理服务；后续执行 `sbmanager` 直接进入管理菜单。

用户无需手动安装 pip 包、创建虚拟环境或编写 sing-box JSON。证书申请和节点就绪取决于域名、网络及服务检查，安装成功不代表这些检查已通过。

## V1 功能范围

- VLESS + REALITY + Vision、Hysteria2、VLESS + WebSocket + TLS 三种入站。
- 统一用户身份，各入站独立授权及凭据管理。
- 通用出口驱动框架，首版实现 SOCKS5。
- 每个用户、每个入站独立保存出口绑定，并选择一个生效出口或 DIRECT。
- 不支持 UDP 的代理出口默认阻断 UDP，禁止静默直连回退。
- sing-box 原生 ACME 证书申请、续期与状态检查。
- 分享链接、客户端 JSON 导出，以及 systemd 服务和日志管理。
- 配置校验、操作锁、备份，以及业务状态和配置同步回滚。

V1 不包含 Web 面板、多 VPS 管理、流量计费、自动出口切换或 Cloudflare API 自动配置。

## 系统与网络要求

- 目标系统：Debian 12/13、Ubuntu 22.04/24.04+，使用 systemd。
- 安装和服务管理需要 root 权限，以及获取系统依赖和 GitHub 发布产物的网络连接。
- Python 3 由安装器检查和准备，核心优先使用标准库。
- PRD 暂定 sing-box 1.14.x，须支持 ACME Certificate Provider；实际发布前验证版本可用性、字段兼容性和运行行为。
- 使用 HTTP-01 申请证书时，域名解析正确，公网 TCP 80 可达且验证请求可到达源站。V1 不支持 DNS-01。
- Cloudflare DNS、代理开关及 Origin Rules 由用户自行配置。

## 架构与发布方式

**Bash 安装器 + Python 业务核心。** Shell 负责部署与运行环境准备；Python 负责交互菜单、用户、出口、配置生成和事务处理。

稳定安装使用 GitHub Releases 中明确版本的压缩包，并校验 SHA-256。默认安装稳定版本，同时支持指定发布版本。程序与状态、配置、备份分开存放；重复安装保护已有数据，升级失败恢复可用版本及匹配数据。

## 项目结构与开发

当前文档：

- [贡献指南](AGENTS.md)：代码组织、命名、测试和提交要求。
- [验证记录与待完成验收](docs/VALIDATION.md)：V1 验收条件及当前限制。

主要代码结构：

```text
install.sh       一键安装器
main.py          Python 入口
sbmanager/       CLI、业务核心、协议驱动和系统集成
config/          默认配置
tests/           自动化测试
docs/            架构、安装、使用和故障排查文档
```

当前可在 macOS/Linux 上运行本地模式，无需 root 或第三方 Python 包：

```bash
python3 main.py
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

默认状态目录为 `~/.local/state/sbmanager-dev`，可用 `--state-dir /path/to/directory` 指定独立目录。目录包含敏感凭据，请勿放入仓库。菜单中先创建入站档案和用户，再使用列表显示的 ID 添加授权及绑定。状态保存不会部署或更新 sing-box 服务。

测试覆盖授权隔离、绑定删除保护、凭据重置、禁用与删除、权限与显示脱敏、写入失败、多个进程并发更新和 CLI 操作。使用 `bash -n install.sh` 和 ShellCheck 检查安装器；安装、systemd、证书和协议连通性仍需在受支持的 Linux 环境验收。

## 安全约定

状态和密钥文件使用 `0600`，敏感目录使用 `0700`。日志、问题反馈和提交内容不得包含密码、私钥或完整分享链接。配置修改必须先校验、备份再应用，失败时同步恢复业务状态和配置。

## 安装、操作与验收文档

- [安装与升级](docs/INSTALLATION.md)
- [操作指南](docs/USER_GUIDE.md)
- [验证记录与待完成验收](docs/VALIDATION.md)

系统模式仅用于安装后的 Linux root 环境，部署成功后的修改会自动更新服务。本地模式始终只保存业务状态，不应用系统服务。

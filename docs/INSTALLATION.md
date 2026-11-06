# 安装与升级

当前发布的是待 Linux 验收的预发布版，仅用于独立测试机，尚未完成 systemd、证书和客户端连通性实测。

## 测试机安装

在 Debian 12/13 或 Ubuntu 22.04/24.04 的测试机执行（会修改系统软件包、systemd 和 `/opt/sbmanager` 等目录）：

```bash
curl -fsSL https://raw.githubusercontent.com/0nevps/SING-BOX-MANAGER/v0.1.0/install.sh | sudo bash -s -- 0nevps/SING-BOX-MANAGER v0.1.0
```

先检查仓库中的安装脚本及发布产物。安装器使用 GitHub Release 中的压缩包及 SHA-256 校验文件；`v0.1.0` 是预发布版，必须显式指定版本。首次启动使用 `sudo sbmanager`。

## 本地开发

Python 3.10+，macOS/Linux，无第三方 Python 包：

```bash
python3 main.py
python3 -m unittest discover -s tests -v
bash -n install.sh
```

本地模式不启动 systemd。可通过 `--sing-box /path/to/sing-box` 指定 1.14.x 引擎，使用初始化、配置、导出和诊断相关功能。

## GitHub 发布准备

```bash
python3 scripts/package.py v0.1.0
```

输出 `dist/sbmanager-v0.1.0.tar.gz` 和 `dist/SHA256SUMS`。GitHub 标签工作流运行测试并创建预发布版 Release；完成 [验证记录](VALIDATION.md) 中的 Linux 验收后才能将其作为稳定版宣传。

安装脚本参数为 `OWNER/REPOSITORY` 和可选的 `v版本`。默认通过 GitHub API 选择稳定 Release；预发布版需显式指定版本。脚本本身应来自已审核的标签或提交。

安装器准备 Python、curl、CA、tar、iproute2 和 flock。内核固定为验证过的 1.14.4，并校验官方 GitHub 资产摘要。下载失败、缺少摘要、压缩包异常或配置不兼容时停止。

## 安装布局

- `/opt/sbmanager/releases/`：按版本保存程序和内核。
- `/opt/sbmanager/current`：当前程序版本链接。
- `/usr/local/bin/sbmanager`：命令入口。
- `/var/lib/sbmanager/`：业务状态、恢复日志、备份和 ACME 缓存。
- `/etc/sbmanager/config.json`：生成的服务配置。
- `sbmanager-sing-box.service`：专用 systemd 单元。

不得覆盖其他软件的 sing-box 配置或服务。业务数据和备份包含明文认证资料，由目录 0700、文件 0600 保护。

## 首次使用

运行 `sbmanager` 后进入初始化向导，准备公网地址、REALITY Server Name/握手目标、HY2/WS 域名及端口。完成资料保存后，选择“校验并部署”。安装和初始化资料保存成功均不代表节点已可连接。

## 升级

重新运行安装脚本并指定新版本，安装器从终端确认升级，保留旧版本及数据备份。同版本安装保持已有部署。内核可在菜单中升级至明确的 1.14.x 稳定版本。

# 验证记录与发布条件

## 已完成的验证

- 本机 macOS、Python 3.14.7：21 项 unittest 通过。
- 官方 sing-box 1.14.4 macOS ARM64：三种入站合并配置及三种客户端出站通过 `sing-box check`。
- `bash -n install.sh` 和 ShellCheck 通过。
- 版本包生成和 SHA-256 文件生成通过；压缩包不包含状态、缓存或凭据。
- 测试覆盖跨进程写入、权限、授权隔离、凭据重置、出口引用保护、TCP-only UDP 拒绝规则、配置校验失败、服务重启失败回滚、首次部署失败、恢复日志及用户导出隔离。

测试中的 systemd 使用替身，因此这些结果不能证明真实服务启动、端口归属、证书签发或客户端转发成功。

## 必须完成的 Linux 发布验收

当前开发环境没有 Docker、Podman、Lima 或可用 Linux VPS；以下项目尚未执行，不得据此发布“完整可用”声明：

- Debian 12/13、Ubuntu 22.04/24.04 上的全新安装、重复安装、升级失败恢复。
- x86_64、ARM64 发布包安装与 systemd 启动。
- 公网域名 HTTP-01 签发、证书加载、续期观察；TCP 80 冲突和公网不可达时的失败反馈。
- REALITY、HY2、WS 三种客户端实际连接、多用户 auth_user 路由隔离及出口 IP 验证。
- TCP-only 出口 UDP 阻断及支持 UDP 出口的 UDP ASSOCIATE 转发。
- Linux 重启或进程强杀后的事务恢复，以及磁盘写满等故障注入。
- GitHub Actions、真实 Release 下载地址和一行安装命令。

## 已知限制

- 服务健康检查核对 systemd 状态和监听端口，不等同于端到端连通性，也未确认每个端口的进程归属。
- 出口测试检查 SOCKS5 协议与认证；UDP 能力来自用户声明，不宣称已验证 UDP。
- 主菜单已覆盖核心操作，尚未拆分为 PRD 中各协议独立子菜单。
- 内核升级有失败回滚，但尚未覆盖升级过程中突然断电的恢复。
- 安装器当前只接受明确列出的四个发行版版本，未来 Ubuntu 版本需实际验证后放行。

## 官方依据

- https://github.com/SagerNet/sing-box/releases/tag/v1.14.4
- https://sing-box.sagernet.org/configuration/shared/certificate-provider/
- https://sing-box.sagernet.org/configuration/shared/certificate-provider/acme/
- https://sing-box.sagernet.org/configuration/shared/tls/

证书采用共享 `certificate_providers` 与 TLS `certificate_provider` 引用，禁用 TLS-ALPN，仅使用 HTTP-01。程序只生成配置和展示诊断，不实现 ACME 客户端。

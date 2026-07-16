# nas-gatekeeper

`nas-gatekeeper` 是一个专为家用 NAS/服务器环境设计的轻量级守护程序，使用 Rust 语言编写。它集成了动态域名解析（DDNS）和 Podman 本地服务可用性检查，适合在 Linux 物理机或容器（如 Proxmox VE LXC）中运行，帮助构建安全、高效的家庭“双轨制”网络接入方案。

## 核心特性

- **双服务商支持**：内置对 Cloudflare 和 GoDaddy API 的支持。
- **高效 IP 嗅探**：每个检查周期仅请求一次公共 IP（使用 `api64.ipify.org`），避免多域名/多服务商配置下的高频网络请求和触发速率限制。
- **安全检查机制**：自动检测配置文件的权限。若配置文件对其他用户可读（如未设置 `chmod 600`），将输出警告日志，防范 API Token / Secrets 泄露风险。
- **Podman 连通性测试**：在启动时手动握手 Podman 本地 Unix Socket（通常为 `/run/podman/podman.sock`），验证容器服务状态。
- **系统自启就绪**：提供开箱即用的 Systemd Service 配置文件，方便以守护进程（Daemon）运行。

---

## 配置文件说明

默认配置文件路径为 `/etc/nas-gatekeeper/config.toml`。请务必将该文件的权限设置为 `600`：

```bash
chmod 600 /etc/nas-gatekeeper/config.toml
```

配置文件示例：

```toml
[cloudflare]
api_token = "YOUR_CLOUDFLARE_API_TOKEN"
domain = "example.com"
record_name = "direct.example.com"

# 如不使用 GoDaddy，可注释或删除以下小节
[godaddy]
api_key = "YOUR_GODADDY_API_KEY"
api_secret = "YOUR_GODADDY_API_SECRET"
domain = "example.com"

[ddns]
check_interval_secs = 60
```

---

## 部署与安装

### 1. 编译安装

```bash
cargo build --release
cp target/release/nas-gatekeeper /usr/local/bin/
```

### 2. 配置守护进程 (Systemd)

将项目根目录下的 `nas-gatekeeper.service` 拷贝到 `/etc/systemd/system/`：

```bash
cp nas-gatekeeper.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now nas-gatekeeper
```

---

## 架构实践报告

关于如何结合 Cloudflare Tunnel 搭建家用“双轨制”（公网直连轨 + 隧道转发轨）网络接入方案，请参考详细的实践报告：
👉 [基于 Cloudflare 的家用“双轨制”网络架构设计与部署实践报告](home_network_solution_report.md)

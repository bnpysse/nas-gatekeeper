---
description: "User Multi-Node Infrastructure & Environment Profile (Mac, N100, Aliyun)"
---

# 用户全景基础设施与环境档案 (Infrastructure & Environment Profile)

> **核心原则**：本文件记录用户核心设备与运行时环境规范。后续所有 Agent 会话必须严格基于本配置认知执行，**严禁要求用户反复说明环境上下文**。

---

## 💻 一、 本机 MacOS 主开发节点 (Local Dev Node)

- **操作系统**：macOS (Apple Silicon, Darwin)
- **默认用户 Shell**：**`Fish Shell`**
  - **配置文件路径**：`~/.config/fish/config.fish` 与 `~/.config/fish/conf.d/`
  - **环境变量存储**：`fish_variables` 与 `conf.d/` 脚本
  - **Agent 行动规范**：
    - 在为用户提供命令或生成 Shell 脚本时，默认优先适配 Fish 语法（如使用 `set -gx VAR val` 或 `fish_add_path` 代替 bash 的 `export`）；
    - 若执行复杂脚本需在 Bash/Zsh 中运行，需显式声明解释器（如 `bash -c "..."`）。
  - **网络代理切换函数**：`proxy_on`（开启 `127.0.0.1:7890`） / `proxy_off`（关闭代理）。
- **极客终端工具链**：
  - **文件管理**：`Yazi`（Catppuccin Mocha 主题，Glow markdown 实时预览，`f` 全文搜索跳转 Neovim 行号，`z` 历史直跳，`gl` lazygit，`O` 多应用分发）。
  - **核心编辑器**：`NvChad (Neovim)`（别名 `nvchad`）。
    - **双通道 Vibe Coding**：
      - 通道 A（Avante）：走 API Key (`gemini-3.6-flash` 免费配额主力，DeepSeek/Qwen 备用，`img-clip` 截图多模态）。
      - 通道 B（AGY 直连）：`~/.config/nvim/lua/configs/agy.lua` + `<Space>ag`，零消耗 API Key 流式直写当前 Buffer。
- **网络分流架构**：
  - `FlClash` (`/Users/woodman/Library/Application Support/com.follow.clash`)：外挂 JS 脚本热插拔，默认流量走美国节点，Telegram、GitHub 与 YouTube 走香港 IEPL 专线（~51ms），订阅更新免疫。
- **开发运行时与包管理**：
  - `Bun` (`/Users/woodman/.bun/bin`)
  - `Miniforge3` (Conda, `/Users/woodman/miniforge3/bin`)
  - `OrbStack` (轻量化 Docker / Podman 替代品)
- **AI Agent CLI 矩阵**：
  - **Antigravity CLI (`agy`)**：官方核心智能体，官方订阅原生通道。
  - **Pi Agent (`pi`)**：`/Users/woodman/.bun/bin/pi`，配置位于 `~/.pi/agent/`，默认接入 Google Gemini (`gemini-3.6-flash`)，内置 DeepSeek 与 DashScope 扩展端点。
  - **Claude Code (`claude`)**：`/Users/woodman/.bun/bin/claude`。

---

## 🏠 二、 N100 第二大脑与自动化算力节点 (N100 Compute Node)

- **操作系统**：Debian LXC 容器
- **网络连接参数**：
  - **局域网内网 IP**：`192.168.2.9`
  - **外网直连 SSH**：`www.donglida.xyz:30022` 或 `22030`（走阿里云 DNS 的纯 DDNS 直连轨，不走代理）
  - **管理账户**：`root`
- **定位与边界**：
  - 专职计算流水线（抓取、AI 处理、构建推送），**不承担海量媒体长期存储**，**不对外提供高并发 Web 服务**。
- **核心托管服务**：
  1. **Telegram 语音 STT 机器人**：
     - Systemd 服务：`obsidian_bot.service`
     - 容灾链条：阿里百炼 `paraformer-v2` ➔ `paraformer-v1` ➔ `sensevoice-v1` 三级级联故障转移。
  2. **容器服务**：
     - 引擎：Podman（容器 `secondbrain-flow` 挂载 `/opt/SecondBrain-Flow/src`，重启指令 `podman restart secondbrain-flow`）。
  3. **知识库构建流水线**：
     - 同步脚本：`/opt/sync_github.sh`（集成 MkDocs、Quartz 5、Nextra）。
     - 部署闭环：推送到 GitHub `main` 分支触发 Cloudflare Pages 自动构建发布到 `brain.imdld.com`。
  4. **双端数据隔离与防爆盘策略**：
     - MacOS 个人核心笔记由 `remotely-save` 同步到 OneDrive；
     - N100 通过 `rclone sync` 单向拉取 OneDrive 笔记用于静态站点编译；
     - TG Bot 与网络抓取产生的大量 Markdown/媒体直接归档到 Google Drive，严格设置 Exclude，**绝对不反向同步到 OneDrive**，杜绝撑爆 Mac 本地空间。
  5. **本地大模型服务**：
     - Ollama (`http://192.168.2.9:11434`)。

---

## ☁️ 三、 阿里云云端轻量小主机 (Aliyun VPS & Relay Node)

- **主机标识**：Ubuntu-nyqc (阿里云 ECS)
- **网络连接参数**：
  - **公网 IP**：`47.101.190.145`
  - **绑定域名**：`erth.donglida.xyz`（已配置 Caddyfile 自动 Let's Encrypt HTTPS 证书）
  - **管理账户**：`root`（Mac 宿主机已打通免密 SSH 互信）
- **核心定位与服务**：
  1. **Web 反向代理与静态分发**：
     - 基础服务器：`Caddy` Web Server。
  2. **微型临时语音驿站 (Audio Relay Station)**：
     - 本地静态目录：`/var/www/bot_audio`
     - 暴露 HTTPS 路由：`https://erth.donglida.xyz/bot_audio/*`
     - 协作流程：N100 机器人抓取到 Telegram 音频后，使用免密 `scp` 极速推送到该目录，生成公网 HTTPS URL 提交给阿里百炼 Paraformer 进行语音识别；识别完毕后立即通过 SSH 执行删除命令，不留存储痕迹。

---

## 🌐 四、 域名双轨隔离路由规范 (Domain Routing Strategy)

严格执行“一域一轨”防路由混乱原则：

| 轨道名称 | 专属域名 | DNS 解析商 | 传输机制 | 典型应用场景 |
| :--- | :--- | :--- | :--- | :--- |
| **直连轨 (Direct)** | `donglida.xyz` | 阿里云 DNS (国内) | 纯公网 DDNS 直连 | N100 SSH 运维 (`:30022`/`:22030`)、大流量数据传输、大文件同步 |
| **隧道轨 (Tunnel)** | `imdld.com` (及所有子域名) | Cloudflare DNS (托管) | Cloudflare Tunnel 加密穿透 | `brain.imdld.com`、面板后台、标准 80/443 Web 访问、边缘 SSL 保护 |

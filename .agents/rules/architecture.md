---
description: "Gatekeeper Project Architecture & Second Brain Workflow"
---

# Gatekeeper 终极解耦架构 (Decoupled Architecture)

这是 Woodman 的 Second Brain 系统的终极架构蓝图。未来的任何开发、重构和部署，都必须遵循以下“算力、存储、展示解耦”的原则。

## 1. 角色分配与数据流
*   **计算中心 (Compute - N100)**：
    *   **职责**：负责抓取 RSS、清理格式、使用本地大模型 (Qwen) 翻译、使用云端大模型 (Gemini) 提炼简报。
    *   **限制**：N100 仅作为流水线，**不承担大规模数据的长久存储**，也不承担最终网站的对外并发服务。
*   **存储中心 (Storage - Github + Google Drive)**：
    *   **纯文本 (Markdown)**：由 N100 推送到私有 Github 仓库。Github 作为文本的版本控制和静态网页构建的触发器。
    *   **大媒体文件 (Video/Audio/PDF)**：由 N100 推送到 Google Drive (5TB)。Markdown 文件中仅保留指向 Google Drive 的超链接，完美避开 Github 的容量限制。
*   **发布中心 (Hosting - Cloudflare Pages)**：
    *   绑定 Github 仓库。当检测到新的 `.md` 文件推送时，利用其云端算力瞬间执行 `npx quartz build`，并分发到全球 CDN。
*   **高级智能体 (Agent - Gemini Spark)**：
    *   作为长期伴随的“云端专家”。通过原生挂载 Google Drive，对沉淀的高质量《全翻译》长文进行深度关联分析。

## 2. 系统组件规范
*   **抓取脚本**：`rss_fetcher.py`，负责定时任务 (Cron: `0 */2 * * *`)。
*   **处理引擎**：`processor.py`，必须采用“本地 Qwen2.5 翻译 + 云端 Gemini 精炼”的混合架构，防止 API 速率超限。
*   **MCP 集成 (未来扩展)**：在 N100 部署 MCP Server，使 Gemini Spark 能够直接调用 N100 的数据库状态或执行本地指令。

## 3. 双轨制域名分配与网络连通规范 (Domain Routing Strategy)
针对国内家庭宽带 80/443 端口被封锁的客观环境，网络架构必须严格执行以下**“一域一轨”**的隔离分配原则，以防出现路由错乱：

*   **轨道一：公网直连轨 (直连大流量 / SSH)**
    *   **指定域名**：`donglida.xyz`
    *   **解析商**：阿里云 DNS (国内)
    *   **用途**：纯 DDNS 动态解析到家里的公网 IP，不走任何代理。主要用于对带宽和延迟要求极高的非 Web 协议直连，例如大文件传输、SSH 运维 (走 `22030`、`8443` 等自定义端口)。
*   **轨道二：加密隧道轨 (80/443 Web 访问)**
    *   **指定域名**：`imdld.com` (及所有子域名如 `brain.imdld.com`, `manager.imdld.com`)
    *   **解析商**：Cloudflare DNS (接管)
    *   **用途**：利用 Cloudflare Tunnel 穿透内网，无需公网开放端口。专属用于所有必须使用标准 80/443 端口提供外部优雅访问的 Web 服务（如个人博客、面板后台、网关导航页等）。自带 CDN 边缘 SSL 小绿锁。

*注意：将来如在多套住宅部署，`donglida.xyz` 专属于 N100 环境的直连域名，而 `imdld.com` 的隧道可通过子域名在多处公用。*

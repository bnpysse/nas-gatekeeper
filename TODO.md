# 📋 NAS Gatekeeper & SecondBrain 待办与系统优化清单 (TODO & Backlog)

> 本文件用于持久化记录未来的系统优化点、算力/额度薅羊毛方案、架构重构计划。  
> **使用规范**：每当有新优化思路时归档入库；当用户询问“我们还有什么优化没做”时，以此文件为准逐一核对推进并划掉完成项。

---

## 🎙️ 一、 语音识别与 AI 多模型算力储备 (ASR & LLM Quota)

- [x] **阿里百炼 `qwen3-vl-embedding` (100万免费Tokens) + Turso 向量数据库接通** `(2026-08-19 完成)`
  - 成功替换已收费模型，生成 2560 维高精向量直接存入 Turso `obsidian_vectors` 表并完成余弦检索验证；
  - 升级 N100 `SecondBrain-Flow/services/rag.py`，实现笔记检索 100% 免费。
- [x] **火山方舟 `DeepSeek-V4-Pro正式版` (`deepseek-v4-pro-ga-260813`) 接入** `(2026-08-19 完成)`
  - 利用火山“今日采集量=次日资源包发放量”机制，成功接入每日循环补给 200 万 Tokens 的 DeepSeek-V4-Pro 正式版；
  - 已注入 N100 `SecondBrain-Flow` 与 Omni 天眼股票系统的 `ai_advisor.py` 作为主力穿透审计大脑。
- [ ] **火山引擎语音大模型（20小时/App 免费额度）多应用级联接入**
  - **背景**：火山方舟/火山语音每个新创建的应用（App）自带 20 小时免费语音识别（ASR）额度，单账号最高可创建 10 个应用（理论可薅 200 小时顶级 ASR 识别）。
  - **实施计划**：
    1. 当百炼额度不足或需要额外高精度识别时，在火山控制台新建语音应用；
    2. 获取 `APP_ID`、`ACCESS_TOKEN`、`CLUSTER_ID` 并注入 `.env`；
    3. 在 `apps/tg-bot/services/ai.py` 与 `apps/rss-fetcher/services/ai.py` 中将火山 ASR 编入首选识别梯队：`火山语音 (20h免费)` ➔ `百炼 Paraformer` ➔ `SenseVoice-V1` ➔ `本地 Whisper`。
  - **状态**：`[待启动 / 额度储备]`

- [ ] **SiliconFlow (硅基流动) 0元模型深度编入爬虫与简报流水线**
  - **背景**：硅基流动提供了 Qwen2.5-7B/14B、GLM-4-9B-Chat、DeepSeek-R1-Distill 系列完全 0 元的免费推理模型。
  - **实施计划**：在 `processor.py` 简报生成中将 SiliconFlow 作为火山方舟 DeepSeek 的多模型故障转移通道（Fallback），实现双重免费兜底。
  - **状态**：`[待启动]`

---

## 🏠 二、 N100 第二大脑与知识库演进 (SecondBrain & PKM Pipeline)

- [x] **N100 爬虫去重数据库本地化 (SQLite) 修复与 rclone 隔离保护** `(2026-08-18 完成)`
  - 重构 `database.py` 为本地轻量 SQLite，消除远端 Turso 握手超时；
  - 修复 `run_crawler.sh` 中 `rclone sync` 误删本地生成的 `Auto_Clippings` 与 `Auto_Summary` 问题。
- [x] **扩充 35+ 个全球顶级科技、AI、半导体与宏观智库信源** `(2026-08-18 完成)`
  - 接入 Hacker News Top、Paul Graham 随笔、Simon Willison、SemiAnalysis、Doomberg、Noahpinion、Lenny's Newsletter 等。
- [x] **阶段二：Omni 股票分析仪表盘 (天眼全息智导系统) 阿里云 VPS 容器化上线** `(2026-08-18 完成)`
  - 优化 Dockerfile 为清华源高速安装 uv，秒级构建 `omni-app` 镜像；
  - Podman 启动 `omni-app` 容器（监听 `127.0.0.1:8501`，自启守护）；
  - 配置 Caddy HTTPS 反向代理与 WebSocket 穿透，线上域名 `https://erth.donglida.xyz` 正式提供服务；
  - 保持 `/var/www/bot_audio` 语音驿站与股票系统无缝并行。
- [ ] **阶段三：SecondBrain-Library (文献与电子书智库)**
  - 扩展 TG Bot 支持 EPUB/PDF 文档直接推送，结合 Gemini 自动提炼结构化书评与标签归档。
  - **状态**：`[规划中]`
- [ ] **阶段四：SecondBrain-MCP-Server (统一知识库语义检索服务端)**
  - 构建 MCP 协议服务端，打通 Cursor、Neovim、Pi Agent 等开发工具对个人第二大脑的全库智能检索。
  - **状态**：`[规划中]`
- [ ] **阶段五：图床分离与多媒体存储极致优化**
  - 媒体与长音频外置到 Google Drive / 云存储，Markdown 纯链接化，保持 GitHub 与本地磁盘 0 存储冗余。
  - **状态**：`[规划中]`

---

## 💻 三、 MacOS 极客开发工作流与环境工具

- [x] **`llm-quota` 多平台大模型额度与免费配额实时看板** `(2026-08-18 完成)`
  - 覆盖 Google Gemini、DeepSeek、SiliconFlow、阿里百炼 483 个模型 TPM/RPM、N100 本地大模型。
- [x] **Pi Agent 多模型接入与 Fish Shell 环境固化** `(2026-08-18 完成)`
  - 完成 `~/.pi/agent/` 基础配置与 `infrastructure_profile.md` 跨会话环境规范。
- [ ] **Neovim (NvChad) 实时浮动终端与 AI 快捷键流畅度微调**
  - **状态**：`[日常优化]`

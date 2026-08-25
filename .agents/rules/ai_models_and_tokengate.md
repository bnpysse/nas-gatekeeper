---
description: "AI Models Routing Strategy & TokenGate 2.0 Central Architecture"
---

# 第二大脑 AI 模型矩阵与 TokenGate 2.0 中央门神架构规范

> **继任者必读（Critical Handover Rules）**：
> 1. **火山方舟（VolcEngine）已全线永久下线与硬锁（Limit = 0）**，严禁在任何脚本中发起对 `ark.cn-beijing.volces.com` 的直连调用！
> 2. **Turso 数据库绝不直连阿里云**：国内阿里云 ECS 无法直连东京 Turso，阿里云 TokenGate 通过免密 SSH 隧道（`ssh -p 30022 root@www.donglida.xyz`）向 N100 聚合算力台账数据。
> 3. **全系统统一请求入口**：所有子系统（TGBot、图书流水线、RSS 爬虫、日报汇编、AIOps 医生、天眼参谋部）统一接入 `http://127.0.0.1:8800/v1` 或 `https://tg.donglida.com/v1`。

---

## 🏛️ 一、 100% 传统纯 0 元大模型黄金铁三角

整个第二大脑生态坚决杜绝任何带有按量计费陷阱的渠道，100% 运行于三大零成本通道：

### 1. ☁️ 阿里百炼 (DashScope) —— 临期高智力抢跑主力
* **物理防扣费保险**：控制台已全部开启【免费额度用完即停 (AllocationQuota.FreeTierOnly)】，额度用尽直接返回 403 停止，绝对 0 扣费！
* **核心模型**：
  * `qwen3.7-max-2026-06-08`：千问最强满血旗舰 Max（92万 Tokens，深度推演与考题命制第一主力）；
  * `qwen3.7-plus`：通义千问 Plus（31.3万 Tokens，章节 20% 去水提炼第一主力）；
  * `kimi-k3`：Kimi K3 超长思维链（100万 Tokens，复杂逻辑推演）；
  * `qwen3.8-27b`：通义 3.8 新版（100万 Tokens，干货提炼备用）；
  * `qwen3.7-flash-2026-07-15`：极速清洗主力（100万 Tokens，RSS 抓取与速读）；
  * `qwen3.5-ocr`：多模态图文识别（100万 Tokens，PDF 图表与公式解析）。

### 2. 🌌 魔搭社区 (ModelScope Serverless) —— 开源 2350 亿旗舰
* **配额规则**：纯开源免费社区，每日 2,000 次免费调用（TokenGate 设 1,800 次安全硬锁）；
* **核心模型**：
  * `Qwen/Qwen3-235B-A22B-Thinking-2507`：2350 亿 MoE 深度思考大模型（去水提炼与深度概念辨析主力）；
  * `deepseek-ai/DeepSeek-V4-Pro`：满血开源 DeepSeek 旗舰（深度推理与代码解构）；
  * `deepseek-ai/DeepSeek-V4-Flash-0731`：毫秒级极速清洗；
  * `MiniMax/MiniMax-M1-80k`：80K 长文本大模型。

### 3. ⚡ 硅基流动 (SiliconFlow) —— 0 元原生永久免费保底池
* **配额规则**：官方永久 0 元免费模型（无限额度，全天候保底兜底）；
* **核心模型**：
  * `deepseek-ai/DeepSeek-V3`：671B MoE 满血版（全系统最终兜底）；
  * `BAAI/bge-m3`：1024/2560 维高精向量（知识库语义检索 RAG 底座）；
  * `BAAI/bge-reranker-v2-m3`：检索多路召回重排模型；
  * `FunAudioLLM/SenseVoiceSmall`：多语言语音转文字 ASR。

---

## 🚦 二、 业务任务分流级联梯队 (Task Cascades)

| 业务场景 | 任务标识 (`task_type`) | 自动级联调度梯队 |
| :--- | :---: | :--- |
| **深度推理 / 架构推演 / 考题命制** | `reasoning` | 🥇 阿里百炼 `qwen3.7-max` ➔ 🥈 魔搭 `DeepSeek-V4-Pro` ➔ 🥉 百炼 `kimi-k3` ➔ 4️⃣ 魔搭 `Qwen3-235B` ➔ 5️⃣ 硅基 `DeepSeek-V3` (无限保底) |
| **章节 20% 去水提炼 / 讲义重构** | `distill` | 🥇 阿里百炼 `qwen3.7-plus` ➔ 🥈 魔搭 `Qwen3-235B` (2350亿主力) ➔ 🥉 百炼 `qwen3.8-27b` ➔ 4️⃣ 魔搭 `MiniMax-M1-80k` ➔ 5️⃣ 硅基 `DeepSeek-V3` (无限保底) |
| **快速清洗 / 提取摘要 / RSS 速读** | `fast_clean` | 🥇 阿里百炼 `qwen3.7-flash` ➔ 🥈 魔搭 `DeepSeek-V4-Flash` ➔ 🥉 硅基 `DeepSeek-V3` (无限保底) |
| **通用对话 / 问答 / 伴读答疑** | `general` | 🥇 百炼 `qwen3.7-max` ➔ 🥈 百炼 `qwen3.7-plus` ➔ 🥉 魔搭 `DeepSeek-V4-Pro` ➔ 4️⃣ 魔搭 `Qwen3-235B` ➔ 5️⃣ 硅基 `DeepSeek-V3` |

---

## 🖥️ 三、 核心服务部署与运维清单 (Host & Service Inventory)

### 1. N100 算力节点 (`192.168.2.9` / `www.donglida.xyz:30022`)
* `secondbrain-worker.service`：AI 图书常驻批处理流水线（队列处理 Google Drive 2500+ 本专著）；
* `library_web.service`：AI 图书馆 Web 交互平台（Port `8888`，绑定 `https://lib.donglida.com`，内置 3 次退避重试与 30s 内存热缓存）；
* `obsidian_bot.service`：Telegram 智能伴读与语音转文字机器人；
* `run_crawler.sh`（Cron: `0 */2 * * *`）：RSS 抓取、全文翻译、每日全景情报汇编（`Daily_Summary`）；
* `crawler_doctor.py`（Cron: `*/30 * * * *`）：AIOps 自愈巡检医生，自动消除僵尸锁并触发沙盒自愈。

### 2. 阿里云云端门禁节点 (`47.101.190.145`)
* `tokengate.service`：TokenGate 2.0 智能中央网关（Port `8800`，绑定 `https://tg.donglida.com`）；
* 统一接口：
  * `POST /v1/chat/completions`：OpenAI 兼容对话补全代理；
  * `POST /v1/embeddings`：BGE-M3 向量化代理；
  * `GET /api/usage/summary` & `GET /api/ledger`：全景算力总账 API（SSH 管道聚合 N100 Turso 台账）；
  * `POST /api/heartbeat/crawler`：爬虫流水线心跳打卡接口。

<div align="center">

# 🚪 TokenGate
### 全网免费大模型算力门禁与智能调度网关
**Universal Free-Tier LLM Quota Gate, Expiration Warning & Smart Router**

[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg?style=flat&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg?style=flat&logo=python&logoColor=white)](https://python.org)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED.svg?style=flat&logo=docker&logoColor=white)](https://docker.com)
[![License](https://img.shields.io/badge/License-MIT-emerald.svg)](LICENSE)

*一站式汇聚、监控、临期预警与智能调度全网免费大模型算力资产（阿里百炼 95+模型、火山方舟 200万/天、魔搭社区 45个Serverless、Google Gemini 1500次/天、硅基流动 0元专区），100% 榨干免费 Token，0 成本运行 AI 应用！*

</div>

---

## 🌟 核心特性 (Features)

- 📊 **全网多平台并发探测**：毫秒级探测各大平台真实可用配额、到期倒计时天数与剩余 Token 比例；
- 🔥 **智能临期预警 (FIFO)**：自动高亮 `< 15天` 临期免费包（如 `qwen3.7-plus`），杜绝任何过期浪费；
- 🔄 **循环保底协同**：智能统筹火山方舟 200万/天、Gemini 1500次/天等“今日不用次日作废”的循环资源；
- 🛡️ **零成本绝对熔断**：模型额度消耗达 98% 自动平滑 Failover，底层物理杜绝产生任何扣费账单；
- 🔌 **三维一体输出引擎**：
  - 🖥️ **暗黑响应式 Web 看板**：模型卡片、进度条、搜索过滤、一键复制；
  - 🔌 **标准 RESTful JSON API**：`/api/quotas` 与 `/api/recommend` 供下游系统调用；
  - ⚡ **OpenAI 兼容代理网关**：`/v1/chat/completions` 支持 Dify, LangChain, Neovim, Omni 天眼直接接入；
  - 📁 **静态文件持久化与 CLI**：自动落盘 `quotas.json` 与终端命令看板；
- 🌐 **Cloudflare 边缘免梯直连**：配套 15 行 CF Worker 反代代码，国内主机 0 成本直通 Gemini！

---

## 🏗️ 架构拓扑 (Architecture)

```mermaid
flowchart TD
    subgraph Clients [客户端与应用终端]
        C1[Omni 天眼量化系统]
        C2[SecondBrain 第二大脑]
        C3[Neovim / Dify / LangChain]
        C4[🖥️ 浏览器 Web 大屏]
    end

    subgraph TokenGate [TokenGate 网关服务]
        UI[🖥️ 现代化 Web 看板]
        API[🔌 REST API (/api/quotas, /api/recommend)]
        PROXY[⚡ OpenAI 兼容反代 (/v1/chat/completions)]
        ROUTER{🧠 智能调度策略引擎}
        DETECTOR[🛡️ 多平台并发异步探测器]
    end

    subgraph Providers [全网各大算力源]
        P1[🔵 阿里百炼 95+ 免费模型包]
        P2[🐳 火山方舟 200万/天 循环补给]
        P3[🔮 魔搭社区 45个 Serverless 池]
        P4[🌐 Google Gemini 1500次/天]
        P5[⚡ 硅基流动 0元专区]
        P6[🐋 DeepSeek 官方 API]
    end

    Clients --> UI & API & PROXY
    PROXY --> ROUTER --> Providers
    DETECTOR --> Providers
```

---

## 🚀 快速上手 (Quick Start)

### 方式 1：本地极速运行 (Local Run)

```bash
# 1. 克隆代码库
git clone https://github.com/bnpysse/TokenGate.git
cd TokenGate

# 2. 安装依赖 (推荐使用 uv 或 pip)
pip install -r requirements.txt

# 3. 配置密钥 (复制模版并填入您拥有的 API Key)
cp .env.example .env

# 4. 启动服务 (访问 http://localhost:8800)
python3 -m tokengate.api.server
```

### 方式 2：Docker 容器一键启动 (Docker Compose)

```bash
cp .env.example .env
docker compose up -d
```

---

## 🎯 命令行看板 (CLI Monitor)

无需打开浏览器，在终端直接运行：

```bash
# 查看全网算力表格看板
python3 -m tokengate.cli

# 获取当前任务最佳模型推荐
python3 -m tokengate.cli --recommend --task coding --strategy expiring_first

# 导出全量 JSON 数据
python3 -m tokengate.cli --json > quotas.json
```

---

## 🔌 API 接口与集成指南

### 1. 获取全网模型配额全景 JSON
```bash
GET /api/quotas
```

### 2. 智能模型选型推荐
```bash
GET /api/recommend?task=coding&strategy=expiring_first
```

### 3. OpenAI 兼容智能路由代理
直接将您的应用（如 LangChain、Dify、Neovim 等）的 Base URL 指向 TokenGate：
```bash
curl http://localhost:8800/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "auto",
    "messages": [{"role": "user", "content": "帮我写一个 Python 快速排序算法"}]
  }'
```

---

## 🛡️ 安全与隐私规范

1. **绝对脱敏**：Web 看板与 API 输出仅展示密钥指纹（如 `ms-2b89****ffe54`），前端与抓包绝不透传完整密钥；
2. **本地隔离**：所有密钥保留在 `.env` 中，`.gitignore` 默认严格忽略；
3. **零报错降级**：未配置的平台自动跳过，不影响其它已配置平台的正常调度。

---

## 📄 License
MIT License © 2026 TokenGate Team.

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
第二大脑·AI 智能图书馆多通道旗舰算力配置模块
支持三大 0 成本主力算力池：
  1. 火山方舟 (VolcEngine Ark)：DeepSeek-V4-Pro (98.7万免费池 · 次日1:1返还) + DeepSeek-V4-Flash (248.3万资源包)
  2. 阿里百炼 (DashScope)：Qwen-Plus (31.3万上下文) + Qwen-Max (深度推理) + Qwen-Long (100万上下文)
  3. Google Gemini：Gemini-3.7-Flash / Gemini-3.5-Flash (100万上下文 · 1500次/天免费)
  4. 硅基流动 (SiliconFlow)：BAAI/bge-m3 (向量化与召回底座 · 永久 0 元免费，严禁调用收费 LLM)
"""

import os
from pathlib import Path
from dotenv import load_dotenv

current_dir = Path(__file__).resolve().parent

# 加载多处可能的 .env 环境变量
for env_path in [
    Path("/opt/nas-gatekeeper/.env"),
    Path("/opt/SecondBrain-Flow/.env"),
    current_dir.parent / ".env",
    current_dir.parent / "apps/tg-bot/.env",
    current_dir.parent / "tokengate/.env",
    Path.home() / ".env"
]:
    if env_path.exists():
        load_dotenv(env_path)
        break
else:
    load_dotenv()


class LibraryConfig:
    # 1. 火山方舟 VolcEngine 满血旗舰 (每日循环返还 + 604万有效资源包)
    VOLCENGINE_API_KEY = os.getenv("VOLCENGINE_API_KEY", "")
    VOLCENGINE_BASE_URL = os.getenv("VOLCENGINE_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
    ENDPOINT_DEEPSEEK_PRO = os.getenv("VOLCENGINE_ENDPOINT_DEEPSEEK_PRO", "ep-20260820195716-snkzx")
    ENDPOINT_DEEPSEEK_FLASH = os.getenv("VOLCENGINE_ENDPOINT_DEEPSEEK_FLASH", "ep-20260809122445-td2g2")
    ENDPOINT_GLM_52 = os.getenv("VOLCENGINE_ENDPOINT_GLM", "ep-20260814105356-zvsw5")

    # 2. 阿里百炼 DashScope 旗舰配置
    DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
    DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    # 3. Google Gemini 旗舰配置 (100万 tokens 超长上下文 · 1500次/天免费)
    GEMINI_API_KEY = os.getenv("GEMINI_PKM_API_KEY", "")
    LOCAL_PROXY = os.getenv("HTTPS_PROXY", "http://192.168.2.3:7890")

    # 主力模型矩阵
    MODEL_PRO = ENDPOINT_DEEPSEEK_PRO         # 火山 DeepSeek-V4-Pro (超强深度透视与全局脉络第一主力)
    MODEL_DISTILLER = "qwen-plus"            # 阿里百炼通义千问 Plus (31.3万超长上下文 · 去水精讲提炼第一主力)
    MODEL_REASONER = ENDPOINT_DEEPSEEK_PRO   # 火山 DeepSeek-V4-Pro / Qwen-Max
    MODEL_FLASH = ENDPOINT_DEEPSEEK_FLASH    # 火山 DeepSeek-V4-Flash (极速清洗)
    MODEL_GEMINI = "gemini-3.5-flash-lite"   # Google Gemini 3.5 Flash Lite (100万超大上下文 · 1.2s 极速 · 1500次/天免费)
    # 4. 国家超算互联网 SCNet 配置 (1000万超算旗舰算力 · 1个月到期优先消灭)
    SCNET_API_KEY = os.getenv(
        "SCNET_API_KEY",
        "sk-MTg4LTExNzUwMzY2NDQzLTE3ODc5MjY5ODIyMjY="
    )
    SCNET_BASE_URL = "https://api.scnet.cn/api/llm/v1"
    MODEL_SCNET = "SCNet-Max"

    # 5. 硅基流动统一配置 (仅用于 BGE-M3 向量化，永久 0 元免费)
    SILICONFLOW_API_KEY = os.getenv(
        "SILICONFLOW_API_KEY",
        "sk-wewpjlyfvwflfcqivobyumvhybqldextibizkxtkmajkkqvs"
    )
    SILICONFLOW_BASE_URL = "https://api.siliconflow.cn/v1"
    EMBEDDING_MODEL = "BAAI/bge-m3"
    RERANK_MODEL = "BAAI/bge-reranker-v2-m3"
    EMBEDDING_DIM = 1024

    # 5. 输出目录配置
    WORKSPACE_DIR = Path(__file__).resolve().parent
    OUTPUT_DIR = WORKSPACE_DIR / "output"
    DOWNLOADS_DIR = WORKSPACE_DIR / "downloads"

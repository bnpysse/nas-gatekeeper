#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
第二大脑·AI 智能图书馆配置模块
火山方舟双引擎 (Doubao-Evolving + DeepSeek-V4-Pro) + 硅基流动 BGE-M3 (0元原生免费版)
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()
class LibraryConfig:
    # 1. 硅基流动统一配置 (DeepSeek-V3 满血 671B MoE 原生永久 0 元 + BGE-M3 向量)
    SILICONFLOW_API_KEY = os.getenv(
        "SILICONFLOW_API_KEY",
        "sk-wewpjlyfvwflfcqivobyumvhybqldextibizkxtkmajkkqvs"
    )
    SILICONFLOW_BASE_URL = "https://api.siliconflow.cn/v1"
    
    MODEL_DISTILLER = "deepseek-ai/DeepSeek-V3" # 章节级 20% 去水提炼主力 (0元免费)
    MODEL_REASONER = "deepseek-ai/DeepSeek-V3"  # 3分钟全景透视/Mermaid/题库 (0元免费)
    MODEL_FLASH = "deepseek-ai/DeepSeek-V3"     # 快速交互清洗 (0元免费)

    EMBEDDING_MODEL = "BAAI/bge-m3"
    RERANK_MODEL = "BAAI/bge-reranker-v2-m3"
    EMBEDDING_DIM = 1024

    # 2. 火山方舟统一 ARK 凭证 (备用)
    VOLCENGINE_API_KEY = os.getenv(
        "VOLCENGINE_API_KEY",
        ""
    )
    VOLCENGINE_BASE_URL = os.getenv(
        "VOLCENGINE_BASE_URL",
        "https://ark.cn-beijing.volces.com/api/v3"
    )

    ENDPOINT_GLM = os.getenv("VOLCENGINE_ENDPOINT_GLM", "ep-20260814105356-zvsw5")
    ENDPOINT_DEEPSEEK_PRO = os.getenv("VOLCENGINE_ENDPOINT_DEEPSEEK_PRO", "ep-20260820195716-snkzx")
    ENDPOINT_DEEPSEEK_FLASH = os.getenv("VOLCENGINE_ENDPOINT_DEEPSEEK_FLASH", "ep-20260809122445-td2g2")

    # 3. 输出目录配置
    WORKSPACE_DIR = Path(__file__).resolve().parent
    OUTPUT_DIR = WORKSPACE_DIR / "output"
    DOWNLOADS_DIR = WORKSPACE_DIR / "downloads"

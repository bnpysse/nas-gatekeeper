#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TokenGate 配置与安全脱敏管理模块
"""

import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# 加载 .env 文件（优先读取当前目录及父目录下的 .env）
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

def mask_key(key: Optional[str]) -> str:
    """将敏感 API Key 脱敏为安全指纹 (例: ms-2b89****ffe54)"""
    if not key:
        return "未配置"
    key = key.strip()
    if len(key) <= 8:
        return "****"
    prefix = key[:6]
    suffix = key[-5:]
    return f"{prefix}****{suffix}"

class Settings:
    PORT: int = int(os.environ.get("PORT", "8800"))
    HOST: str = os.environ.get("HOST", "0.0.0.0")

    # API 密钥配置
    DASHSCOPE_API_KEY: str = os.environ.get("DASHSCOPE_API_KEY", "")
    VOLCENGINE_API_KEY: str = os.environ.get("VOLCENGINE_API_KEY", "")
    VOLCENGINE_ENDPOINT_ID: str = os.environ.get("VOLCENGINE_ENDPOINT_ID", "")
    VOLCENGINE_ENDPOINT_DEEPSEEK_PRO: str = os.environ.get("VOLCENGINE_ENDPOINT_DEEPSEEK_PRO", "")
    VOLCENGINE_ENDPOINT_DOUBAO: str = os.environ.get("VOLCENGINE_ENDPOINT_DOUBAO", "")
    VOLCENGINE_ENDPOINT_GLM: str = os.environ.get("VOLCENGINE_ENDPOINT_GLM", "")
    VOLCENGINE_ENDPOINT_DEEPSEEK_FLASH: str = os.environ.get("VOLCENGINE_ENDPOINT_DEEPSEEK_FLASH", "")
    MODELSCOPE_API_KEY: str = os.environ.get("MODELSCOPE_API_KEY", "")
    GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", "")
    GEMINI_BASE_URL: str = os.environ.get("GEMINI_BASE_URL", "")
    DEEPSEEK_API_KEY: str = os.environ.get("DEEPSEEK_API_KEY", "")
    SILICONFLOW_API_KEY: str = os.environ.get("SILICONFLOW_API_KEY", "")

    # 代理
    HTTP_PROXY: str = os.environ.get("HTTP_PROXY", "")
    HTTPS_PROXY: str = os.environ.get("HTTPS_PROXY", "")

    # 基础路径
    DATA_DIR: Path = BASE_DIR / "data"

settings = Settings()
settings.DATA_DIR.mkdir(parents=True, exist_ok=True)

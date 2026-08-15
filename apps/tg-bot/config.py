#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
配置加载器：支持从系统环境变量或 .env 文件读取
支持自动感知操作系统 (macOS / Linux / Docker 容器) 匹配路径
"""

import os
import platform
from pathlib import Path
from dotenv import load_dotenv

# 优先读取当前目录、模块目录或 /etc 下的 .env
env_paths = [
    Path(__file__).parent / ".env",
    Path(__file__).parent.parent / ".env",
    Path("/etc/secondbrain/secondbrain.env"),
]

for env_path in env_paths:
    if env_path.exists():
        load_dotenv(dotenv_path=env_path, override=True)
        break
else:
    load_dotenv(override=True)

def get_default_inbox_path() -> Path:
    """获取默认的 Obsidian Inbox 保存路径"""
    if os.getenv("DOCKER_ENV"):
        return Path("/app/notes/Inbox")
    elif platform.system() == "Darwin":
        return Path.home() / "Library/Mobile Documents/iCloud~md~obsidian/Documents/notes/Inbox"
    else:
        return Path("/opt/obsidian/vault/Inbox")

def get_default_gdrive_path() -> Path | None:
    """获取本地挂载的 Google Drive 路径"""
    if platform.system() == "Darwin":
        cloud_storage = Path.home() / "Library/CloudStorage"
        if cloud_storage.exists():
            for gdrive_dir in cloud_storage.glob("GoogleDrive-*"):
                for drive_name in ["我的云端硬盘", "My Drive"]:
                    inbox_dir = gdrive_dir / drive_name / "Inbox"
                    inbox_dir.mkdir(parents=True, exist_ok=True)
                    if inbox_dir.exists():
                        return inbox_dir
                    drive_dir = gdrive_dir / drive_name
                    if drive_dir.exists():
                        return drive_dir
    return None

class Config:
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    ALLOWED_USER_ID = int(os.getenv("ALLOWED_USER_ID", "0"))
    
    GEMINI_API_KEY = os.getenv("GEMINI_PKM_API_KEY") or os.getenv("GEMINI_API_KEY", "")
    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
    DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
    GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
    VOLCENGINE_API_KEY = os.getenv("VOLCENGINE_API_KEY", "")
    VOLCENGINE_ENDPOINT_ID = os.getenv("VOLCENGINE_ENDPOINT_ID", "")
    VOLCENGINE_EMBEDDING_ENDPOINT_ID = os.getenv("VOLCENGINE_EMBEDDING_ENDPOINT_ID", "")
    
    # --- 模型配置 ---
    DASHSCOPE_CHAT_MODEL = os.getenv("DASHSCOPE_CHAT_MODEL", "qwen3.8-max")
    DASHSCOPE_EMBEDDING_MODEL = os.getenv("DASHSCOPE_EMBEDDING_MODEL", "text-embedding-v3")
    TURSO_DATABASE_URL = os.getenv("TURSO_DATABASE_URL", "")
    TURSO_AUTH_TOKEN = os.getenv("TURSO_AUTH_TOKEN", "")
    
    HTTP_PROXY = os.getenv("HTTP_PROXY") or os.getenv("http_proxy", "")
    HTTPS_PROXY = os.getenv("HTTPS_PROXY") or os.getenv("https_proxy", "")

    # 在 Docker 容器内部自动将 127.0.0.1 / localhost 指向宿主机 host.docker.internal
    if os.getenv("DOCKER_ENV"):
        if "127.0.0.1" in HTTP_PROXY or "localhost" in HTTP_PROXY:
            HTTP_PROXY = HTTP_PROXY.replace("127.0.0.1", "host.docker.internal").replace("localhost", "host.docker.internal")
        if "127.0.0.1" in HTTPS_PROXY or "localhost" in HTTPS_PROXY:
            HTTPS_PROXY = HTTPS_PROXY.replace("127.0.0.1", "host.docker.internal").replace("localhost", "host.docker.internal")

    if HTTP_PROXY and not (HTTP_PROXY.startswith("http://") or HTTP_PROXY.startswith("https://") or HTTP_PROXY.startswith("socks")):
        HTTP_PROXY = f"http://{HTTP_PROXY}"
    if HTTPS_PROXY and not (HTTPS_PROXY.startswith("http://") or HTTPS_PROXY.startswith("https://") or HTTPS_PROXY.startswith("socks")):
        HTTPS_PROXY = f"http://{HTTPS_PROXY}"

    # 移除环境变量中的代理，防止污染第三方库 (如 Dashscope 导致请求卡死)
    for env_key in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"]:
        if env_key in os.environ:
            del os.environ[env_key]
    
    raw_inbox = os.getenv("OBSIDIAN_INBOX_PATH", "")
    if raw_inbox and raw_inbox.strip():
        OBSIDIAN_INBOX_PATH = Path(os.path.expanduser(raw_inbox.strip()))
    else:
        OBSIDIAN_INBOX_PATH = get_default_inbox_path()

    raw_gdrive = os.getenv("GDRIVE_SYNC_PATH", "")
    if raw_gdrive and raw_gdrive.strip():
        GDRIVE_SYNC_PATH = Path(os.path.expanduser(raw_gdrive.strip()))
    else:
        GDRIVE_SYNC_PATH = get_default_gdrive_path()

    INBOX_AUTO_PRUNE_DAYS = int(os.getenv("INBOX_AUTO_PRUNE_DAYS", "30"))

    @classmethod
    def validate(cls):
        """校验关键配置项目"""
        missing = []
        if not cls.TELEGRAM_BOT_TOKEN:
            missing.append("TELEGRAM_BOT_TOKEN")
        if not cls.DASHSCOPE_API_KEY:
            missing.append("DASHSCOPE_API_KEY")
        if not cls.ALLOWED_USER_ID:
            missing.append("ALLOWED_USER_ID")
            
        if missing:
            raise ValueError(f"缺少必要配置项目，请在 .env 中设置: {', '.join(missing)}")

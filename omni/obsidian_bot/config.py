#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
配置加载器：支持从系统环境变量或 .env / /etc/nas-gatekeeper/obsidian_bot.env 读取
智能根据操作系统 (macOS / Linux) 匹配默认 Obsidian Inbox 路径
"""

import os
import platform
from pathlib import Path
from dotenv import load_dotenv

# 尝试优先读取系统预设路径，其次读取当前目录下的 .env
env_paths = [
    Path("/etc/nas-gatekeeper/obsidian_bot.env"),
    Path(__file__).parent / ".env",
]

for env_path in env_paths:
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)
        break
else:
    load_dotenv()

def get_default_inbox_path() -> Path:
    """智能获取默认的 Inbox 路径"""
    if platform.system() == "Darwin":
        # macOS 下默认匹配 iCloud 中的 Obsidian 主仓库 notes/Inbox
        return Path.home() / "Library/Mobile Documents/iCloud~md~obsidian/Documents/notes/Inbox"
    else:
        # Linux (N100) 环境下默认路径
        return Path("/opt/obsidian/vault/Inbox")

def get_default_gdrive_path() -> Path | None:
    """智能自动搜索本地挂载的 Google Drive 同步目录 (如 ~/Library/CloudStorage/GoogleDrive-*/我的云端硬盘/Stock)"""
    if platform.system() == "Darwin":
        cloud_storage = Path.home() / "Library/CloudStorage"
        if cloud_storage.exists():
            for gdrive_dir in cloud_storage.glob("GoogleDrive-*"):
                for drive_name in ["我的云端硬盘", "My Drive"]:
                    stock_dir = gdrive_dir / drive_name / "Stock"
                    if stock_dir.exists():
                        return stock_dir
                    drive_dir = gdrive_dir / drive_name
                    if drive_dir.exists():
                        return drive_dir
    return None

class Config:
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    ALLOWED_USER_ID = int(os.getenv("ALLOWED_USER_ID", "0"))
    
    # 优先读取 GEMINI_PKM_API_KEY，后备 GEMINI_API_KEY
    GEMINI_API_KEY = os.getenv("GEMINI_PKM_API_KEY") or os.getenv("GEMINI_API_KEY", "")
    
    HTTP_PROXY = os.getenv("HTTP_PROXY") or os.getenv("http_proxy", "")
    HTTPS_PROXY = os.getenv("HTTPS_PROXY") or os.getenv("https_proxy", "")
    
    # 智能展开波浪号 ~ 和匹配操作系统默认值
    raw_inbox = os.getenv("OBSIDIAN_INBOX_PATH", "")
    if raw_inbox and raw_inbox.strip():
        OBSIDIAN_INBOX_PATH = Path(os.path.expanduser(raw_inbox.strip()))
    else:
        OBSIDIAN_INBOX_PATH = get_default_inbox_path()

    # Google Drive 自动同步路径
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
        if not cls.ALLOWED_USER_ID:
            missing.append("ALLOWED_USER_ID")
        if not cls.GEMINI_API_KEY:
            missing.append("GEMINI_PKM_API_KEY")
            
        if missing:
            raise ValueError(f"缺少必要配置项目，请在 .env 中设置: {', '.join(missing)}")

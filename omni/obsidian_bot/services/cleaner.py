#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Inbox 定时自动清理组件：清除超过指定天数 (默认30天) 未归档的抓取草稿笔记
"""

import os
import sys
import time
import logging
from pathlib import Path

parent_dir = str(Path(__file__).resolve().parent.parent)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from config import Config

logger = logging.getLogger(__name__)

def auto_prune_inbox() -> int:
    """
    清理指定天数前且未标记 #keep 的 Inbox 草稿
    返回清理的文件数
    """
    inbox_dir = Config.OBSIDIAN_INBOX_PATH
    if not inbox_dir.exists():
        return 0

    max_age_seconds = Config.INBOX_AUTO_PRUNE_DAYS * 86400
    now = time.time()
    pruned_count = 0

    for file_path in inbox_dir.glob("*.md"):
        try:
            mtime = file_path.stat().st_mtime
            age_seconds = now - mtime

            if age_seconds > max_age_seconds:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    file_content = f.read(2048)

                if "#keep" in file_content or "keep: true" in file_content:
                    logger.info(f"跳过包含 #keep 标记的过期文件: {file_path.name}")
                    continue

                trash_dir = inbox_dir / ".trash"
                trash_dir.mkdir(exist_ok=True)
                
                target_path = trash_dir / file_path.name
                file_path.rename(target_path)
                logger.info(f"已清理超过 {Config.INBOX_AUTO_PRUNE_DAYS} 天的旧草稿: {file_path.name} -> .trash/")
                pruned_count += 1

        except Exception as e:
            logger.error(f"清理文件失败 {file_path}: {e}")

    return pruned_count

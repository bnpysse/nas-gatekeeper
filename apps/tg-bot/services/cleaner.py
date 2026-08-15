#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
定时清理模块：自动定期扫描 Inbox 目录并移走过期临时草稿
"""

import sys
import logging
from datetime import datetime, timedelta
from pathlib import Path

parent_dir = str(Path(__file__).resolve().parent.parent)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from config import Config

logger = logging.getLogger(__name__)

def auto_prune_inbox() -> int:
    """清理 Inbox 超过设定天数的解理草稿"""
    inbox_dir = Config.OBSIDIAN_INBOX_PATH
    if not inbox_dir.exists():
        return 0

    days = Config.INBOX_AUTO_PRUNE_DAYS
    cutoff = datetime.now() - timedelta(days=days)
    removed_count = 0

    for note_file in inbox_dir.glob("*.md"):
        try:
            mtime = datetime.fromtimestamp(note_file.stat().st_mtime)
            if mtime < cutoff:
                logger.info(f"清理过期草稿文件: {note_file.name}")
                note_file.unlink()
                removed_count += 1
        except Exception as e:
            logger.warning(f"处理文件 {note_file} 失败: {e}")

    return removed_count

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Obsidian 文件写入组件：生成美观的带有 YAML Frontmatter 的 Markdown 笔记并保存至 Inbox
"""

import re
import sys
import logging
from datetime import datetime
from pathlib import Path

parent_dir = str(Path(__file__).resolve().parent.parent)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from config import Config

logger = logging.getLogger(__name__)

def sanitize_filename(name: str) -> str:
    """清理非法的文件名字符"""
    clean = re.sub(r'[\\/:*?"<>|]', '_', name)
    return clean.strip()[:60]

def save_to_obsidian_inbox(title: str, url: str, content: str, source_type: str = "Video") -> Path:
    """
    格式化并保存笔记到 Obsidian 的 Inbox 目录
    """
    inbox_dir = Config.OBSIDIAN_INBOX_PATH
    inbox_dir.mkdir(parents=True, exist_ok=True)

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    date_prefix = datetime.now().strftime("%Y%m%d_%H%M")
    
    clean_title = sanitize_filename(title)
    filename = f"[{source_type}] {date_prefix}_{clean_title}.md"
    file_path = inbox_dir / filename

    yaml_header = f"""---
title: "{title}"
url: "{url}"
source: "{source_type}"
captured_at: {now_str}
tags:
  - inbox/capture
  - source/{source_type.lower()}
status: unread
---

# {title}

> [!NOTE] 捕获元数据
> - **来源**: [{source_type}]({url})
> - **捕获时间**: `{now_str}`

{content}
"""

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(yaml_header)

    logger.info(f"成功保存 Markdown 笔记到 Obsidian Inbox: {file_path}")

    # 1. 优先尝试 Google Drive API (v3) 云端直传 (无视 Mac 是否关机，24/7 运行于 N100)
    try:
        from services.gdrive import upload_file_to_gdrive_api
        gdrive_url = upload_file_to_gdrive_api(file_path, target_folder_name="Stock")
        if gdrive_url:
            logger.info(f"☁️ Google Drive API 云端直传成功: {gdrive_url}")
    except Exception as e:
        logger.warning(f"Google Drive API 呼叫异常: {e}")

    # 2. 备用：自动同步至 macOS 本地挂载的 Google Drive 镜像目录 (如果存在)
    gdrive_path = getattr(Config, "GDRIVE_SYNC_PATH", None)
    if gdrive_path and gdrive_path.exists():
        try:
            import shutil
            gdrive_file = gdrive_path / filename
            shutil.copy2(file_path, gdrive_file)
            logger.info(f"☁️ 本地镜像同步到 Google Drive 目录成功: {gdrive_file}")
        except Exception as e:
            logger.warning(f"同步至本地 Google Drive 目录失败: {e}")

    return file_path

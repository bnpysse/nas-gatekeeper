#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Markdown 笔记落盘模块：带有标准 YAML Frontmatter 的 Markdown 笔记生成与云端同步
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
    """清理非法文件名字符，防止云端部署 URL 解析错误"""
    clean = re.sub(r'[\\/:*?"<>|?#%&+=？!！()]', '_', name)
    return clean.strip(' .')[:60].strip(' .')

async def save_to_obsidian_inbox(title: str, url: str, content: str, source_type: str = "Video") -> Path:
    """格式化并保存 Markdown 笔记到 Obsidian Inbox，并触发 OneDrive 同步"""
    inbox_dir = Config.OBSIDIAN_INBOX_PATH
    inbox_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. RAG 向量化与双链生成
    try:
        from services.rag import get_embedding, search_similar_notes, upsert_note, init_db
        from services.ai import get_volcengine_async_client
        await init_db()
        embedding = await get_embedding(content)
        similar_notes = await search_similar_notes(embedding, limit=3)
        
        rag_section = ""
        if similar_notes:
            rag_section = "\n\n## 🔗 AI 图谱双向关联\n"
            context_text = "\n".join([f"- {n['title']}: {n['content'][:100]}..." for n in similar_notes])
            prompt = f"当前笔记标题：{title}\n相似的历史笔记如下：\n{context_text}\n请你作为 Obsidian 知识库管理员，用一段非常简短的话（不超过100字）总结当前笔记与这些历史笔记的关联，并在文中直接使用确切的双向链接格式 [[历史笔记的标题]] 引用它们。"
            try:
                client = get_volcengine_async_client()
                resp = await client.chat.completions.create(
                    model=Config.VOLCENGINE_ENDPOINT_ID or "ep-20260809122445-td2g2",
                    messages=[{"role": "user", "content": prompt}]
                )
                rag_section += resp.choices[0].message.content + "\n"
            except Exception as e:
                logger.error(f"大模型生成双链语境失败，降级为直列: {e}")
                for n in similar_notes:
                    rag_section += f"- [[{n['title']}]]\n"
                    
            content += rag_section
    except Exception as e:
        logger.error(f"RAG 模块执行异常: {e}")
        embedding = []

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    date_prefix = datetime.now().strftime("%Y%m%d_%H%M")
    
    clean_title = sanitize_filename(title)
    
    # 确定前缀
    prefix = "WA"  # 默认普通网页 Web Article
    if "douyin.com" in url:
        prefix = "DA"
    elif "xueqiu.com" in url:
        prefix = "XA"
    elif source_type == "Toutiao_Video":
        prefix = "TV"
    elif source_type == "Toutiao_Article":
        prefix = "TA"
    elif source_type == "Memo":
        prefix = "Memo"
    elif source_type == "Web":
        prefix = "WA"
        
    filename = f"[{prefix}]{clean_title}_{date_prefix}.md"
    file_path = inbox_dir / filename

    import json
    safe_title = json.dumps(title, ensure_ascii=False)
    safe_url = json.dumps(url, ensure_ascii=False)
    safe_source = json.dumps(source_type, ensure_ascii=False)
    
    yaml_header = f"""---
title: {safe_title}
url: {safe_url}
source: {safe_source}
captured_at: {now_str}
tags:
  - inbox/capture
  - source/{source_type.lower()}
status: unread
---\n
# {title}\n
> [!NOTE] 捕获元数据
> - **来源**: [{source_type}]({url})
> - **捕获时间**: `{now_str}`\n
{content}
"""

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(yaml_header)

    logger.info(f"成功保存 Markdown 笔记至 Inbox: {file_path}")
    
    # 2. RAG 入库
    try:
        if embedding:
            await upsert_note(filename, title, str(file_path), content, embedding)
    except Exception as e:
        logger.error(f"RAG 入库失败: {e}")

    # 3. 使用 rclone 自动双向同步 (Google Drive + OneDrive)
    try:
        import subprocess
        logger.info("☁️ 正在通过 rclone 同步至 Google Drive (根目录)...")
        # 优先同步到 Google Drive (你期望的主力)
        subprocess.run([
            "rclone", "copy", str(file_path), "gdrive:Inbox/"
        ], check=False, capture_output=True, text=True)
        
        logger.info("☁️ 正在通过 rclone 同步至 OneDrive (备份)...")
        # 备份同步到 OneDrive
        subprocess.run([
            "rclone", "copy", str(file_path), "onedrive:应用/remotely-save/notes/Inbox/"
        ], check=False, capture_output=True, text=True)
        logger.info(f"☁️ 双云盘同步完成!")
    except Exception as e:
        logger.warning(f"云盘同步异常: {e}")

    return file_path

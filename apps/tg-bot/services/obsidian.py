#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Markdown 笔记落盘模块：带有标准 YAML Frontmatter 的 Markdown 笔记生成与云端同步
支持分流落库至 Inbox（音视频）与 Auto_Clippings（微信/网页/专栏剪藏）
"""

import re
import sys
import os
import shutil
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

def get_autoclippings_dir() -> Path:
    """获取 Auto_Clippings 目录"""
    p = Config.OBSIDIAN_INBOX_PATH.parent / "Auto_Clippings"
    if p.exists():
        return p
    default_p = Path("/opt/obsidian-brain-data/Auto_Clippings")
    default_p.mkdir(parents=True, exist_ok=True)
    return default_p

async def save_to_obsidian_autoclippings(
    title: str,
    url: str,
    raw_content: str,
    summary_content: str,
    source_type: str = "WeChat",
    account_name: str = "微信精选"
) -> dict:
    """
    将微信文章/头条文章完整双轨归档至 Auto_Clippings:
    1. Raw_微信_【公众号】_标题.md (完整原文沉淀)
    2. Auto_简报_微信_【公众号】_标题.md (AI 深度拆解报告)
    """
    clippings_dir = get_autoclippings_dir()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    clean_title = sanitize_filename(title)
    clean_account = sanitize_filename(account_name) or "微信精选"
    
    # 1. 准备 RAG 向量与双向链接
    embedding = []
    try:
        from services.rag import get_embedding, search_similar_notes, upsert_note, init_db
        from services.ai import get_volcengine_async_client
        await init_db()
        embedding = await get_embedding(summary_content)
        similar_notes = []
        if embedding:
            similar_notes = await search_similar_notes(embedding, limit=3)
        
        if similar_notes:
            rag_section = "\n\n## 🔗 AI 知识库双向关联\n"
            for n in similar_notes:
                clean_target = re.sub(r'\[.*?\]', '', n.get("title", "")).strip(' _-')
                rag_section += f"- [[{clean_target}]]\n"
            summary_content += rag_section
    except Exception as e:
        logger.warning(f"RAG 双链计算跳过: {e}")

    # 2. 写入 Raw 原文完整归档
    raw_filename = f"Raw_微信_{clean_account}_{clean_title}.md"
    raw_path = clippings_dir / raw_filename
    
    raw_yaml = f"""---
title: "Raw_{clean_title}"
date: "{now_str}"
created: "{now_str}"
url: "{url}"
source: "微信公众号 - {account_name}"
author: "{account_name}"
tags:
  - 微信精选
  - 微信文章_全文
  - "{clean_account}"
status: processed
---

# 原文归档：{title}

> [!NOTE] 微信文章元数据
> - **来源公众号**: `{account_name}`
> - **原文链接**: [{url}]({url})
> - **收录时间**: `{now_str}`

---

{raw_content}
"""
    with open(raw_path, "w", encoding="utf-8") as f:
        f.write(raw_yaml)
    logger.info(f"✅ 微信原文已沉淀至 Auto_Clippings: {raw_path}")

    # 3. 写入 Auto 简报深度分析
    summary_filename = f"Auto_简报_微信_{clean_account}_{clean_title}.md"
    summary_path = clippings_dir / summary_filename
    
    summary_yaml = f"""---
title: "简报_{clean_title}"
date: "{now_str}"
created: "{now_str}"
url: "{url}"
source: "微信公众号 - {account_name}"
author: "{account_name}"
tags:
  - 微信精选_深度解读
  - 智能简报
  - "{clean_account}"
status: completed
---

# 深度精读简报：{title}

> [!TIP] 智能情报卡片
> - **公众号**: `{account_name}`
> - **原文链接**: [点击阅读微信原文]({url})
> - **提炼引擎**: `Volcengine DeepSeek-V4 (AIOps)`

---

{summary_content}
"""
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(summary_yaml)
    logger.info(f"✅ 微信深度简报已保存至 Auto_Clippings: {summary_path}")

    # 4. RAG 数据库入库
    try:
        if embedding:
            from services.rag import upsert_note
            await upsert_note(summary_filename, f"简报_{title}", str(summary_path), summary_content, embedding)
    except Exception as e:
        logger.warning(f"Turso 向量入库异常: {e}")

    # 5. 云盘与 Quartz 镜像同步
    try:
        import subprocess
        # 同步至 Google Drive
        subprocess.run(["rclone", "copy", str(raw_path), "gdrive:Auto_Clippings/"], check=False, capture_output=True)
        subprocess.run(["rclone", "copy", str(summary_path), "gdrive:Auto_Clippings/"], check=False, capture_output=True)
        # 同步至 Quartz
        quartz_clippings = Path("/opt/SecondBrain-Quartz/content/notes/Auto_Clippings")
        if quartz_clippings.parent.exists():
            quartz_clippings.mkdir(parents=True, exist_ok=True)
            shutil.copy2(raw_path, quartz_clippings / raw_filename)
            shutil.copy2(summary_path, quartz_clippings / summary_filename)
    except Exception as e:
        logger.warning(f"同步或镜像异常: {e}")

    return {
        "raw_path": raw_path,
        "summary_path": summary_path,
        "title": title,
        "account": account_name
    }

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
        similar_notes = []
        if embedding:
            similar_notes = await search_similar_notes(embedding, limit=3)
        
        rag_section = ""
        if similar_notes:
            rag_section = "\n\n## 🔗 AI 图谱双向关联\n"
            context_text = "\n".join([f"- 笔记{i+1}: {n['title']} (相关片段: {n['content'][:80]}...)" for i, n in enumerate(similar_notes)])
            prompt = (
                f"当前笔记标题：{title}\n"
                f"相似的历史笔记如下：\n{context_text}\n"
                "请你作为 Obsidian 知识库管理员，用一段极简练的话（80字以内）总结当前笔记与这些历史笔记的关联。"
                "请直接在关联分析中使用形如 [[笔记1]]、[[笔记2]] 的标记来指代对应的历史笔记。"
            )
            try:
                client = get_volcengine_async_client()
                resp = await client.chat.completions.create(
                    model=Config.VOLCENGINE_ENDPOINT_ID or "ep-20260809122445-td2g2",
                    messages=[{"role": "user", "content": prompt}]
                )
                text = resp.choices[0].message.content.strip()
                
                # 将 [[笔记1]]、[[笔记2]] 或包含标题的 [[...]] 替换为真实的内部链接
                for i, n in enumerate(similar_notes):
                    d_id = n.get("doc_id", "")
                    d_title = n.get("title", "") or d_id
                    # 确定相对路径
                    if d_id.startswith("Auto_") or d_id.startswith("Raw_"):
                        target_link = f"[{d_title}](<../Auto_Clippings/{d_id}>)"
                    else:
                        target_link = f"[{d_title}](<./{d_id}>)"
                    
                    # 替换占位符及标题
                    text = text.replace(f"[[笔记{i+1}]]", target_link)
                    text = text.replace(f"[[{d_title}]]", target_link)
                    
                rag_section += text + "\n"
            except Exception as e:
                logger.error(f"大模型生成双链语境失败，降级为直列: {e}")
                for n in similar_notes:
                    d_id = n.get("doc_id", "")
                    d_title = n.get("title", "") or d_id
                    if d_id.startswith("Auto_") or d_id.startswith("Raw_"):
                        rag_section += f"- [{d_title}](<../Auto_Clippings/{d_id}>)\n"
                    else:
                        rag_section += f"- [{d_title}](<./{d_id}>)\n"
                    
            content += rag_section
    except Exception as e:
        logger.error(f"RAG 模块执行异常: {e}")
        embedding = []

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
        
    # 核心保护机制：如果该笔记此前已存在（如重新生成或补全），必须沿用最初捕获时间与原有文件名，禁止跳到最前端！
    orig_capture_time = None
    file_path = None
    existing_files = list(inbox_dir.glob(f"[{prefix}]{clean_title}*.md"))
    if existing_files:
        file_path = existing_files[0]
        try:
            old_txt = file_path.read_text(encoding="utf-8", errors="ignore")
            m_cap = re.search(r'captured_at:\s*["\']?(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?)["\']?', old_txt)
            if m_cap:
                orig_capture_time = m_cap.group(1).replace("T", " ")
            else:
                m_time = re.search(r'捕获时间[^\n\r`]*`(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?)`', old_txt)
                if m_time:
                    orig_capture_time = m_time.group(1).replace("T", " ")
        except Exception:
            pass

    if orig_capture_time:
        now_str = orig_capture_time if len(orig_capture_time) == 19 else f"{orig_capture_time}:00"
    else:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        date_prefix = datetime.now().strftime("%Y%m%d_%H%M")
        filename = f"[{prefix}]{clean_title}_{date_prefix}.md"
        file_path = inbox_dir / filename

    # 自动转换 Mermaid 图表为 Base64 矢量 SVG
    if "```mermaid" in content and "https://mermaid.ink/svg/" not in content:
        import base64
        pattern = r'```mermaid\s*\n(.*?)\n```'
        def _mermaid_repl(m):
            code = m.group(1).strip()
            obj = {"code": code, "mermaid": {"theme": "default"}}
            b64 = base64.b64encode(json.dumps(obj).encode('utf-8')).decode('ascii')
            svg_url = f"https://mermaid.ink/svg/{b64}"
            return f"\n\n![架构流程图]({svg_url})\n\n<details><summary>📊 查看 Mermaid 流程图源码</summary>\n\n```mermaid\n{code}\n```\n</details>\n\n"
        content = re.sub(pattern, _mermaid_repl, content, flags=re.DOTALL)

    import json
    safe_title = json.dumps(title, ensure_ascii=False)
    safe_url = json.dumps(url, ensure_ascii=False)
    safe_source = json.dumps(source_type, ensure_ascii=False)
    
    # 自动生成 aliases 别名列表，确保 Obsidian 和 Quartz 无论用什么形式都能搜到并正确跳转（限制不超过 120 字节）
    aliases = []
    clean_t = title.strip()
    if clean_t and len(clean_t.encode('utf-8')) <= 120:
        aliases.append(clean_t)
    t_no_model = re.sub(r'^\[多模型\]\s*', '', clean_t).strip()
    if t_no_model and len(t_no_model.encode('utf-8')) <= 120 and t_no_model not in aliases:
        aliases.append(t_no_model)
    t_no_tags = re.sub(r'#[^\s#]+', '', t_no_model).strip()
    if t_no_tags and len(t_no_tags.encode('utf-8')) <= 120 and t_no_tags not in aliases:
        aliases.append(t_no_tags)
    t_norm = re.sub(r'[?？!！_]+$', '', t_no_tags).strip()
    if t_norm and len(t_norm.encode('utf-8')) <= 120 and t_norm not in aliases:
        aliases.append(t_norm)
    aliases_yaml = "\n".join([f"  - {json.dumps(a, ensure_ascii=False)}" for a in aliases])

    yaml_header = f"""---
title: {safe_title}
date: "{now_str}"
created: "{now_str}"
modified: "{now_str}"
published: "{now_str}"
url: {safe_url}
source: {safe_source}
captured_at: "{now_str}"
tags:
  - inbox/capture
  - source/{source_type.lower()}
aliases:
{aliases_yaml}
status: unread
---
\n
# {title}\n
> [!NOTE] 捕获元数据
> - **来源**: [{source_type}]({url})
> - **捕获时间**: `{now_str}`\n
{content}
"""

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(yaml_header)

    # 同步保持文件系统时间与实际捕获时间一致
    try:
        dt_obj = datetime.strptime(now_str, "%Y-%m-%d %H:%M:%S")
        ts = dt_obj.timestamp()
        os.utime(file_path, (ts, ts))
    except Exception:
        pass

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
        subprocess.run([
            "rclone", "copy", str(file_path), "gdrive:Inbox/"
        ], check=False, capture_output=True, text=True)
        
        logger.info("☁️ 正在通过 rclone 同步至 OneDrive (备份)...")
        subprocess.run([
            "rclone", "copy", str(file_path), "onedrive:应用/remotely-save/notes/Inbox/"
        ], check=False, capture_output=True, text=True)
    except Exception as e:
        logger.warning(f"云盘同步异常: {e}")

    # 4. 实时镜像到 Quartz 目录以触发即时构建
    try:
        quartz_inbox = Path("/opt/SecondBrain-Quartz/content/notes/Inbox")
        if quartz_inbox.parent.exists():
            quartz_inbox.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file_path, quartz_inbox / filename)
    except Exception as q_err:
        logger.warning(f"Quartz 镜像异常: {q_err}")

    return file_path

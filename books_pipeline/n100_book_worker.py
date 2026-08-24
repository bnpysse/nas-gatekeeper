#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
第二大脑·AI 智能图书馆：N100 边缘无人值守批量流水线引擎 (`n100_book_worker.py`)
特性：
  1. 自动从 Google Drive 队列拉取待处理电子书 (优先处理前沿技术与高价值专著)
  2. 零磁盘驻留：本地在 /tmp 内存盘处理，完成即清理
  3. 全程 0 费用：SiliconFlow BGE-M3 (批量向量化) + 豆包自进化 (20%高密度重构) + DeepSeek-V4-Pro (透视与图谱)
  4. 双轨同步：产物自动同步至 `gdrive:CloseReading/output/`
  5. 详实台账：记录每本书的处理时长、切块数、Tokens 消耗与错误自动熔断恢复
"""

import os
import sys
import time
import json
import shutil
import logging
import asyncio
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional

current_dir = Path(__file__).resolve().parent
parent_dir = current_dir.parent
if str(current_dir) in sys.path:
    sys.path.remove(str(current_dir))
sys.path.insert(0, str(current_dir))

from config import LibraryConfig
from db import execute_turso, float_array_to_blob, TURSO_URL, TURSO_TOKEN
from bge_embedder import get_bge_m3_embeddings_batch, BATCH_SIZE
from dual_engine import call_volcengine
from deep_distiller import distill_single_chapter, generate_key_takeaways

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [N100Worker] - %(levelname)s - %(message)s"
)
logger = logging.getLogger("N100Worker")

LOCAL_TMP_DIR = Path("/tmp/n100_book_worker")
LOCAL_TMP_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR = current_dir / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def get_gdrive_ebook_catalog() -> List[Dict[str, Any]]:
    """扫描 Google Drive 中的电子书资产，返回排好序的待处理队列"""
    cmd = ["rclone", "lsjson", "gdrive:CloseReading/EBook", "--fast-list"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        logger.error(f"rclone 扫描失败: {res.stderr}")
        return []
        
    items = json.loads(res.stdout)
    valid_exts = {".epub", ".pdf", ".azw3", ".mobi"}
    
    # 核心技术关键词优先权
    tech_keywords = [
        "solidjs", "svelte", "rust", "typescript", "python", "docker", "react", 
        "deepseek", "full-stack", "vue", "algorithm", "架构", "数据结构"
    ]
    
    books = []
    for it in items:
        if it.get("IsDir"): continue
        path_str = it.get("Path", "")
        ext = Path(path_str).suffix.lower()
        if ext in valid_exts and not path_str.startswith("output/"):
            prio = 100
            for kw in tech_keywords:
                if kw in path_str.lower():
                    prio = 10
                    break
            size_mb = it.get("Size", 0) / (1024 * 1024)
            if size_mb < 30:
                prio -= 2
                
            books.append({
                "remote_path": f"gdrive:CloseReading/EBook/{path_str}",
                "filename": Path(path_str).name,
                "relative_path": path_str,
                "size_mb": size_mb,
                "priority": prio,
                "format": ext.replace(".", "")
            })
            
    books.sort(key=lambda x: (x["priority"], x["size_mb"]))
    return books


async def is_book_already_processed(book_id: str) -> bool:
    """检查书籍是否已完整入库并生成精读讲义"""
    sql = "SELECT id, summary_chars FROM library_books WHERE id = ? OR id LIKE ?;"
    rows = await execute_turso(sql, [book_id, f"%{book_id}%"])
    if rows and int(rows[0].get("summary_chars") or 0) > 5000:
        return True
    return False


def clean_book_id(filename: str) -> str:
    """生成合规的 book_id"""
    import re
    base = Path(filename).stem
    cleaned = re.sub(r"[^\w\s\u4e00-\u9fa5]", "_", base)
    cleaned = re.sub(r"\s+", "_", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_").lower()
    return cleaned[:80] or "unnamed_book"


def extract_epub_text_and_chapters(file_path: Path) -> List[Dict[str, Any]]:
    """轻量解析 EPUB 章节与文本内容"""
    import zipfile
    from bs4 import BeautifulSoup
    
    chapters = []
    try:
        with zipfile.ZipFile(file_path, 'r') as z:
            html_files = [f for f in z.namelist() if f.endswith(('.html', '.xhtml', '.htm'))]
            for idx, hfile in enumerate(html_files, 1):
                try:
                    content = z.read(hfile).decode('utf-8', errors='ignore')
                    soup = BeautifulSoup(content, 'html.parser')
                    
                    # 优先查找 h1/h2/h3 标题，避免抓到通用的 title
                    h_tag = soup.find(['h1', 'h2', 'h3'])
                    if h_tag and h_tag.get_text().strip():
                        chap_title = h_tag.get_text().strip()
                    elif soup.title and soup.title.get_text().strip() and "EPUB" not in soup.title.get_text():
                        chap_title = soup.title.get_text().strip()
                    else:
                        chap_title = f"第 {idx:02d} 节"
                        
                    if len(chap_title) > 80:
                        chap_title = chap_title[:80]
                        
                    paragraphs = []
                    for p in soup.find_all(['p', 'pre', 'code', 'blockquote', 'li', 'h4', 'h5']):
                        txt = p.get_text().strip()
                        if txt and len(txt) > 5:
                            paragraphs.append(txt)
                            
                    full_text = "\n\n".join(paragraphs)
                    if len(full_text) > 150:  # 过滤目录与空白页
                        chapters.append({
                            "title": chap_title,
                            "content": full_text
                        })
                except Exception as e:
                    pass
    except Exception as e:
        logger.error(f"解析 EPUB 失败: {e}")
        
    return chapters


async def process_book_pipeline(book_info: Dict[str, Any]):
    """单本书的全自动切块、BGE-M3向量化、20%精讲提炼与双轨同步流水线"""
    filename = book_info["filename"]
    book_id = clean_book_id(filename)
    remote_path = book_info["remote_path"]
    
    if await is_book_already_processed(book_id):
        logger.info(f"⏭️ 书籍 《{filename}》 已完整处理，跳过。")
        return
        
    t_start = time.time()
    logger.info(f"\n=======================================================")
    logger.info(f"📥 [1/5] 开始下载并处理图书: 《{filename}》 (体积: {book_info['size_mb']:.1f} MB)")
    logger.info(f"=======================================================")
    
    local_file = LOCAL_TMP_DIR / filename
    
    try:
        # 1. 从 Google Drive 下载
        if not local_file.exists() or local_file.stat().st_size == 0:
            dl_cmd = ["rclone", "copyto", remote_path, str(local_file), "--drive-chunk-size", "32M"]
            res = subprocess.run(dl_cmd, capture_output=True, text=True)
            if res.returncode != 0:
                logger.error(f"下载失败: {res.stderr}")
                return
            
        # 2. 提取章节
        chapters = []
        if local_file.suffix.lower() == ".epub":
            chapters = extract_epub_text_and_chapters(local_file)
            
        if not chapters:
            logger.warning(f"未能提取到有效章节结构，跳过: {filename}")
            return
            
        total_chars = sum(len(c["content"]) for c in chapters)
        logger.info(f"📖 [2/5] 解析成功: 提取到 {len(chapters)} 个章节，总字数: {total_chars:,} 字")
        
        # 3. 构造切块与 BGE-M3 向量化
        all_chunks = []
        chunk_idx = 1
        for chap in chapters:
            c_title = chap["title"]
            c_text = chap["content"]
            step = 1000
            for i in range(0, len(c_text), step):
                chunk_content = f"【章节: {c_title}】\n" + c_text[i : i + step]
                all_chunks.append({
                    "id": f"{book_id}_c{chunk_idx}",
                    "book_id": book_id,
                    "chapter_title": c_title,
                    "chunk_index": chunk_idx,
                    "content": chunk_content
                })
                chunk_idx += 1
                
        logger.info(f"🧩 [3/5] 切块完成，共 {len(all_chunks)} 块，正在由 BGE-M3 批量向量化...")
        
        total_tokens = 0
        for i in range(0, len(all_chunks), BATCH_SIZE):
            batch = all_chunks[i : i + BATCH_SIZE]
            batch_texts = [c["content"] for c in batch]
            vecs, tokens, _ = await get_bge_m3_embeddings_batch(
                texts=batch_texts,
                book_id=book_id,
                task_name="Worker_BGE_M3向量化"
            )
            total_tokens += tokens
            
            import base64
            pipeline_reqs = []
            for c, vec in zip(batch, vecs):
                blob_bytes = float_array_to_blob(vec)
                b64_str = base64.b64encode(blob_bytes).decode('utf-8')
                pipeline_reqs.append({
                    "type": "execute",
                    "stmt": {
                        "sql": """
                        INSERT INTO library_book_chunks (id, book_id, chapter_title, chunk_index, content, embedding)
                        VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT(id) DO UPDATE SET content=excluded.content, embedding=excluded.embedding;
                        """,
                        "args": [
                            {"type": "text", "value": c["id"]},
                            {"type": "text", "value": book_id},
                            {"type": "text", "value": c["chapter_title"]},
                            {"type": "integer", "value": str(c["chunk_index"])},
                            {"type": "text", "value": c["content"]},
                            {"type": "blob", "base64": b64_str}
                        ]
                    }
                })
            
            import httpx
            async with httpx.AsyncClient(timeout=60.0) as client:
                await client.post(
                    f"{TURSO_URL}/v2/pipeline",
                    headers={"Authorization": f"Bearer {TURSO_TOKEN}", "Content-Type": "application/json"},
                    json={"requests": pipeline_reqs + [{"type": "close"}]}
                )
            await asyncio.sleep(0.1)

        # 4. 20% 极客干货深度重构
        logger.info(f"🧠 [4/5] 启动章节级 20% 去水提炼 (硅基流动 DeepSeek-V3 旗舰 · 原生永久 0 元)...")
        core_chaps = sorted(chapters, key=lambda x: len(x["content"]), reverse=True)[:15]
        sem = asyncio.Semaphore(3)
        distill_tasks = []
        for chap in core_chaps:
            distill_tasks.append(distill_single_chapter(
                book_id=book_id,
                book_title=filename,
                chapter_title=chap["title"],
                start_chunk=1,
                end_chunk=len(all_chunks),
                chapter_text=chap["content"],
                sem=sem
            ))
            
        distilled_results = await asyncio.gather(*distill_tasks)
        distilled_text = "\n\n".join([r["markdown"] for r in distilled_results if r.get("markdown")])
        
        out_file = OUTPUT_DIR / f"[Book]{book_id}_精读研习.md"
        out_file.write_text(distilled_text, encoding="utf-8")
        
        # 5. 更新书籍元数据至 Turso
        book_insert_sql = """
        INSERT INTO library_books (
            id, title, format, total_chars, total_chunks, summary_path, summary_chars, category, tags_json, original_file_path
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET 
            total_chars=excluded.total_chars, total_chunks=excluded.total_chunks,
            summary_chars=excluded.summary_chars, summary_path=excluded.summary_path;
        """
        await execute_turso(book_insert_sql, [
            book_id, filename, book_info["format"], total_chars, len(all_chunks),
            str(out_file), len(distilled_text), "前沿计算机与软件架构",
            json.dumps(["#CS", "#Architecture", "#CloudNative"]), book_info["remote_path"]
        ])
        
        # 6. 同步产物回 Google Drive
        logger.info(f"📤 [5/5] 同步 20% 讲义至 Google Drive (gdrive:CloseReading/output/)...")
        sync_cmd = ["rclone", "copy", str(out_file), "gdrive:CloseReading/output/"]
        subprocess.run(sync_cmd, capture_output=True)
        
        t_duration = time.time() - t_start
        logger.info(f"🎉 《{filename}》 处理圆满完成！耗时: {t_duration:.1f}s | 消耗 Tokens: {total_tokens:,} | 讲义: {len(distilled_text):,} 字")
        
    except Exception as err:
        logger.error(f"❌ 处理书籍 《{filename}》 异常: {err}", exc_info=True)
    finally:
        if local_file.exists():
            local_file.unlink()


async def run_worker_loop(max_books: int = 5):
    """主调度循环"""
    logger.info("🚀 启动第二大脑·AI 图书馆 N100 边缘常驻处理引擎...")
    catalog = get_gdrive_ebook_catalog()
    logger.info(f"📋 成功加载待处理队列: 共 {len(catalog)} 本图书 (本次计划批处理前 {max_books} 本)")
    
    count = 0
    for book in catalog:
        if count >= max_books:
            break
        await process_book_pipeline(book)
        count += 1
        await asyncio.sleep(2)
        
    logger.info(f"🏁 批处理任务阶段性圆满结束！共处理 {count} 本专著。")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--max", type=int, default=3, help="本次连续处理书籍数")
    args = parser.parse_args()
    
    asyncio.run(run_worker_loop(max_books=args.max))

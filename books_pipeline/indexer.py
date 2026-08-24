#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
第二大脑·AI 智能图书馆：书籍向量化切块索引器 (`indexer.py`)
将百万字级电子书（PDF / EPUB）按语义与章节切块，通过 DashScope Embedding 生成 2560 维向量并批量入库 Turso。
"""

import os
import re
import sys
import time
import uuid
import logging
import asyncio
from pathlib import Path
from typing import List, Dict, Any

import httpx

# 路径加载
parent_dir = Path(__file__).resolve().parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))

from config import LibraryConfig
from extractor import extract_book
try:
    from .db import execute_turso, execute_turso_batch, float_array_to_blob, init_library_schema, record_usage
except ImportError:
    from db import execute_turso, execute_turso_batch, float_array_to_blob, init_library_schema, record_usage

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("BookIndexer")

CHUNK_SIZE = 1000       # 每个切块约 1000 字符
CHUNK_OVERLAP = 150     # 重叠 150 字符保持上下文连贯

async def get_embeddings_batch(texts: List[str], book_id: str = "") -> List[List[float]]:
    """批量获取 DashScope text-embedding-v3 向量 (1024 维) 并统计 Token 消耗"""
    url = "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings"
    headers = {
        "Authorization": f"Bearer {LibraryConfig.DASHSCOPE_API_KEY}",
        "Content-Type": "application/json"
    }
    
    embeddings = []
    batch_size = 8
    total_emb_tokens = 0
    t0 = time.time()
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            cleaned_batch = [t.replace("\n", " ").strip()[:2000] for t in batch]
            payload = {
                "model": LibraryConfig.EMBEDDING_MODEL,
                "input": cleaned_batch,
                "dimensions": LibraryConfig.EMBEDDING_DIM
            }
            try:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
                usage = data.get("usage", {})
                total_emb_tokens += usage.get("total_tokens", 0)
                for item in data.get("data", []):
                    embeddings.append(item["embedding"])
            except Exception as e:
                logger.error(f"❌ 批量获取向量失败 ({e}), 正在逐条降级重试...")
                for text in cleaned_batch:
                    single_payload = {
                        "model": LibraryConfig.EMBEDDING_MODEL,
                        "input": text,
                        "dimensions": LibraryConfig.EMBEDDING_DIM
                    }
                    try:
                        single_resp = await client.post(url, headers=headers, json=single_payload)
                        single_resp.raise_for_status()
                        single_data = single_resp.json()
                        total_emb_tokens += single_data.get("usage", {}).get("total_tokens", 0)
                        embeddings.append(single_data["data"][0]["embedding"])
                    except Exception as ex:
                        logger.error(f"单条向量生成失败: {ex}")
                        embeddings.append([0.0] * LibraryConfig.EMBEDDING_DIM)
                        
    if book_id and total_emb_tokens > 0:
        try:
            await record_usage(
                book_id=book_id,
                task_name="向量分块 Embedding (DashScope)",
                provider="DashScope",
                model_name=LibraryConfig.EMBEDDING_MODEL,
                prompt_tokens=total_emb_tokens,
                completion_tokens=0,
                total_tokens=total_emb_tokens,
                duration_seconds=round(time.time() - t0, 2)
            )
        except Exception as err:
            logger.warning(f"记录 Embedding 台账异常: {err}")
            
    return embeddings


def chunk_book_content(book_meta: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    将书籍结构化内容切分成适合 RAG 检索的语义块
    """
    full_text = book_meta.get("text", "")
    chapters = book_meta.get("chapters", [])
    chunks: List[Dict[str, Any]] = []
    
    # 如果有明确章节划分，按章节切块
    if chapters and len(chapters) > 1:
        for ch in chapters:
            ch_title = ch.get("title", "未命名章节")
            ch_text = ch.get("content", "").strip()
            if not ch_text:
                continue
                
            # 滑动窗口切块
            start = 0
            while start < len(ch_text):
                end = min(start + CHUNK_SIZE, len(ch_text))
                chunk_text = ch_text[start:end].strip()
                if len(chunk_text) >= 100:  # 忽略过短的杂质
                    chunks.append({
                        "chapter_title": ch_title,
                        "chunk_index": len(chunks) + 1,
                        "content": f"【章节: {ch_title}】\n{chunk_text}"
                    })
                start += (CHUNK_SIZE - CHUNK_OVERLAP)
                if start >= len(ch_text) - 50:
                    break
    else:
        # 无明确章节时按通用段落滑动切块
        paragraphs = full_text.split("\n\n")
        current_chunk = ""
        current_ch = "全书精选"
        
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            if para.startswith("#"):
                current_ch = para.strip("# ")
                
            if len(current_chunk) + len(para) < CHUNK_SIZE:
                current_chunk += ("\n\n" + para if current_chunk else para)
            else:
                if len(current_chunk) >= 100:
                    chunks.append({
                        "chapter_title": current_ch,
                        "chunk_index": len(chunks) + 1,
                        "content": f"【章节: {current_ch}】\n{current_chunk}"
                    })
                current_chunk = para
                
        if len(current_chunk) >= 100:
            chunks.append({
                "chapter_title": current_ch,
                "chunk_index": len(chunks) + 1,
                "content": f"【章节: {current_ch}】\n{current_chunk}"
            })
            
    return chunks


async def index_single_book(book_file_path: str | Path) -> Dict[str, Any]:
    """
    对单本电子书进行切块、向量化与 Turso 数据库入库
    """
    book_file_path = Path(book_file_path)
    if not book_file_path.exists():
        raise FileNotFoundError(f"文件不存在: {book_file_path}")
        
    logger.info(f"📖 开始提取并切块电子书: {book_file_path.name}")
    book_meta = extract_book(book_file_path)
    
    title = book_meta["title"]
    book_id = re.sub(r"[^a-zA-Z0-9_\u4e00-\u9fa5]", "_", title).strip("_").lower()
    if not book_id:
        book_id = f"book_{uuid.uuid4().hex[:8]}"
        
    chunks = chunk_book_content(book_meta)
    logger.info(f"🧩 切块完成: 全书共切分为 {len(chunks)} 个知识块，准备批量生成 1024 维向量...")
    
    # 批量生成向量 (带台账记录)
    chunk_texts = [c["content"] for c in chunks]
    embeddings = await get_embeddings_batch(chunk_texts, book_id=book_id)
    
    # 写入 Turso library_books 表
    sql_book = """
    INSERT OR REPLACE INTO library_books (id, title, author, format, total_chars, total_chunks)
    VALUES (?, ?, ?, ?, ?, ?);
    """
    await execute_turso(sql_book, [
        book_id,
        title,
        book_meta.get("author", "未知作者"),
        book_meta.get("format", "unknown"),
        book_meta.get("word_count", 0),
        len(chunks)
    ])
    
    # 清理该书旧切块 (如有)
    await execute_turso("DELETE FROM library_book_chunks WHERE book_id = ?;", [book_id])
    
    # 批量入库切块 (每批 25 个，秒级完成并防止网络中断)
    logger.info(f"💾 正在将 {len(chunks)} 个向量切块批量写入 Turso libSQL 数据库...")
    batch_statements = []
    for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
        chunk_id = f"{book_id}_chunk_{i+1:04d}"
        emb_blob = float_array_to_blob(emb)
        sql_chunk = """
        INSERT INTO library_book_chunks (id, book_id, chapter_title, chunk_index, content, embedding)
        VALUES (?, ?, ?, ?, ?, ?);
        """
        batch_statements.append((sql_chunk, [
            chunk_id,
            book_id,
            chunk["chapter_title"],
            chunk["chunk_index"],
            chunk["content"],
            emb_blob
        ]))
        
        if len(batch_statements) >= 25:
            await execute_turso_batch(batch_statements)
            batch_statements = []
            
    if batch_statements:
        await execute_turso_batch(batch_statements)
        
    logger.info(f"🎉 书籍《{title}》全量向量切块入库完成！(ID: {book_id}, 切块数: {len(chunks)})")
    return {
        "book_id": book_id,
        "title": title,
        "total_chunks": len(chunks),
        "total_chars": book_meta.get("word_count", 0)
    }


async def main():
    await init_library_schema()
    
    # 自动检索 downloads 目录下的全部电子书
    books_dir = parent_dir / "downloads/CloseReading"
    if not books_dir.exists():
        logger.warning(f"目录不存在: {books_dir}")
        return
        
    book_files = list(books_dir.glob("*.pdf")) + list(books_dir.glob("*.epub"))
    logger.info(f"📚 发现 {len(book_files)} 本待入库电子书: {[f.name for f in book_files]}")
    
    for book_file in book_files:
        await index_single_book(book_file)


if __name__ == "__main__":
    asyncio.run(main())

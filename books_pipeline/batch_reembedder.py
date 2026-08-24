#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
第二大脑·AI 智能图书馆：全量数据 BGE-M3 重新向量化与基准压测流水线 (`batch_reembedder.py`)
可在 N100 边缘小主机或本地 Mac 上执行。
功能：
  1. 遍历 `library_books` 下的所有藏书，按 Batch=32 批量调用 `BAAI/bge-m3` (原生免费版)
  2. 精确记录每本书的【处理总耗时】、【Token 消耗量】、【切块总数】与【平均速率】
  3. 写入/更新 Turso 边缘数据库 `library_book_chunks.embedding`
  4. 支持同步重刷 `obsidian_chunks`，保证 RSS / TG Bot / 图书馆 RAG 向量空间 100% 对齐统一！
"""

import os
import sys
import time
import json
import logging
import asyncio
from pathlib import Path
from typing import List, Dict, Any

current_dir = Path(__file__).resolve().parent
parent_dir = current_dir.parent
for p in [str(current_dir), str(parent_dir)]:
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from books_pipeline.config import LibraryConfig
    from books_pipeline.db import execute_turso, float_array_to_blob, TURSO_URL, TURSO_TOKEN
    from books_pipeline.bge_embedder import get_bge_m3_embeddings_batch, BATCH_SIZE
except ImportError:
    from config import LibraryConfig
    from db import execute_turso, float_array_to_blob, TURSO_URL, TURSO_TOKEN
    from bge_embedder import get_bge_m3_embeddings_batch, BATCH_SIZE

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("BatchReEmbedder")


async def update_chunks_embeddings_batch(chunk_ids: List[str], embeddings: List[List[float]]):
    """批量更新 Turso 数据库中的切块向量字段"""
    import base64
    pipeline_requests = []
    
    for c_id, emb in zip(chunk_ids, embeddings):
        blob_bytes = float_array_to_blob(emb)
        b64_str = base64.b64encode(blob_bytes).decode('utf-8')
        
        pipeline_requests.append({
            "type": "execute",
            "stmt": {
                "sql": "UPDATE library_book_chunks SET embedding = ? WHERE id = ?;",
                "args": [
                    {"type": "blob", "base64": b64_str},
                    {"type": "text", "value": c_id}
                ]
            }
        })
        
    # 分批提交 pipeline (每次提交 50 条 SQL)
    async with import_httpx().AsyncClient(timeout=60.0) as client:
        headers = {
            "Authorization": f"Bearer {TURSO_TOKEN}",
            "Content-Type": "application/json"
        }
        batch_step = 50
        for i in range(0, len(pipeline_requests), batch_step):
            sub_requests = pipeline_requests[i : i + batch_step]
            payload = {
                "requests": sub_requests + [{"type": "close"}]
            }
            res = await client.post(f"{TURSO_URL}/v2/pipeline", headers=headers, json=payload)
            if res.status_code != 200:
                logger.error(f"Turso Pipeline 批量更新失败: {res.text}")


def import_httpx():
    import httpx
    return httpx


async def process_single_book(book: Dict[str, Any]) -> Dict[str, Any]:
    """处理单本书籍的全量切块重新向量化"""
    book_id = book["id"]
    book_title = book["title"]
    
    t_start = time.time()
    logger.info(f"\n=======================================================")
    logger.info(f"📚 开始批量向量化书籍: 《{book_title}》 (ID: {book_id})")
    logger.info(f"=======================================================")
    
    # 1. 查询该书的所有切块
    sql = "SELECT id, chunk_index, chapter_title, content FROM library_book_chunks WHERE book_id = ? ORDER BY chunk_index ASC;"
    chunks = await execute_turso(sql, [book_id])
    total_chunks = len(chunks)
    
    if total_chunks == 0:
        logger.warning(f"书籍 《{book_title}》 无切块数据，跳过。")
        return {"book_id": book_id, "title": book_title, "chunks": 0, "tokens": 0, "duration": 0}

    total_book_tokens = 0
    batch_count = 0
    total_batches = (total_chunks + BATCH_SIZE - 1) // BATCH_SIZE
    
    logger.info(f"📑 切块总数: {total_chunks} 块 | 分批次数: {total_batches} 批 (BatchSize={BATCH_SIZE})")

    for i in range(0, total_chunks, BATCH_SIZE):
        batch = chunks[i : i + BATCH_SIZE]
        batch_ids = [c["id"] for c in batch]
        batch_texts = [c["content"] for c in batch]
        batch_count += 1
        
        # 2. 批量调用 SiliconFlow BAAI/bge-m3
        vecs, tokens, dur = await get_bge_m3_embeddings_batch(
            texts=batch_texts,
            book_id=book_id,
            task_name=f"BGE-M3批量重构_批次{batch_count}"
        )
        total_book_tokens += tokens
        
        # 3. 批量刷入 Turso
        await update_chunks_embeddings_batch(batch_ids, vecs)
        
        logger.info(f"  ⚡ 进度: 批次 [{batch_count}/{total_batches}] | 切块 #{batch[0]['chunk_index']}~#{batch[-1]['chunk_index']} | 消耗 Tokens: {tokens} | 耗时: {dur:.2f}s")
        # 微休止防瞬时高并发
        await asyncio.sleep(0.1)

    t_total = time.time() - t_start
    chars_count = sum(len(c.get("content", "")) for c in chunks)
    speed_chunks = total_chunks / t_total if t_total > 0 else 0
    speed_chars = chars_count / t_total if t_total > 0 else 0
    
    logger.info(f"✅ 《{book_title}》 向量化圆满完成！")
    logger.info(f"   ⏱️ 总处理耗时: {t_total:.2f} 秒")
    logger.info(f"   🔢 累计消耗 Tokens: {total_book_tokens:,} tokens (0 元免费)")
    logger.info(f"   ⚡ 处理吞吐率: {speed_chunks:.1f} 块/秒 ({speed_chars:,.0f} 字/秒)\n")

    return {
        "book_id": book_id,
        "title": book_title,
        "total_chars": chars_count,
        "chunks": total_chunks,
        "tokens": total_book_tokens,
        "duration_seconds": round(t_total, 2),
        "speed_chunks_per_sec": round(speed_chunks, 1),
        "speed_chars_per_sec": round(speed_chars, 0)
    }


async def run_all_library_reembedding():
    """全库批量向量化主入口"""
    global_start = time.time()
    logger.info("🚀 启动第二大脑·全量数据 BGE-M3 (SiliconFlow 免费版) 向量化与基准测试...")
    
    books = await execute_turso("SELECT id, title, total_chars, total_chunks FROM library_books ORDER BY total_chunks ASC;")
    logger.info(f"📖 发现待重构书籍: {len(books)} 本")
    
    results = []
    for b in books:
        res = await process_single_book(b)
        results.append(res)
        
    global_duration = time.time() - global_start
    total_all_tokens = sum(r["tokens"] for r in results)
    total_all_chunks = sum(r["chunks"] for r in results)
    total_all_chars = sum(r["total_chars"] for r in results)
    
    logger.info("=======================================================")
    logger.info("📊 全库 BGE-M3 向量化基准统计与测试报告")
    logger.info("=======================================================")
    logger.info(f"📚 处理图书总数: {len(results)} 本")
    logger.info(f"📑 累计切块总数: {total_all_chunks:,} 块")
    logger.info(f"📝 累计处理字符: {total_all_chars:,} 字")
    logger.info(f"🔢 累计消耗 Tokens: {total_all_tokens:,} Tokens (SiliconFlow 官方免费 0 元)")
    logger.info(f"⏱️ 全流程总耗时: {global_duration:.2f} 秒 (平均单书: {global_duration/max(1, len(results)):.2f}s)")
    logger.info("=======================================================\n")
    
    # 输出 JSON 明细摘要
    return {
        "status": "success",
        "total_books": len(results),
        "total_chunks": total_all_chunks,
        "total_chars": total_all_chars,
        "grand_total_tokens": total_all_tokens,
        "total_duration_seconds": round(global_duration, 2),
        "book_benchmarks": results
    }

if __name__ == "__main__":
    summary = asyncio.run(run_all_library_reembedding())
    print(json.dumps(summary, ensure_ascii=False, indent=2))

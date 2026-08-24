#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
第二大脑·Obsidian / TG / RSS 笔记全量 BGE-M3 向量对齐流水线 (`reembed_obsidian.py`)
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

from db import execute_turso, float_array_to_blob, TURSO_URL, TURSO_TOKEN
from bge_embedder import get_bge_m3_embeddings_batch, BATCH_SIZE

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("ObsidianReEmbedder")


async def update_obsidian_embeddings_batch(chunk_ids: List[str], embeddings: List[List[float]]):
    import base64
    import httpx
    pipeline_requests = []
    
    for c_id, emb in zip(chunk_ids, embeddings):
        blob_bytes = float_array_to_blob(emb)
        b64_str = base64.b64encode(blob_bytes).decode('utf-8')
        
        pipeline_requests.append({
            "type": "execute",
            "stmt": {
                "sql": "UPDATE obsidian_chunks SET embedding = ? WHERE chunk_id = ?;",
                "args": [
                    {"type": "blob", "base64": b64_str},
                    {"type": "text", "value": c_id}
                ]
            }
        })
        
    async with httpx.AsyncClient(timeout=60.0) as client:
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


async def run_obsidian_reembedding():
    t_start = time.time()
    logger.info("🚀 启动 Obsidian / RSS / TG Bot 笔记全量 BGE-M3 向量空间对齐...")
    
    sql = "SELECT chunk_id, doc_title, content FROM obsidian_chunks ORDER BY chunk_id ASC;"
    chunks = await execute_turso(sql)
    total_chunks = len(chunks)
    logger.info(f"📑 发现 Obsidian 笔记切块: {total_chunks:,} 块")
    
    total_tokens = 0
    total_batches = (total_chunks + BATCH_SIZE - 1) // BATCH_SIZE
    
    for i in range(0, total_chunks, BATCH_SIZE):
        batch = chunks[i : i + BATCH_SIZE]
        batch_ids = [c["chunk_id"] for c in batch]
        batch_texts = [c["content"] for c in batch]
        batch_idx = (i // BATCH_SIZE) + 1
        
        vecs, tokens, dur = await get_bge_m3_embeddings_batch(
            texts=batch_texts,
            book_id="obsidian_notes",
            task_name=f"Obsidian_BGE_M3_批次{batch_idx}"
        )
        total_tokens += tokens
        await update_obsidian_embeddings_batch(batch_ids, vecs)
        
        if batch_idx % 10 == 0 or batch_idx == total_batches:
            logger.info(f"  ⚡ 进度: [{batch_idx}/{total_batches}] ({i+len(batch)}/{total_chunks}) | 消耗 Tokens: {tokens} | 耗时: {dur:.2f}s")
        await asyncio.sleep(0.1)

    t_total = time.time() - t_start
    speed = total_chunks / t_total if t_total > 0 else 0
    
    logger.info(f"=======================================================")
    logger.info(f"✅ Obsidian / RSS / TG 笔记 BGE-M3 向量对齐圆满完成！")
    logger.info(f"   📑 累计切块: {total_chunks:,} 块")
    logger.info(f"   🔢 累计消耗 Tokens: {total_tokens:,} tokens (0 元免费)")
    logger.info(f"   ⏱️ 总处理耗时: {t_total:.2f} 秒 (吞吐率: {speed:.1f} 块/秒)")
    logger.info(f"=======================================================")

if __name__ == "__main__":
    asyncio.run(run_obsidian_reembedding())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
第二大脑·AI 智能图书馆 BGE-M3 向量与 Reranker 引擎 (`bge_embedder.py`)
特性：
  1. 选用 SiliconFlow 原生免费版 `BAAI/bge-m3`（1024 维，永久免费，严禁使用 Pro/ 前缀付费版）
  2. 配套免费重排模型 `BAAI/bge-reranker-v2-m3`（两阶段高精度 RAG）
  3. 支持 Batching 批量请求（batch_size=32），单书只需十余次 API 调用
  4. 严格统计 Token 消耗与网络耗时，落库 Turso 台账 (`library_usage_ledger`)
"""

import os
import sys
import time
import json
import logging
import asyncio
from pathlib import Path
from typing import List, Dict, Any, Tuple
import httpx

current_dir = Path(__file__).resolve().parent
parent_dir = current_dir.parent
for p in [str(current_dir), str(parent_dir)]:
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from books_pipeline.config import LibraryConfig
    from books_pipeline.db import execute_turso, record_usage, float_array_to_blob
except ImportError:
    from config import LibraryConfig
    from db import execute_turso, record_usage, float_array_to_blob

logger = logging.getLogger("BGEEmbedder")

# 硅基流动统一配置
SILICONFLOW_API_KEY = os.getenv(
    "SILICONFLOW_API_KEY",
    "sk-wewpjlyfvwflfcqivobyumvhybqldextibizkxtkmajkkqvs"
)
SILICONFLOW_EMBEDDING_URL = "https://api.siliconflow.cn/v1/embeddings"
SILICONFLOW_RERANK_URL = "https://api.siliconflow.cn/v1/rerank"

# 必须使用原生免费版本（绝不带 Pro/ 前缀）
BGE_EMBEDDING_MODEL = "BAAI/bge-m3"
BGE_RERANK_MODEL = "BAAI/bge-reranker-v2-m3"

BATCH_SIZE = 32  # 单次批量切块数


async def get_bge_m3_embeddings_batch(
    texts: List[str],
    book_id: str = "general",
    task_name: str = "BGE_M3_批量切块向量化",
    max_retries: int = 3
) -> Tuple[List[List[float]], int, float]:
    """
    批量调用 BAAI/bge-m3 (原生免费版) 获取 1024 维密集向量
    返回: (向量列表, 消耗Tokens, 耗时秒数)
    """
    headers = {
        "Authorization": f"Bearer {SILICONFLOW_API_KEY}",
        "Content-Type": "application/json"
    }
    
    cleaned_texts = [t.strip() if t and t.strip() else " " for t in texts]
    payload = {
        "model": BGE_EMBEDDING_MODEL,
        "input": cleaned_texts
    }

    t0 = time.time()
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                res = await client.post(SILICONFLOW_EMBEDDING_URL, headers=headers, json=payload)
                duration = time.time() - t0
                
                if res.status_code == 200:
                    data = res.json()
                    raw_items = data.get("data", [])
                    raw_items.sort(key=lambda x: x.get("index", 0))
                    embeddings = [item["embedding"] for item in raw_items]
                    
                    usage = data.get("usage", {})
                    prompt_tokens = usage.get("prompt_tokens", 0)
                    total_tokens = usage.get("total_tokens", prompt_tokens)
                    
                    try:
                        await record_usage(
                            book_id=book_id,
                            task_name=task_name,
                            provider="SiliconFlow",
                            model_name=BGE_EMBEDDING_MODEL,
                            prompt_tokens=prompt_tokens,
                            completion_tokens=0,
                            total_tokens=total_tokens,
                            duration_seconds=duration,
                            cost_cny=0.0  # 官方免费 0 元
                        )
                    except Exception as db_err:
                        logger.warning(f"台账记录跳过: {db_err}")
                        
                    return embeddings, total_tokens, duration
                elif res.status_code == 429:
                    wait_time = (attempt + 1) * 2
                    logger.warning(f"触发频控 (429)，等待 {wait_time}s 重试...")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"SiliconFlow 请求失败 [{res.status_code}]: {res.text}")
                    if attempt == max_retries - 1:
                        res.raise_for_status()
                    await asyncio.sleep(1)
        except Exception as e:
            logger.warning(f"请求异常 (尝试 {attempt+1}/{max_retries}): {e}")
            if attempt == max_retries - 1:
                raise e
            await asyncio.sleep(1.5)
            
    raise RuntimeError("重试次数耗尽，批量向量化失败")


async def get_single_bge_m3_embedding(text: str, book_id: str = "general") -> List[float]:
    """单文本向量化（用于用户提问检索）"""
    vectors, _, _ = await get_bge_m3_embeddings_batch([text], book_id=book_id, task_name="检索问答向量化")
    return vectors[0] if vectors else []


async def rerank_documents(
    query: str,
    documents: List[str],
    top_n: int = 5,
    max_retries: int = 3
) -> List[Dict[str, Any]]:
    """
    调用免费重排模型 `BAAI/bge-reranker-v2-m3` 对初筛召回文档进行高精度重排序
    """
    headers = {
        "Authorization": f"Bearer {SILICONFLOW_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": BGE_RERANK_MODEL,
        "query": query,
        "documents": documents,
        "top_n": top_n
    }

    t0 = time.time()
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                res = await client.post(SILICONFLOW_RERANK_URL, headers=headers, json=payload)
                if res.status_code == 200:
                    data = res.json()
                    results = data.get("results", [])
                    return results
                elif res.status_code == 429:
                    await asyncio.sleep((attempt + 1) * 2)
                else:
                    logger.error(f"Rerank 失败 [{res.status_code}]: {res.text}")
                    if attempt == max_retries - 1:
                        res.raise_for_status()
                    await asyncio.sleep(1)
        except Exception as e:
            if attempt == max_retries - 1:
                logger.warning(f"Rerank 异常跳过: {e}")
                return [{"index": i, "relevance_score": 1.0} for i in range(min(top_n, len(documents)))]
            await asyncio.sleep(1)
            
    return [{"index": i, "relevance_score": 1.0} for i in range(min(top_n, len(documents)))]

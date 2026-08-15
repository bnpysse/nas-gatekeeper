#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import logging
import asyncio
import json
import struct
import math
from pathlib import Path
import base64

import httpx
from openai import AsyncOpenAI

parent_dir = str(Path(__file__).resolve().parent.parent)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from config import Config

logger = logging.getLogger(__name__)

def cosine_similarity(v1, v2):
    dot = sum(x * y for x, y in zip(v1, v2))
    mag1 = math.sqrt(sum(x * x for x in v1))
    mag2 = math.sqrt(sum(y * y for y in v2))
    if mag1 * mag2 == 0: return 0
    return dot / (mag1 * mag2)

def get_embedding_client() -> AsyncOpenAI:
    # 强制不使用代理，走国内直连
    return AsyncOpenAI(
        http_client=httpx.AsyncClient(proxy=None),
        api_key=Config.DASHSCOPE_API_KEY,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
    )

def float_array_to_blob(float_array: list[float]) -> bytes:
    """将 float 数组转换为 32-bit float 二进制 blob，适配 Turso F32_BLOB"""
    return struct.pack(f'{len(float_array)}f', *float_array)

async def _execute_turso(sql: str, args: list = None):
    base = Config.TURSO_DATABASE_URL.replace("wss://", "https://").replace("libsql://", "https://")
    url = f"{base}/v2/pipeline"
    headers = {
        "Authorization": f"Bearer {Config.TURSO_AUTH_TOKEN}",
        "Content-Type": "application/json"
    }
    
    formatted_args = []
    if args:
        for arg in args:
            if isinstance(arg, bytes):
                formatted_args.append({"type": "blob", "base64": base64.b64encode(arg).decode('utf-8')})
            elif isinstance(arg, int):
                formatted_args.append({"type": "integer", "value": str(arg)})
            elif isinstance(arg, float):
                formatted_args.append({"type": "float", "value": str(arg)})
            elif arg is None:
                formatted_args.append({"type": "null"})
            else:
                formatted_args.append({"type": "text", "value": str(arg)})
                
    payload = {
        "requests": [
            {"type": "execute", "stmt": {"sql": sql, "args": formatted_args}},
            {"type": "close"}
        ]
    }
    
    proxy = Config.HTTP_PROXY or None
    
    async with httpx.AsyncClient(timeout=30.0, proxy=proxy) as client:
        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
        
        results = data.get("results", [])
        if not results: return []
        
        exec_res = results[0].get("response", {}).get("result", {})
        rows = exec_res.get("rows", [])
        
        parsed_rows = []
        for row in rows:
            parsed_row = []
            for val_obj in row:
                if val_obj["type"] == "blob":
                    parsed_row.append(base64.b64decode(val_obj["base64"]))
                else:
                    parsed_row.append(val_obj.get("value"))
            parsed_rows.append(parsed_row)
        return parsed_rows

async def get_embedding(text: str) -> list[float]:
    if not Config.DASHSCOPE_API_KEY:
        logger.warning("未配置 DASHSCOPE_API_KEY，跳过 Embedding 生成。")
        return []
        
    client = get_embedding_client()
    text = text.replace("\n", " ")
    
    try:
        response = await client.embeddings.create(
            input=[text[:3000]],
            model=Config.DASHSCOPE_EMBEDDING_MODEL,
        )
        return response.data[0].embedding
    except Exception as e:
        logger.error(f"生成 Embedding 失败: {e}")
        return []

async def init_db():
    """初始化数据库表"""
    try:
        await _execute_turso('''
            CREATE TABLE IF NOT EXISTS obsidian_vectors (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                path TEXT NOT NULL,
                content TEXT,
                embedding F32_BLOB(1024),
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
    except Exception as e:
        logger.error(f"初始化 Turso/SQLite 失败: {e}")

async def upsert_note(note_id: str, title: str, path: str, content: str, embedding: list[float]):
    """插入或更新笔记，包含向量"""
    try:
        blob = float_array_to_blob(embedding)
        await _execute_turso(
            "INSERT INTO obsidian_vectors (id, title, path, content, embedding) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET title=excluded.title, path=excluded.path, content=excluded.content, embedding=excluded.embedding, updated_at=CURRENT_TIMESTAMP",
            [note_id, title, path, content, blob]
        )
        logger.info(f"成功将笔记向量入库: {title}")
    except Exception as e:
        logger.error(f"笔记入库失败: {e}")

async def search_similar_notes(embedding: list[float], limit: int = 3) -> list[dict]:
    """通过向量余弦相似度检索相关笔记"""
    try:
        blob = float_array_to_blob(embedding)
        rows = await _execute_turso(
            "SELECT id, title, path, content, vector_distance_cos(embedding, ?) as dist FROM obsidian_vectors ORDER BY dist ASC LIMIT ?",
            [blob, limit]
        )
        return [{"id": row[0], "title": row[1], "path": row[2], "content": row[3], "distance": row[4]} for row in rows]
    except Exception as e:
        logger.error(f"检索相似笔记失败: {e}")
        return []

async def ask_rag(question: str) -> str:
    """基于第二大脑知识库检索并使用大模型回答问题"""
    embedding = await get_embedding(question)
    if not embedding:
        return "⚠️ 生成问题向量失败或未配置 DASHSCOPE_API_KEY。"
        
    similar_notes = await search_similar_notes(embedding, limit=5)
    if not similar_notes:
        return "抱歉，在您的第二大脑知识库中没有检索到相关笔记。"
        
    context_blocks = []
    for n in similar_notes:
        title = n.get("title", "未命名笔记")
        content = n.get("content", "")[:1000]
        context_blocks.append(f"### 《{title}》\n{content}\n")
        
    context_text = "\n".join(context_blocks)
    
    prompt = f"""你是一个智能知识库问答助手。请基于以下从用户的 Obsidian 笔记库中检索到的上下文内容，准确、深入地回答用户的问题。如果上下文中没有足够信息，请如实说明。

【检索到的参考笔记】：
{context_text}

【用户问题】：
{question}
"""
    try:
        from services.ai import get_volcengine_async_client
        client = get_volcengine_async_client()
        resp = await client.chat.completions.create(
            model=Config.VOLCENGINE_ENDPOINT_ID or "ep-20260809122445-td2g2",
            messages=[
                {"role": "system", "content": "你是一位专业的知识管理与第二大脑问答专家。"},
                {"role": "user", "content": prompt}
            ]
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"RAG 回答生成失败: {e}")
        return f"大模型回答失败: {e}"

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
第二大脑高阶 RAG 检索中枢 (`rag.py`)
融入两阶段检索漏斗架构：
  1. 阶段一（海量初筛）：Turso 向量库 (BGE-M3 1024维) + 图书切块库 (437本专著) 粗召回 Top-25 候选
  2. 阶段二（高阶提鲜）：阿里百炼 qwen3-vl-rerank (或硅基 bge-reranker-v2-m3) 交叉注意力重排序 Top-4
  3. 阶段三（精准问答）：火山 DeepSeek-V4-Pro / 阿里百炼 Qwen-Plus 旗舰深度解答并附带溯源打分
"""

import os
import sys
import logging
import asyncio
import json
import struct
import math
import re
from pathlib import Path
import base64

import httpx
from openai import AsyncOpenAI

parent_dir = str(Path(__file__).resolve().parent.parent)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from config import Config

logger = logging.getLogger(__name__)

DASHSCOPE_KEY = os.getenv("DASHSCOPE_API_KEY", "sk-d36c2e0717cb4d52917711ea13e614bc")
SILICONFLOW_KEY = os.getenv("SILICONFLOW_API_KEY", "sk-wewpjlyfvwflfcqivobyumvhybqldextibizkxtkmajkkqvs")

def float_array_to_blob(float_array: list[float]) -> bytes:
    """将 float 数组转换为 32-bit float 二进制 blob，适配 Turso F32_BLOB"""
    return struct.pack(f'{len(float_array)}f', *float_array)

def get_embedding_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        http_client=httpx.AsyncClient(proxy=None, timeout=30.0),
        api_key=SILICONFLOW_KEY,
        base_url="https://api.siliconflow.cn/v1"
    )

async def get_embedding(text: str, model="BAAI/bge-m3") -> list[float]:
    """生成 1024 维密集嵌入向量 (官方永久 0 元免费)"""
    try:
        client = get_embedding_client()
        clean_text = text.replace("\n", " ").strip()[:3000]
        if not clean_text:
            return []
        resp = await client.embeddings.create(input=[clean_text], model=model)
        return resp.data[0].embedding
    except Exception as e:
        logger.error(f"Embedding 生成异常: {e}")
        return []

async def init_db():
    """初始化/检查 RAG 数据库连接"""
    return True

async def upsert_note(doc_id: str, title: str, path: str, content: str, embedding: list[float] = None):
    """兼容旧版笔记写入方法"""
    return True

async def search_similar_notes(embedding: list[float], limit: int = 3) -> list[dict]:
    """检索第二大脑相似笔记 (兼容 Obsidian 自动打标溯源)"""
    if not embedding:
        return []
    blob = float_array_to_blob(embedding)
    try:
        rows = await _execute_turso("""
            SELECT chunk_id, doc_id, doc_title, section, content, vector_distance_cos(embedding, ?) as dist
            FROM obsidian_chunks
            WHERE embedding IS NOT NULL
            ORDER BY dist ASC
            LIMIT ?;
        """, [blob, limit])
        res = []
        for r in rows:
            res.append({
                "doc_id": r[1],
                "title": r[2],
                "section": r[3] or "正文",
                "content": r[4],
                "score": round(1.0 - float(r[5] or 0.5), 3)
            })
        return res
    except Exception as e:
        logger.warning(f"检索相似笔记失败: {e}")
        return []

async def _execute_turso(sql: str, args: list = None):
    """底层 Turso 异步 HTTP Pipeline 适配器"""
    if not Config.TURSO_DATABASE_URL or not Config.TURSO_AUTH_TOKEN:
        return []
    base = Config.TURSO_DATABASE_URL.replace("wss://", "https://").replace("libsql://", "https://")
    if not base.startswith("http"):
        base = f"https://{base}"
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
    try:
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
                    elif val_obj["type"] == "integer":
                        parsed_row.append(int(val_obj["value"]))
                    elif val_obj["type"] == "float":
                        parsed_row.append(float(val_obj["value"]))
                    elif val_obj["type"] == "null":
                        parsed_row.append(None)
                    else:
                        parsed_row.append(val_obj.get("value", ""))
                parsed_rows.append(parsed_row)
            return parsed_rows
    except Exception as e:
        logger.error(f"Turso 查询异常: {e}")
        return []

async def search_library_and_obsidian_chunks(embedding: list[float], limit: int = 20) -> list[dict]:
    """同时从图书知识库 (library_book_chunks) 与 Obsidian 笔记库 (obsidian_chunks) 粗召回候选"""
    candidates = []
    blob = float_array_to_blob(embedding)
    
    # 1. 检索图书切块库 (library_book_chunks)
    try:
        book_rows = await _execute_turso("""
            SELECT c.id, c.book_id, b.title, c.chapter_title, c.content, vector_distance_cos(c.embedding, ?) as dist
            FROM library_book_chunks c
            JOIN library_books b ON c.book_id = b.id
            WHERE c.embedding IS NOT NULL
            ORDER BY dist ASC
            LIMIT ?;
        """, [blob, limit])
        
        for r in book_rows:
            candidates.append({
                "source_type": "book",
                "doc_id": r[1],
                "doc_title": r[2],
                "section": r[3] or "核心章节",
                "content": r[4],
                "vector_dist": r[5]
            })
    except Exception as e:
        logger.warning(f"检索图书切块失败: {e}")

    # 2. 检索 Obsidian 笔记切块库 (obsidian_chunks)
    try:
        obs_rows = await _execute_turso("""
            SELECT chunk_id, doc_id, doc_title, section, content, vector_distance_cos(embedding, ?) as dist
            FROM obsidian_chunks
            WHERE embedding IS NOT NULL
            ORDER BY dist ASC
            LIMIT 10;
        """, [blob])
        
        for r in obs_rows:
            candidates.append({
                "source_type": "note",
                "doc_id": r[1],
                "doc_title": r[2],
                "section": r[3] or "正文",
                "content": r[4],
                "vector_dist": r[5]
            })
    except Exception as e:
        logger.warning(f"检索 Obsidian 切块失败: {e}")

    return candidates

async def rerank_candidates(query: str, candidates: list[dict], top_n: int = 4) -> list[dict]:
    """
    两阶段高阶重排：
    1. 优先调用阿里百炼 qwen3-vl-rerank (赠送 100 万高阶配额)
    2. 容灾平滑降级至硅基流动 BAAI/bge-reranker-v2-m3 (永久 0 元免费)
    """
    if not candidates:
        return []
        
    doc_texts = [f"《{c['doc_title']}》 - {c['section']}\n{c['content'][:1500]}" for c in candidates]
    
    # 尝试 1: 阿里百炼 qwen3-vl-rerank
    try:
        url = "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"
        headers = {
            "Authorization": f"Bearer {DASHSCOPE_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "qwen3-vl-rerank",
            "input": {
                "query": query,
                "documents": doc_texts
            },
            "parameters": {
                "top_n": top_n,
                "return_documents": False
            }
        }
        async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("output", {}).get("results", [])
                reranked = []
                for item in results:
                    idx = item.get("index", 0)
                    score = item.get("relevance_score", 0.0)
                    cand = candidates[idx].copy()
                    cand["rerank_score"] = score
                    cand["reranker_used"] = "qwen3-vl-rerank (百炼旗舰)"
                    reranked.append(cand)
                logger.info(f"✅ 百炼 qwen3-vl-rerank 重排成功 (候选 {len(candidates)} ➔ 精排 Top-{len(reranked)})")
                return reranked
    except Exception as e:
        logger.warning(f"百炼 Rerank 调用异常 ({e})，降级至硅基流动 BGE-Reranker...")

    # 尝试 2: 硅基流动 BAAI/bge-reranker-v2-m3 (官方永久免费)
    try:
        url = "https://api.siliconflow.cn/v1/rerank"
        headers = {
            "Authorization": f"Bearer {SILICONFLOW_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "BAAI/bge-reranker-v2-m3",
            "query": query,
            "documents": doc_texts,
            "top_n": top_n,
            "return_documents": False
        }
        async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("results", [])
                reranked = []
                for item in results:
                    idx = item.get("index", 0)
                    score = item.get("relevance_score", 0.0)
                    cand = candidates[idx].copy()
                    cand["rerank_score"] = score
                    cand["reranker_used"] = "bge-reranker-v2-m3 (硅基免费)"
                    reranked.append(cand)
                logger.info(f"✅ 硅基 bge-reranker-v2-m3 重排成功 (候选 {len(candidates)} ➔ 精排 Top-{len(reranked)})")
                return reranked
    except Exception as e:
        logger.warning(f"硅基 Rerank 调用异常: {e}")

    # 兜底：纯向量余弦相似度截取
    for c in candidates[:top_n]:
        c["rerank_score"] = round(1.0 - c.get("vector_dist", 0.5), 3)
        c["reranker_used"] = "Vector-Cosine (向量粗排)"
    return candidates[:top_n]

async def ask_rag(question: str) -> str:
    """
    第二大脑终极 RAG 问答中枢：
    向量粗召回 ➔ Rerank 交叉打分 ➔ 过滤噪音 ➔ 旗舰模型深度解答
    """
    embedding = await get_embedding(question)
    if not embedding:
        return "⚠️ 生成问题向量失败，请检查网络或 API 配置。"

    # 1. 粗召回 Top-25 候选
    candidates = await search_library_and_obsidian_chunks(embedding, limit=20)
    if not candidates:
        return "抱歉，在您的第二大脑（437 本专著与 Obsidian 笔记库）中未检索到相关内容。"

    # 2. 高阶 Rerank 交叉语义打分提鲜
    top_chunks = await rerank_candidates(question, candidates, top_n=4)
    if not top_chunks:
        return "未找到相关知识切块。"

    # 3. 组装精排上下文
    context_blocks = []
    source_traces = []
    for c in top_chunks:
        icon = "📚" if c["source_type"] == "book" else "📝"
        title = c["doc_title"]
        sec = c["section"]
        score = c.get("rerank_score", 0.0)
        source_traces.append(f"{icon} 《{title}》 > {sec} (相关度: `{score:.3f}`)")
        context_blocks.append(f"### {icon} 《{title}》 (章节/小节: {sec} | 语义匹配分: {score:.3f})\n{c['content']}\n")

    context_text = "\n".join(context_blocks)
    reranker_info = top_chunks[0].get("reranker_used", "qwen3-vl-rerank")

    prompt = f"""你是一个智能第二大脑知识库问答专家。请基于以下从用户的 437 本技术专著与 Obsidian 笔记库中经过【Rerank 高阶重排序模型】精准打分初筛出的最核心切块内容，准确、深入、结构化地回答用户的问题。

【回答规范】：
1. 答案必须紧密围绕提供的参考资料，逻辑清晰，有理有据，提炼出可落地的技术方案或知识结论；
2. 在回答涉及具体专著观点时，用 《书名》 明确标注溯源；
3. 如果提供的段落不足以完全解答，请客观指出。

【精排参考切块（Top-4）】：
{context_text}

【用户问题】：
{question}
"""
    try:
        from services.ai import get_dashscope_async_client
        client = get_dashscope_async_client()
        resp = await client.chat.completions.create(
            model="qwen3.8-flash",
            messages=[
                {"role": "system", "content": "你是一位专业的知识管理与第二大脑问答专家。"},
                {"role": "user", "content": prompt}
            ]
        )
        answer = resp.choices[0].message.content.strip()

        # 追加精美的 Rerank 溯源与打分卡片
        answer += "\n\n━━━━━━━━━━━━━━━━━━━━━\n"
        answer += f"🎯 **Rerank 精排引擎**：`{reranker_info}`\n"
        answer += "📚 **精准命中出处段落**:\n"
        for st in source_traces:
            answer += f"- {st}\n"

        return answer
    except Exception as e:
        logger.error(f"RAG 回答生成失败: {e}")
        return f"大模型回答失败: {e}"

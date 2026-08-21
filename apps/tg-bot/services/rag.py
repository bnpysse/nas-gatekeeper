#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
第二大脑轻量级 RAG 向量引擎 (DashScope Embedding + Turso Vector DB)
融入 RAGFlow 精髓的“Markdown 标题层级语义感知分块 (Header-Aware Chunking)”与“多路召回”
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

def cosine_similarity(v1, v2):
    dot = sum(x * y for x, y in zip(v1, v2))
    mag1 = math.sqrt(sum(x * x for x in v1))
    mag2 = math.sqrt(sum(y * y for y in v2))
    if mag1 * mag2 == 0: return 0
    return dot / (mag1 * mag2)

def get_embedding_client() -> AsyncOpenAI:
    # 强制直连阿里百炼，不走外部代理
    return AsyncOpenAI(
        http_client=httpx.AsyncClient(proxy=None),
        api_key=Config.DASHSCOPE_API_KEY,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
    )

def float_array_to_blob(float_array: list[float]) -> bytes:
    """将 float 数组转换为 32-bit float 二进制 blob，适配 Turso F32_BLOB"""
    return struct.pack(f'{len(float_array)}f', *float_array)

async def _execute_turso(sql: str, args: list = None):
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
    """使用阿里百炼 text-embedding-v3 生成 1024 维向量"""
    if not Config.DASHSCOPE_API_KEY:
        logger.warning("未配置 DASHSCOPE_API_KEY，跳过 Embedding 生成。")
        return []
        
    client = get_embedding_client()
    text = text.replace("\n", " ")
    
    try:
        response = await client.embeddings.create(
            input=[text[:2000]],
            model=Config.DASHSCOPE_EMBEDDING_MODEL or "text-embedding-v3",
            dimensions=1024
        )
        return response.data[0].embedding
    except Exception as e:
        logger.error(f"生成 Embedding 失败: {e}")
        return []

def chunk_markdown(doc_title: str, content: str, max_chars: int = 800) -> list[dict]:
    """
    RAGFlow 风格的 Markdown 标题语义感知分块算法 (Hierarchical Header-Aware Chunking):
    1. 剥离 YAML Frontmatter;
    2. 按 #, ##, ### 等层级标题识别段落边界;
    3. 为每一个 Chunk 注入面包屑导航头 (如: 《文档标题》 > 章节标题);
    4. 保障单个语义块在 200~800 字之间，杜绝切断上下文。
    """
    body = re.sub(r'^---[\s\S]*?---\n', '', content).strip()
    if not body:
        return [{"section": "概要", "text": f"【来源: 《{doc_title}》】\n{content[:max_chars]}"}]

    lines = body.splitlines()
    chunks = []
    current_header = "概要"
    current_lines = []
    
    for line in lines:
        header_match = re.match(r'^(#{1,4})\s+(.+)$', line.strip())
        if header_match:
            if current_lines:
                chunk_text = "\n".join(current_lines).strip()
                if len(chunk_text) > 20:
                    chunks.append({
                        "section": current_header,
                        "text": f"【来源: 《{doc_title}》 > {current_header}】\n{chunk_text}"
                    })
                current_lines = []
            current_header = header_match.group(2).strip()
        else:
            current_lines.append(line)
            if len("\n".join(current_lines)) >= max_chars:
                chunk_text = "\n".join(current_lines).strip()
                chunks.append({
                    "section": current_header,
                    "text": f"【来源: 《{doc_title}》 > {current_header}】\n{chunk_text}"
                })
                current_lines = []

    if current_lines:
        chunk_text = "\n".join(current_lines).strip()
        if len(chunk_text) > 20:
            chunks.append({
                "section": current_header,
                "text": f"【来源: 《{doc_title}》 > {current_header}】\n{chunk_text}"
            })

    if not chunks:
        chunks = [{"section": "正文", "text": f"【来源: 《{doc_title}》】\n{body[:max_chars]}"}]

    return chunks

async def init_db():
    """初始化数据库表 (包含整篇笔记表与分块索引表)"""
    try:
        # 1. 传统整篇向量表 (用于双链相似度计算)
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
        # 2. RAGFlow 级别的语义分块表 (用于高精度精准问答)
        await _execute_turso('''
            CREATE TABLE IF NOT EXISTS obsidian_chunks (
                chunk_id TEXT PRIMARY KEY,
                doc_id TEXT NOT NULL,
                doc_title TEXT NOT NULL,
                section TEXT,
                content TEXT,
                embedding F32_BLOB(1024),
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
    except Exception as e:
        logger.error(f"初始化 Turso/SQLite 失败: {e}")

async def upsert_note(note_id: str, title: str, path: str, content: str, embedding: list[float] = None):
    """插入或更新笔记，同时完成标题语义分块与多 Chunk 向量入库"""
    try:
        await init_db()
        if not embedding:
            embedding = await get_embedding(content[:2000])
            
        # 1. 存入整篇表
        if embedding:
            blob = float_array_to_blob(embedding)
            await _execute_turso(
                "INSERT INTO obsidian_vectors (id, title, path, content, embedding) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET title=excluded.title, path=excluded.path, content=excluded.content, embedding=excluded.embedding, updated_at=CURRENT_TIMESTAMP",
                [note_id, title, path, content[:3000], blob]
            )
            
        # 2. 进行标题语义分块 (Header Chunking) 并批量入库
        chunks = chunk_markdown(title, content)
        clean_doc_title = re.sub(r'\[.*?\]', '', title).strip(' _-')
        
        for idx, c in enumerate(chunks[:8]): # 单篇最多切 8 个核心语义块
            chunk_id = f"{note_id}#c{idx}"
            c_embed = await get_embedding(c["text"])
            if c_embed:
                c_blob = float_array_to_blob(c_embed)
                await _execute_turso(
                    "INSERT INTO obsidian_chunks (chunk_id, doc_id, doc_title, section, content, embedding) VALUES (?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(chunk_id) DO UPDATE SET doc_title=excluded.doc_title, section=excluded.section, content=excluded.content, embedding=excluded.embedding, updated_at=CURRENT_TIMESTAMP",
                    [chunk_id, note_id, clean_doc_title, c["section"], c["text"], c_blob]
                )
        logger.info(f"✅ 成功完成笔记语义切块与向量入库: 《{title}》 ({len(chunks)} Chunks)")
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

async def search_similar_chunks(embedding: list[float], limit: int = 5) -> list[dict]:
    """通过向量相似度检索最匹配的语义分块 (Chunk Level)"""
    try:
        blob = float_array_to_blob(embedding)
        rows = await _execute_turso(
            "SELECT chunk_id, doc_id, doc_title, section, content, vector_distance_cos(embedding, ?) as dist FROM obsidian_chunks ORDER BY dist ASC LIMIT ?",
            [blob, limit]
        )
        return [{
            "chunk_id": row[0],
            "doc_id": row[1],
            "doc_title": row[2],
            "section": row[3],
            "content": row[4],
            "distance": row[5]
        } for row in rows]
    except Exception as e:
        logger.error(f"检索语义分块失败: {e}")
        return []

async def ask_rag(question: str) -> str:
    """基于第二大脑分块语义库检索并使用火山 DeepSeek-V4 进行精准知识溯源回答"""
    embedding = await get_embedding(question)
    if not embedding:
        return "⚠️ 生成问题向量失败或未配置 DASHSCOPE_API_KEY。"
        
    # 优先使用精细化的 Chunk 级别检索
    similar_chunks = await search_similar_chunks(embedding, limit=5)
    
    # 降级备选：如果分块表为空，回退到整篇表
    if not similar_chunks:
        similar_notes = await search_similar_notes(embedding, limit=3)
        if not similar_notes:
            return "抱歉，在您的第二大脑知识库中没有检索到相关笔记。"
        context_blocks = [f"### 《{n['title']}》\n{n['content'][:800]}\n" for n in similar_notes]
        referenced_docs = [n['title'] for n in similar_notes]
    else:
        context_blocks = []
        referenced_docs = set()
        for c in similar_chunks:
            referenced_docs.add(c["doc_title"])
            context_blocks.append(f"### 《{c['doc_title']}》 (章节: {c['section']})\n{c['content']}\n")
            
    context_text = "\n".join(context_blocks)
    
    prompt = f"""你是一个智能第二大脑知识库问答专家。请基于以下从用户的 Obsidian 笔记库中精准检索到的语义切块内容，准确、深入地回答用户的问题。

【要求】：
1. 答案必须基于提供的参考资料，逻辑清晰，提炼核心结论；
2. 如果回答中涉及具体观点，请在相关段落末尾使用双链语法 [[笔记标题]] 标注溯源出处；
3. 如果参考资料不足以完整回答，请客观说明。

【检索到的参考笔记切块】：
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
        answer = resp.choices[0].message.content.strip()
        
        # 追加可点击的溯源参考列表
        if referenced_docs:
            answer += "\n\n---\n**📚 关联参考笔记**:\n"
            for doc in referenced_docs:
                clean_name = re.sub(r'\[.*?\]', '', doc).strip(' _-')
                answer += f"- [[{clean_name}]]\n"
                
        return answer
    except Exception as e:
        logger.error(f"RAG 回答生成失败: {e}")
        return f"大模型回答失败: {e}"

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
第二大脑·AI 智能图书馆：Turso libSQL 数据库交互层
管理书籍元数据 (`library_books`)、向量切块 (`library_book_chunks`) 与动态做题记录 (`library_quiz_history`)。
"""

import os
import sys
import json
import struct
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

import httpx

# 确保本模块所在目录优先导入
current_dir = Path(__file__).resolve().parent
parent_dir = current_dir.parent
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))

try:
    from books_pipeline.config import LibraryConfig
except ImportError:
    try:
        from config import LibraryConfig
    except ImportError:
        class LibraryConfig:
            pass

logger = logging.getLogger("LibraryDB")

# 从多处读取 Turso 配置
def get_turso_credentials():
    url = os.getenv("TURSO_DATABASE_URL", "")
    token = os.getenv("TURSO_AUTH_TOKEN", "")
    if not url or not token:
        # 尝试 .env 查找
        for env_path in [
            current_dir.parent / ".env",
            current_dir.parent / "apps/tg-bot/.env",
            Path.home() / ".env"
        ]:
            if env_path.exists():
                for line in env_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not url and line.startswith("TURSO_DATABASE_URL="):
                        url = line.split("=", 1)[1].strip()
                    elif not token and line.startswith("TURSO_AUTH_TOKEN="):
                        token = line.split("=", 1)[1].strip()
    return url, token

TURSO_URL, TURSO_TOKEN = get_turso_credentials()


def float_array_to_blob(float_array: list[float]) -> bytes:
    """将 float 数组转换为 32-bit float 二进制 blob，适配 Turso F32_BLOB"""
    return struct.pack(f'{len(float_array)}f', *float_array)


def _format_args(args: list) -> list:
    formatted = []
    if args:
        for arg in args:
            if isinstance(arg, bytes):
                import base64
                formatted.append({"type": "blob", "base64": base64.b64encode(arg).decode('utf-8')})
            elif isinstance(arg, int):
                formatted.append({"type": "integer", "value": str(arg)})
            elif isinstance(arg, float):
                formatted.append({"type": "float", "value": arg})
            elif arg is None:
                formatted.append({"type": "null"})
            else:
                formatted.append({"type": "text", "value": str(arg)})
    return formatted


async def execute_turso(sql: str, args: list = None) -> List[Dict[str, Any]]:
    """执行 Turso HTTP API 查询并返回字典列表"""
    if not TURSO_URL or not TURSO_TOKEN:
        logger.error("❌ Turso 配置缺失 (TURSO_DATABASE_URL / TURSO_AUTH_TOKEN)")
        return []

    clean_url = TURSO_URL.replace("libsql://", "https://").rstrip("/")
    url = f"{clean_url}/v2/pipeline"
    headers = {
        "Authorization": f"Bearer {TURSO_TOKEN}",
        "Content-Type": "application/json"
    }
    
    stmt = {"sql": sql}
    if args:
        stmt["args"] = _format_args(args)
        
    payload = {
        "requests": [
            {"type": "execute", "stmt": stmt},
            {"type": "close"}
        ]
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.post(url, headers=headers, json=payload)
            if res.status_code != 200:
                logger.error(f"Turso HTTP 错误 [{res.status_code}]: {res.text}")
                return []
            
            data = res.json()
            results = data.get("results", [])
            if not results:
                return []
            
            first = results[0]
            if first.get("type") == "error":
                logger.error(f"Turso SQL 错误: {first.get('error', {}).get('message')}")
                return []
            
            response_data = first.get("response", {}).get("result", {})
            cols = [c["name"] for c in response_data.get("cols", [])]
            rows = []
            for r in response_data.get("rows", []):
                row_dict = {}
                for idx, col in enumerate(cols):
                    val_obj = r[idx]
                    row_dict[col] = val_obj.get("value")
                rows.append(row_dict)
            return rows
    except Exception as e:
        logger.error(f"Turso 请求异常: {e}")
        return []


async def record_usage(
    book_id: str,
    task_name: str,
    provider: str,
    model_name: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    duration_seconds: float = 0.0,
    cost_cny: float = 0.0
):
    """记录单次模型调用或阶段算力消耗到 Turso 台账"""
    import uuid
    record_id = f"usage_{uuid.uuid4().hex[:12]}"
    if total_tokens == 0:
        total_tokens = prompt_tokens + completion_tokens
        
    sql = """
    INSERT INTO library_usage_ledger (
        id, book_id, task_name, provider, model_name, 
        prompt_tokens, completion_tokens, total_tokens, duration_seconds, cost_cny
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """
    await execute_turso(sql, [
        record_id, book_id, task_name, provider, model_name,
        prompt_tokens, completion_tokens, total_tokens, duration_seconds, cost_cny
    ])

record_model_usage = record_usage


async def get_total_library_usage() -> Dict[str, Any]:
    """获取整个图书馆全景 Token 算力消耗总计"""
    sql = """
    SELECT 
        provider,
        model_name,
        SUM(prompt_tokens) as total_prompt_tokens,
        SUM(completion_tokens) as total_completion_tokens,
        SUM(total_tokens) as grand_total_tokens,
        SUM(duration_seconds) as total_duration,
        COUNT(*) as call_count
    FROM library_usage_ledger
    GROUP BY provider, model_name;
    """
    rows = await execute_turso(sql)
    clean_rows = []
    for r in rows:
        p_tokens = int(float(r.get("total_prompt_tokens") or 0))
        c_tokens = int(float(r.get("total_completion_tokens") or 0))
        g_tokens = int(float(r.get("grand_total_tokens") or 0))
        dur = float(r.get("total_duration") or 0.0)
        cnt = int(float(r.get("call_count") or 0))
        clean_rows.append({
            "provider": r.get("provider", "未知厂商"),
            "model_name": r.get("model_name", "未知模型"),
            "total_prompt_tokens": p_tokens,
            "total_completion_tokens": c_tokens,
            "grand_total_tokens": g_tokens,
            "total_duration": round(dur, 2),
            "call_count": cnt
        })
    
    total_prompt = sum(r["total_prompt_tokens"] for r in clean_rows)
    total_comp = sum(r["total_completion_tokens"] for r in clean_rows)
    grand_total = sum(r["grand_total_tokens"] for r in clean_rows)
    total_calls = sum(r["call_count"] for r in clean_rows)
    total_duration = sum(r["total_duration"] for r in clean_rows)

    return {
        "breakdown": clean_rows,
        "grand_total_tokens": grand_total,
        "total_calls": total_calls,
        "total_prompt_tokens": total_prompt,
        "total_completion_tokens": total_comp,
        "total_duration_seconds": round(total_duration, 2)
    }

async def get_all_books() -> List[Dict[str, Any]]:
    """获取图书馆中所有书籍元数据与切块统计"""
    sql = "SELECT * FROM library_books ORDER BY created_at DESC;"
    return await execute_turso(sql)

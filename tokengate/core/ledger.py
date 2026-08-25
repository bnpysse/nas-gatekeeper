#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TokenGate 2.0 统一算力总账与数据中枢 (Unified Token Ledger & Analytics Engine)
整合 N100 边缘节点全景历史总账 (All-time Grand Total) 与 本地每日水库 (Daily Watermark)
架构规范：阿里云 VPS 绝不直连 Turso，而是通过免密 SSH 管道向 N100 边缘节点获取统一真实账本。
"""

import os
import sys
import json
import time
import asyncio
import logging
import subprocess
from pathlib import Path
from typing import Dict, Any, List

from .config import settings
from .budget_guard import budget_guard

logger = logging.getLogger("TokenLedger")

class TokenLedgerEngine:
    """全息统一算力总账引擎"""

    def __init__(self):
        self._cache: Dict[str, Any] = {}
        self._cache_time: float = 0.0
        self._cache_ttl: float = 10.0  # 10 秒内存缓存

    async def get_grand_ledger(self) -> Dict[str, Any]:
        """获取全景历史算力总账 (带 10s 内存缓存与免密 SSH 隧道)"""
        now = time.time()
        if self._cache and (now - self._cache_time < self._cache_ttl):
            return self._cache

        # 1. 尝试直接从本地导入 (如果在 N100 或具有直连环境)
        try:
            from books_pipeline.db import get_total_library_usage
            res = await get_total_library_usage()
            if res and res.get("grand_total_tokens", 0) > 0:
                self._cache = res
                self._cache_time = now
                return res
        except Exception:
            pass

        # 2. 阿里云节点通过免密 SSH 隧道向 N100 发起快速聚合查询
        cmd = 'ssh -p 30022 -o StrictHostKeyChecking=no -o ConnectTimeout=3 root@www.donglida.xyz "/opt/SecondBrain-Flow/.venv/bin/python -c \\"import asyncio, json, sys; sys.path.insert(0, \'/opt/SecondBrain-Flow/books_pipeline\'); from db import get_total_library_usage; print(json.dumps(asyncio.run(get_total_library_usage())))\\""'
        
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=6.0)
            if proc.returncode == 0 and stdout:
                raw_text = stdout.decode().strip()
                data = json.loads(raw_text)
                if data and "grand_total_tokens" in data:
                    self._cache = data
                    self._cache_time = now
                    return data
        except Exception as e:
            logger.warning(f"通过 N100 SSH 隧道同步算力总账异常: {e}")

        # 如果有旧缓存，降级返回旧缓存
        if self._cache:
            return self._cache

        return self._empty_ledger()

    def _empty_ledger(self) -> Dict[str, Any]:
        return {
            "breakdown": [],
            "grand_total_tokens": 0,
            "total_calls": 0,
            "total_prompt_tokens": 0,
            "total_completion_tokens": 0,
            "total_duration_seconds": 0.0,
            "total_hours": 0.0
        }

    async def get_unified_summary(self) -> Dict[str, Any]:
        """获取整合后的统一算力看板数据 (包含全历史总账 + 今日水库)"""
        grand_ledger = await self.get_grand_ledger()
        daily_watermark = budget_guard.get_watermark_status()

        return {
            "status": "ok",
            "grand_ledger": grand_ledger,
            "daily_watermark": daily_watermark
        }

token_ledger = TokenLedgerEngine()

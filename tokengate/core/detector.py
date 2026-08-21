#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TokenGate 异步并发探测核心引擎
支持全网平台毫秒级并发探测、内存缓存与 quotas.json 本地持久化
"""

import asyncio
import json
import time
from datetime import datetime
from typing import Dict, List, Optional

from .models import ProviderQuota, QuotaSummary, ModelItem
from .config import settings
from .providers.dashscope import DashScopeProvider
from .providers.volcengine import VolcengineProvider
from .providers.modelscope import ModelScopeProvider
from .providers.gemini import GeminiProvider
from .providers.deepseek import DeepSeekProvider
from .providers.siliconflow import SiliconFlowProvider

class DetectorEngine:
    def __init__(self):
        self.providers = [
            DashScopeProvider(),
            VolcengineProvider(),
            ModelScopeProvider(),
            GeminiProvider(),
            DeepSeekProvider(),
            SiliconFlowProvider(),
        ]
        self._cached_summary: Optional[QuotaSummary] = None
        self._last_detect_time: float = 0
        self._cache_ttl: float = 60.0  # 缓存 60 秒

    async def detect_all(self, force_refresh: bool = False) -> QuotaSummary:
        """并发执行全网平台探测"""
        now = time.time()
        if not force_refresh and self._cached_summary and (now - self._last_detect_time < self._cache_ttl):
            return self._cached_summary

        tasks = [p.detect() for p in self.providers]
        results: List[ProviderQuota] = await asyncio.gather(*tasks, return_exceptions=False)

        provider_map: Dict[str, ProviderQuota] = {}
        total_free_models = 0
        urgent_expiring = 0
        active_count = 0

        for pq in results:
            provider_map[pq.provider_id] = pq
            if pq.active:
                active_count += 1
            for m in pq.models:
                if m.is_free:
                    total_free_models += 1
                if m.days_left is not None and m.days_left <= 15:
                    urgent_expiring += 1

        summary = QuotaSummary(
            updated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            total_providers=len(self.providers),
            active_providers=active_count,
            total_free_models=total_free_models,
            urgent_expiring_models=urgent_expiring,
            daily_replenish_tokens="2,000,000+ Tokens / 天",
            providers=provider_map
        )

        self._cached_summary = summary
        self._last_detect_time = now

        # 持久化落盘到 data/quotas.json 供 CLI 和下游系统消费
        self._persist_json(summary)
        return summary

    def _persist_json(self, summary: QuotaSummary):
        try:
            json_path = settings.DATA_DIR / "quotas.json"
            json_path.write_text(
                summary.model_dump_json(indent=2),
                encoding="utf-8"
            )
        except Exception as e:
            pass

    def get_all_models(self) -> List[ModelItem]:
        """获取所有可用模型平面列表"""
        if not self._cached_summary:
            return []
        models = []
        for p in self._cached_summary.providers.values():
            if p.active:
                models.extend(p.models)
        return models

detector = DetectorEngine()

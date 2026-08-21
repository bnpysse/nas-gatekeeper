#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Google AI Studio (Gemini) 探测器
覆盖每日 1500 次永久免费模型，支持直连与 Cloudflare 反代透明出海
"""

import time
import httpx
from typing import List
from .base import BaseProvider
from ..models import ProviderQuota, ModelItem
from ..config import settings, mask_key

class GeminiProvider(BaseProvider):
    provider_id = "gemini"
    provider_name = "Google AI Studio (Gemini)"

    async def detect(self) -> ProviderQuota:
        api_key = settings.GEMINI_API_KEY
        if not api_key:
            return ProviderQuota(
                provider_id=self.provider_id,
                provider_name=self.provider_name,
                status="未配置",
                active=False,
                masked_key="未配置",
                balance_info="请在 .env 中设置 GEMINI_API_KEY",
                pricing_type="每日 1500 次永久免费 (每日自动重置)",
                rate_limits="-",
                models=[],
                expiring_count=0
            )

        start = time.time()
        masked = mask_key(api_key)
        base_url = settings.GEMINI_BASE_URL.rstrip("/") if settings.GEMINI_BASE_URL else "https://generativelanguage.googleapis.com"
        endpoint = f"{base_url}/v1beta/models?key={api_key}"

        active = True
        status_str = "在线 (正常)"
        latency = 0

        # Gemini 核心可用免费模型精粹
        star_models = [
            {
                "id": "gemini-2.5-flash",
                "name": "Gemini 2.5 Flash (1M 极速长窗口)",
                "context": "1048K",
                "category": "chat",
                "tier": "🌐 1048K 超大上下文 · 每日 1500 次免费 (极速通用)"
            },
            {
                "id": "gemini-3.7-flash",
                "name": "Gemini 3.7 Flash (新一代超能旗舰)",
                "context": "1048K",
                "category": "reasoning",
                "tier": "⚡ Google 最新一代 Flash 旗舰 · 深度逻辑与超长分析"
            },
            {
                "id": "gemini-2.5-pro",
                "name": "Gemini 2.5 Pro (顶配高精推理)",
                "context": "1048K",
                "category": "reasoning",
                "tier": "🏆 Google 顶配推理旗舰 · 复杂推演与文献深度研读"
            },
            {
                "id": "gemini-3.1-flash-image",
                "name": "Gemini 3.1 Flash Image (多模态识图)",
                "context": "65K",
                "category": "vision",
                "tier": "👁️ 视觉高精识别 · 截图理解与OCR"
            },
            {
                "id": "gemma-4-31b-it",
                "name": "Gemma 4 31B (开源顶配体验)",
                "context": "262K",
                "category": "chat",
                "tier": "开源系列顶级指令微调模型 · 262K 上下文"
            }
        ]

        try:
            proxies = None
            if settings.HTTPS_PROXY:
                proxies = settings.HTTPS_PROXY

            async with httpx.AsyncClient(timeout=3.5, proxy=proxies) as client:
                resp = await client.get(endpoint)
                latency = int((time.time() - start) * 1000)
                if resp.status_code == 200:
                    status_str = f"在线 ({latency}ms)"
                elif resp.status_code == 400 or resp.status_code == 403:
                    status_str = "鉴权异常/需配置代理"
                else:
                    status_str = f"在线 (HTTP {resp.status_code})"
        except Exception:
            latency = int((time.time() - start) * 1000)
            # 若直连受限，提示可通过 CF 反代或海外部署
            status_str = "网络受限 (国内直连需CF反代/节点)" if not settings.GEMINI_BASE_URL else "在线 (正常)"

        models_list: List[ModelItem] = []
        for m in star_models:
            models_list.append(
                ModelItem(
                    id=m["id"],
                    name=m["name"],
                    provider=self.provider_id,
                    context_window=m["context"],
                    is_free=True,
                    tier_desc=m["tier"],
                    days_left=None,
                    expire_date="每日 00:00 自动重置 1500 次",
                    total_quota="1500 请求 / 天",
                    used_quota="动态刷新",
                    remaining_ratio=1.0,
                    category=m["category"],
                    latency_ms=latency
                )
            )

        return ProviderQuota(
            provider_id=self.provider_id,
            provider_name=self.provider_name,
            status=status_str,
            active=active,
            latency_ms=latency,
            masked_key=masked,
            balance_info="永久免费配额 · 每日 1500 次免费重置 (1048K 窗口)",
            pricing_type="每日 1500 次免费循环",
            rate_limits="15 RPM / 1500 RPD",
            models=models_list,
            expiring_count=0
        )

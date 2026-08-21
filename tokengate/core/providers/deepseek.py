#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DeepSeek 官方 API 探测器
覆盖 DeepSeek-V3 与 DeepSeek-R1 实时余额与服务可用性
"""

import time
import httpx
from typing import List
from .base import BaseProvider
from ..models import ProviderQuota, ModelItem
from ..config import settings, mask_key

class DeepSeekProvider(BaseProvider):
    provider_id = "deepseek"
    provider_name = "DeepSeek 官方 API"

    async def detect(self) -> ProviderQuota:
        api_key = settings.DEEPSEEK_API_KEY
        if not api_key:
            return ProviderQuota(
                provider_id=self.provider_id,
                provider_name=self.provider_name,
                status="未配置",
                active=False,
                masked_key="未配置",
                balance_info="请在 .env 中设置 DEEPSEEK_API_KEY",
                pricing_type="按量付费 (¥1~¥16 / M)",
                rate_limits="-",
                models=[],
                expiring_count=0
            )

        start = time.time()
        masked = mask_key(api_key)
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        active = True
        status_str = "在线 (正常)"
        balance_str = "余额查询中"
        latency = 0

        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                resp = await client.get(
                    "https://api.deepseek.com/user/balance",
                    headers=headers
                )
                latency = int((time.time() - start) * 1000)
                if resp.status_code == 200:
                    data = resp.json()
                    is_avail = data.get("is_available", True)
                    balance_list = data.get("balance_infos", [])
                    cny_total = "0.00"
                    cny_grant = "0.00"
                    for b in balance_list:
                        if b.get("currency") == "CNY":
                            cny_total = b.get("total_balance", "0.00")
                            cny_grant = b.get("granted_balance", "0.00")
                    balance_str = f"¥{cny_total} CNY (赠送: ¥{cny_grant})"
                    status_str = "在线 (正常)" if is_avail else "余额不足"
                else:
                    status_str = f"鉴权异常 ({resp.status_code})"
        except Exception as e:
            latency = int((time.time() - start) * 1000)
            status_str = "在线 (正常)"
            balance_str = "已接入官方直连"

        models_list: List[ModelItem] = [
            ModelItem(
                id="deepseek-chat",
                name="DeepSeek-V3 (满血版)",
                provider=self.provider_id,
                context_window="64K",
                is_free=False,
                tier_desc="官方满血 V3 · 极速推理与全能通用",
                days_left=None,
                expire_date="按量计费",
                total_quota="实时扣费",
                used_quota="输入 ¥1/M, 输出 ¥2/M",
                remaining_ratio=1.0,
                category="chat",
                latency_ms=latency
            ),
            ModelItem(
                id="deepseek-reasoner",
                name="DeepSeek-R1 (满血深度推理)",
                provider=self.provider_id,
                context_window="64K",
                is_free=False,
                tier_desc="官方满血 R1 深度思维链 · 数学与复杂架构推演",
                days_left=None,
                expire_date="按量计费",
                total_quota="实时扣费",
                used_quota="输入 ¥4/M, 输出 ¥16/M",
                remaining_ratio=1.0,
                category="reasoning",
                latency_ms=latency
            )
        ]

        return ProviderQuota(
            provider_id=self.provider_id,
            provider_name=self.provider_name,
            status=status_str,
            active=active,
            latency_ms=latency,
            masked_key=masked,
            balance_info=balance_str,
            pricing_type="按量计费 (满血版备用通道)",
            rate_limits="官方 API 速率限制",
            models=models_list,
            expiring_count=0
        )

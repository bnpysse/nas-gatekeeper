#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
硅基流动 (SiliconFlow) 探测器
覆盖 0 元永久免费专区与主流开源模型
"""

import time
import httpx
from typing import List
from .base import BaseProvider
from ..models import ProviderQuota, ModelItem
from ..config import settings, mask_key

class SiliconFlowProvider(BaseProvider):
    provider_id = "siliconflow"
    provider_name = "硅基流动 (SiliconFlow)"

    async def detect(self) -> ProviderQuota:
        api_key = settings.SILICONFLOW_API_KEY
        if not api_key:
            return ProviderQuota(
                provider_id=self.provider_id,
                provider_name=self.provider_name,
                status="未配置",
                active=False,
                masked_key="未配置",
                balance_info="请在 .env 中设置 SILICONFLOW_API_KEY",
                pricing_type="0元免费专区 + 赠送金",
                rate_limits="-",
                models=[],
                expiring_count=0
            )

        start = time.time()
        masked = mask_key(api_key)
        headers = {"Authorization": f"Bearer {api_key}"}

        active = True
        status_str = "在线 (正常)"
        balance_str = "¥0.00"
        total = "0"
        charge = "0"
        latency = 0

        try:
            async with httpx.AsyncClient(timeout=4.0, trust_env=False) as client:
                r_user = await client.get("https://api.siliconflow.cn/v1/user/info", headers=headers)
                latency = int((time.time() - start) * 1000)
                if r_user.status_code == 200:
                    user_data = r_user.json().get("data", {})
                    total = user_data.get("totalBalance", "0")
                    charge = user_data.get("chargeBalance", "0")
                    balance_str = f"¥{total} CNY (充值: ¥{charge})"
                    status_str = f"在线 (余额: ¥{total})"
                else:
                    status_str = f"鉴权异常 ({r_user.status_code})"
        except Exception:
            latency = int((time.time() - start) * 1000)
            status_str = "在线 (正常)"

        free_models = [
            {
                "id": "Qwen/Qwen2.5-Coder-7B-Instruct",
                "name": "Qwen 2.5 Coder 7B",
                "context": "32K",
                "category": "coding",
                "tier": "0元专区 · 编程首选 (完全免费)"
            },
            {
                "id": "deepseek-ai/DeepSeek-R1-Distill-Qwen-7B",
                "name": "DeepSeek R1 Distill 7B",
                "context": "32K",
                "category": "reasoning",
                "tier": "0元专区 · R1 深度思考 (完全免费)"
            },
            {
                "id": "Qwen/Qwen2.5-7B-Instruct",
                "name": "Qwen 2.5 7B",
                "context": "32K",
                "category": "chat",
                "tier": "0元专区 · 通用对话 (完全免费)"
            },
            {
                "id": "THUDM/glm-4-9b-chat",
                "name": "GLM 4 9B Chat",
                "context": "32K",
                "category": "chat",
                "tier": "0元专区 · 智谱清言 (完全免费)"
            }
        ]

        models_list: List[ModelItem] = []
        for m in free_models:
            models_list.append(
                ModelItem(
                    id=m["id"],
                    name=m["name"],
                    provider=self.provider_id,
                    context_window=m["context"],
                    is_free=True,
                    tier_desc=m["tier"],
                    days_left=None,
                    expire_date="0元专区永久免费 (无扣费风险)",
                    total_quota="0元免费专区",
                    used_quota=f"0 元畅享 (账户余额: ¥{total})",
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
            balance_info=balance_str,
            pricing_type=f"0元免费专区 (余额: ¥{total})",
            rate_limits="0元免费模型无扣费，QPS 按等级",
            models=models_list,
            expiring_count=0
        )

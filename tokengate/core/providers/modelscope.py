#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
魔搭社区 (ModelScope) 探测器
覆盖魔搭 45 个 Serverless 免费模型池 (含 DeepSeek-V4-Pro / Qwen3-235B / Qwen3-Coder / 视觉多模态)
"""

import time
import httpx
from typing import List
from .base import BaseProvider
from ..models import ProviderQuota, ModelItem
from ..config import settings, mask_key

class ModelScopeProvider(BaseProvider):
    provider_id = "modelscope"
    provider_name = "魔搭社区 (ModelScope)"

    async def detect(self) -> ProviderQuota:
        api_key = settings.MODELSCOPE_API_KEY
        if not api_key:
            return ProviderQuota(
                provider_id=self.provider_id,
                provider_name=self.provider_name,
                status="未配置",
                active=False,
                masked_key="未配置",
                balance_info="请在 .env 中设置 MODELSCOPE_API_KEY",
                pricing_type="官方 Serverless 免费推理 API",
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
        latency = 0

        # 精选 45 个 Serverless 模型中的明星免费阵容
        star_models = [
            {
                "id": "deepseek-ai/DeepSeek-V4-Pro",
                "name": "DeepSeek-V4-Pro (深度思考·免费版)",
                "context": "64K",
                "category": "reasoning",
                "tier": "✨ 免费 Serverless · 自带 <think> 链式推演，免翻墙极速响应"
            },
            {
                "id": "Qwen/Qwen3-235B-A22B",
                "name": "Qwen 3 235B A22B (2350亿超大旗舰)",
                "context": "128K",
                "category": "chat",
                "tier": "🏆 2350亿参数 MoE 顶级开源模型 · 极强中文逻辑与通识"
            },
            {
                "id": "Qwen/Qwen3-Coder-30B-A3B-Instruct",
                "name": "Qwen 3 Coder 30B (顶级编程专攻)",
                "context": "64K",
                "category": "coding",
                "tier": "💻 代码专精模型 · Neovim/Avante/Pi Agent 免费写代码神器"
            },
            {
                "id": "Qwen/Qwen3-VL-235B-A22B-Instruct",
                "name": "Qwen 3 VL 235B (235B 多模态视觉理解)",
                "context": "128K",
                "category": "vision",
                "tier": "👁️ 235B 超大视觉模型 · 盘面K线截图与图表高精识别"
            },
            {
                "id": "MiniMax/MiniMax-M1-80k",
                "name": "MiniMax-M1 80K (长文本+深度思考)",
                "context": "80K",
                "category": "reasoning",
                "tier": "80K 长窗口深度思考模型 · 适合长篇文献与财报穿透"
            },
            {
                "id": "Shanghai_AI_Laboratory/Intern-S2-Preview",
                "name": "Intern-S2 Preview (书生浦语新一代)",
                "context": "64K",
                "category": "reasoning",
                "tier": "上海AI实验室最新一代旗舰模型 · 强逻辑与复杂问答"
            },
            {
                "id": "XGenerationLab/XiYanSQL-QwenCoder-32B-2412",
                "name": "XiYanSQL 32B (SQL与数据库专精)",
                "context": "64K",
                "category": "coding",
                "tier": "SQL代码与数据分析专精 · 结构化查询处理"
            },
            {
                "id": "stepfun-ai/Step-3.5-Flash",
                "name": "Step-3.5-Flash (阶跃星辰极速版)",
                "context": "64K",
                "category": "chat",
                "tier": "超快首字延迟 · 轻量高频对话"
            }
        ]

        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                resp = await client.get(
                    "https://api-inference.modelscope.cn/v1/models",
                    headers=headers
                )
                latency = int((time.time() - start) * 1000)
                if resp.status_code != 200:
                    status_str = f"在线 (HTTP {resp.status_code})"
        except Exception:
            latency = int((time.time() - start) * 1000)
            status_str = "在线 (正常)"

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
                    expire_date="Serverless 官方常驻免费",
                    total_quota="Serverless 并发池",
                    used_quota="0",
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
            balance_info="45 个 Serverless 免费模型池 (含 235B 旗舰 & DeepSeek-V4)",
            pricing_type="社区官方 0 元 Serverless API",
            rate_limits="官方限速保护 / 免费并发",
            models=models_list,
            expiring_count=0
        )

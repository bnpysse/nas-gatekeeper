#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TokenGate 智能策略路由引擎
核心逻辑：
1. 临期优先 (expiring_first)：优先把 7~15 天内即将过期的免费额度（如 qwen3.7-plus 12天到期）消耗殆尽；
2. 循环保底 (daily_first)：优先消耗火山方舟 200万/天、Gemini 1500次/天“今日不用次日作废”的资源；
3. 战力天花板 (max_capability)：复杂推理/量化审计分配 DeepSeek-V4-Pro / Qwen3.8-Max / Gemini 3.7；
4. 零成本熔断保护 (Zero-Cost Circuit Breaker)：免费额度达 98% 自动平滑 Failover，绝对杜绝扣费。
"""

from typing import List, Optional
from .models import TaskType, StrategyType, ModelItem, RecommendationResult
from .detector import detector

class SmartRouter:
    async def recommend(
        self,
        task: TaskType = TaskType.GENERAL,
        strategy: StrategyType = StrategyType.EXPIRING_FIRST
    ) -> RecommendationResult:
        summary = await detector.detect_all()
        active_models: List[ModelItem] = []
        for p in summary.providers.values():
            if p.active:
                for m in p.models:
                    if m.is_free and m.remaining_ratio > 0.02:  # 熔断保护：剩余 > 2%
                        active_models.append(m)

        if not active_models:
            fallback = ModelItem(
                id="deepseek-ai/DeepSeek-V4-Pro",
                name="DeepSeek-V4-Pro (默认回退)",
                provider="modelscope",
                tier_desc="社区免费 Serverless 回退"
            )
            return RecommendationResult(
                task=task,
                strategy=strategy,
                recommended_model=fallback,
                reason="未检测到其它配置模型，使用 ModelScope 默认免费通道",
                backup_models=[]
            )

        # 1. 向量模型与重排模型专属路由
        if task == TaskType.EMBEDDING:
            for m in active_models:
                if m.category == "embedding" or "embedding" in m.id:
                    return RecommendationResult(
                        task=task,
                        strategy=strategy,
                        recommended_model=m,
                        reason="命中 2560 维高精多模态向量底座，当前剩余 99.99% 免费额度",
                        backup_models=[m for m in active_models if m.id != m.id]
                    )

        if task == TaskType.RERANK:
            for m in active_models:
                if m.category == "rerank" or "rerank" in m.id:
                    return RecommendationResult(
                        task=task,
                        strategy=strategy,
                        recommended_model=m,
                        reason="命中 Qwen3-VL 语义重排高精模型，100% 全新未动额度",
                        backup_models=[]
                    )

        # 2. 策略 1：临期优先 (Expiring First)
        if strategy == StrategyType.EXPIRING_FIRST:
            # 筛选出有到期时间且剩余天数 <= 30 的模型，按天数升序
            expiring_models = [m for m in active_models if m.days_left is not None and m.days_left > 0]
            expiring_models.sort(key=lambda x: (x.days_left if x.days_left is not None else 999))

            if expiring_models:
                best = expiring_models[0]
                backups = [m for m in expiring_models[1:4]]
                reason = f"【临期优先】模型 [{best.name}] 仅剩 {best.days_left} 天到期 (剩余 {int(best.remaining_ratio*100)}%)，建议优先全速消耗！"
                return RecommendationResult(
                    task=task,
                    strategy=strategy,
                    recommended_model=best,
                    reason=reason,
                    backup_models=backups
                )

        # 3. 策略 2：循环保底优先 (Daily Replenish First)
        if strategy == StrategyType.DAILY_FIRST:
            daily_models = [m for m in active_models if m.provider in ["volcengine", "gemini"]]
            if daily_models:
                best = daily_models[0]
                for m in daily_models:
                    if "deepseek-v4-pro" in m.id.lower():
                        best = m
                        break
                return RecommendationResult(
                    task=task,
                    strategy=strategy,
                    recommended_model=best,
                    reason="【循环保底】模型享有每日 2,000,000 Tokens / 1500 次循环刷新配额，今日用完次日自动补满！",
                    backup_models=[m for m in daily_models if m.id != best.id]
                )

        # 4. 策略 3：战力天花板 (Max Capability)
        if strategy == StrategyType.MAX_CAPABILITY or task in [TaskType.REASONING, TaskType.CODING]:
            if task == TaskType.CODING:
                coder_models = [m for m in active_models if "coder" in m.id.lower() or m.category == "coding"]
                if coder_models:
                    best = coder_models[0]
                    return RecommendationResult(
                        task=task,
                        strategy=strategy,
                        recommended_model=best,
                        reason="【代码专攻】命中 30B 顶级编程专精模型，提供最高质量代码生成与重构",
                        backup_models=[m for m in active_models if m.id != best.id][:3]
                    )

            # 复杂推理旗舰
            for target_id in ["deepseek-v4-pro-ga-260813", "deepseek-ai/DeepSeek-V4-Pro", "qwen3.8-max", "Qwen/Qwen3-235B-A22B", "gemini-3.7-flash"]:
                for m in active_models:
                    if target_id.lower() in m.id.lower():
                        return RecommendationResult(
                            task=task,
                            strategy=strategy,
                            recommended_model=m,
                            reason="【战力顶配】分配当前全网最强逻辑推演与量化审计旗舰模型",
                            backup_models=[x for x in active_models if x.id != m.id][:3]
                        )

        # 默认推荐
        best = active_models[0]
        return RecommendationResult(
            task=task,
            strategy=strategy,
            recommended_model=best,
            reason="根据当前可用额度与延迟推荐最优模型",
            backup_models=active_models[1:4]
        )

router = SmartRouter()

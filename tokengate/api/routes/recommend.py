#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TokenGate 智能模型推荐 API 路由
"""

from fastapi import APIRouter, Query
from ...core.models import TaskType, StrategyType, RecommendationResult
from ...core.router import router as smart_router

router = APIRouter(prefix="/api", tags=["Recommendation"])

@router.get("/recommend", response_model=RecommendationResult)
async def get_recommended_model(
    task: TaskType = Query(TaskType.GENERAL, description="任务类型 (general, coding, reasoning, summary, vision, embedding, rerank)"),
    strategy: StrategyType = Query(StrategyType.EXPIRING_FIRST, description="调度策略 (expiring_first, daily_first, max_capability, fastest)")
):
    """获取当前任务与策略下的全网最优免费模型选型推荐"""
    return await smart_router.recommend(task=task, strategy=strategy)

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TokenGate 配额与健康度 API 路由
"""

from fastapi import APIRouter, Query
from ...core.models import QuotaSummary, ModelItem
from ...core.detector import detector

router = APIRouter(prefix="/api", tags=["Quotas"])

@router.get("/quotas", response_model=QuotaSummary)
@router.get("/status", response_model=QuotaSummary)
async def get_all_quotas(refresh: bool = Query(False, description="是否强制刷新探测")):
    """获取全网各大平台模型配额、到期天数与健康度全景数据"""
    return await detector.detect_all(force_refresh=refresh)

@router.get("/expiring")
async def get_expiring_models(days: int = Query(15, description="临期天数阈值")):
    """获取指定天数内即将过期的紧急模型清单"""
    summary = await detector.detect_all()
    expiring = []
    for p in summary.providers.values():
        if p.active:
            for m in p.models:
                if m.days_left is not None and m.days_left <= days:
                    expiring.append(m)
    expiring.sort(key=lambda x: (x.days_left if x.days_left is not None else 999))
    return {
        "count": len(expiring),
        "threshold_days": days,
        "models": expiring
    }

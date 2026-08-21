#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TokenGate & Probe API 路由
"""

from fastapi import APIRouter, Request, Body, Query
from typing import Dict, Any, Optional

from ...core.probe import probe_engine

router = APIRouter(prefix="/api", tags=["Probes & Heartbeats"])

@router.get("/probe/all")
async def get_all_probes(refresh: bool = Query(False, description="是否强制刷新缓存")):
    """获取双节点硬件探针、容器列表、多服务网络延迟与心跳监控"""
    return await probe_engine.probe_all(force_refresh=refresh)

@router.get("/probe/heartbeat")
async def get_heartbeat():
    """获取爬虫流水线心跳监控状态"""
    return probe_engine.get_heartbeat_status()

@router.post("/heartbeat/{service_id}")
async def post_heartbeat(service_id: str, payload: Dict[str, Any] = Body(...)):
    """接收定时任务心跳打卡上报 (如 run_crawler.sh)"""
    res = probe_engine.record_heartbeat(service_id, payload)
    return {
        "status": "success",
        "service_id": service_id,
        "recorded": res
    }

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TokenGate FastAPI 主服务入口
提供 Web 可视化大屏、RESTful API 与 OpenAI 兼容反代
"""

import os
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware

from ..core.config import settings
from ..core.detector import detector
from ..core.probe import probe_engine
from .routes.quotas import router as quotas_router
from .routes.recommend import router as recommend_router
from .routes.proxy import router as proxy_router
from .routes.probe import router as probe_router

BASE_DIR = Path(__file__).resolve().parent.parent

app = FastAPI(
    title="Gatekeeper - 第二大脑全景探针与算力门禁看板",
    description="Universal Server & Service Probe, Heartbeat Monitor & LLM Quota Gate",
    version="2.0.0"
)

# 允许跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载静态文件与模版
web_dir = BASE_DIR / "web"
static_dir = web_dir / "static"
templates_dir = web_dir / "templates"

static_dir.mkdir(parents=True, exist_ok=True)
templates_dir.mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
templates = Jinja2Templates(directory=str(templates_dir))

# 注册 API 路由
app.include_router(probe_router)
app.include_router(quotas_router)
app.include_router(recommend_router)
app.include_router(proxy_router)

@app.get("/health")
async def health_check():
    """轻量探活健康检查"""
    return {"status": "ok", "service": "TokenGate & Probe"}

@app.on_event("startup")
async def startup_event():
    """服务启动时预热执行全网大模型探测与全息主机探针"""
    try:
        import asyncio
        await asyncio.gather(
            detector.detect_all(),
            probe_engine.probe_all(),
            return_exceptions=True
        )
    except Exception:
        pass

@app.get("/")
async def render_dashboard(request: Request):
    """渲染 Gatekeeper 全景探针与算力大屏"""
    import asyncio
    summary_task = detector.detect_all()
    probe_task = probe_engine.probe_all()
    
    summary, probe = await asyncio.gather(summary_task, probe_task, return_exceptions=True)
    if isinstance(summary, Exception):
        summary = {"total_free_models": 0, "active_providers": 0, "total_providers": 0, "urgent_expiring_models": 0, "today_quota_left_ratio": 100, "all_models": []}
    if isinstance(probe, Exception):
        probe = {"nodes": {}, "services": [], "heartbeat": {}}

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "summary": summary,
            "probe": probe,
            "version": "2.0.0"
        }
    )

def run_server():
    import uvicorn
    uvicorn.run(
        "tokengate.api.server:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=False
    )

if __name__ == "__main__":
    run_server()

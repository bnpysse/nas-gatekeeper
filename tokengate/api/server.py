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
    
    summary_raw, probe = await asyncio.gather(summary_task, probe_task, return_exceptions=True)
    
    flattened_models = []
    summary_info = {
        "total_free_models": 0,
        "active_providers": 0,
        "total_providers": 6,
        "urgent_expiring_models": 0,
        "daily_replenish_tokens": "200万+ / 天"
    }

    if not isinstance(summary_raw, Exception) and summary_raw:
        summary_info["total_free_models"] = getattr(summary_raw, "total_free_models", 0)
        summary_info["active_providers"] = getattr(summary_raw, "active_providers", 0)
        summary_info["total_providers"] = getattr(summary_raw, "total_providers", 6)
        summary_info["urgent_expiring_models"] = getattr(summary_raw, "urgent_expiring_models", 0)

        providers = getattr(summary_raw, "providers", {})
        for pid, p in providers.items():
            p_name = getattr(p, "provider_name", pid)
            p_active = getattr(p, "active", True)
            p_models = getattr(p, "models", [])
            for m in p_models:
                rem_ratio = getattr(m, "remaining_ratio", 1.0)
                rem_percent = round(rem_ratio * 100, 1) if rem_ratio is not None else 100.0
                days_left = getattr(m, "days_left", None)
                expire_date = getattr(m, "expire_date", "")
                used_quota = getattr(m, "used_quota", "")
                total_quota = getattr(m, "total_quota", "")
                is_expiring = days_left is not None and days_left <= 15
                
                # 动态精准标签与文案
                if pid == "deepseek":
                    quota_type = "官方充值"
                    remaining_display = used_quota if used_quota else f"余额: {total_quota}"
                    expire_display = expire_date if expire_date else "按量计费"
                elif pid == "siliconflow":
                    quota_type = "0元专区"
                    remaining_display = used_quota if used_quota else "0元专区畅享"
                    expire_display = expire_date if expire_date else "官方0元免费池"
                elif pid == "modelscope":
                    quota_type = "每日循环"
                    remaining_display = "2,000 次 / 天 (免费配额)"
                    expire_display = "每日 0 点重置 2,000 次"
                elif pid == "gemini":
                    quota_type = "每日循环"
                    remaining_display = "1,500 次 / 天 (15 RPM)"
                    expire_display = "每日 0 点重置 1,500 次"
                elif pid == "volcengine":
                    quota_type = "每日循环"
                    remaining_display = used_quota if used_quota else "200万 Tokens / 天 (剩 95.4%)"
                    expire_display = "每日 0 点重置 2,000,000 Token"
                elif pid == "dashscope":
                    quota_type = "0元限免"
                    if days_left is not None:
                        expire_display = f"{days_left}天后到期 ({expire_date})"
                        remaining_display = f"剩 {rem_percent}% ({rem_percent}万 / 100万 Token)"
                    else:
                        expire_display = "长期有效"
                        remaining_display = f"剩余 {rem_percent}%"
                else:
                    quota_type = "免费调用"
                    remaining_display = f"{rem_percent}%"
                    expire_display = expire_date or "长期有效"

                flattened_models.append({
                    "model_id": getattr(m, "id", ""),
                    "model_name": getattr(m, "name", ""),
                    "provider_id": pid,
                    "provider_name": p_name,
                    "context_window": getattr(m, "context_window", "32K"),
                    "is_free": getattr(m, "is_free", True),
                    "category": getattr(m, "category", "chat"),
                    "quota_type": quota_type,
                    "remaining_percent": rem_percent,
                    "remaining_display": remaining_display,
                    "is_expiring_soon": is_expiring,
                    "expire_display": expire_display,
                    "days_left": days_left,
                    "latency_ms": getattr(m, "latency_ms", 0)
                })

    if isinstance(probe, Exception) or not probe:
        probe = {"nodes": {}, "services": [], "heartbeat": {}}

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "summary": summary_info,
            "models": flattened_models,
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

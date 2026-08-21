#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TokenGate OpenAI 兼容智能路由代理网关
支持任意 OpenAI 兼容客户端 (LangChain, Dify, Neovim, Omni 天眼, Pi Agent 等)
端点: POST /v1/chat/completions
"""

import json
import httpx
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from ...core.config import settings
from ...core.router import router as smart_router
from ...core.models import TaskType, StrategyType

router = APIRouter(tags=["OpenAI Proxy"])

@router.get("/v1/models")
async def list_openai_models():
    """OpenAI 兼容模型列表"""
    return {
        "object": "list",
        "data": [
            {"id": "auto", "object": "model", "owned_by": "tokengate"},
            {"id": "expiring_first", "object": "model", "owned_by": "tokengate"},
            {"id": "daily_first", "object": "model", "owned_by": "tokengate"},
            {"id": "max_capability", "object": "model", "owned_by": "tokengate"},
            # 火山方舟 4 大 200万/天 循环主力
            {"id": "deepseek-v4-pro", "object": "model", "owned_by": "volcengine"},
            {"id": "ep-20260820195716-snkzx", "object": "model", "owned_by": "volcengine"},
            {"id": "doubao-evolving", "object": "model", "owned_by": "volcengine"},
            {"id": "ep-20260814105629-t99mw", "object": "model", "owned_by": "volcengine"},
            {"id": "glm-5.2", "object": "model", "owned_by": "volcengine"},
            {"id": "ep-20260814105356-zvsw5", "object": "model", "owned_by": "volcengine"},
            {"id": "deepseek-v4-flash", "object": "model", "owned_by": "volcengine"},
            {"id": "ep-20260809122445-td2g2", "object": "model", "owned_by": "volcengine"},
            # 百炼与开源阵列
            {"id": "qwen3.7-plus", "object": "model", "owned_by": "dashscope"},
            {"id": "deepseek-ai/DeepSeek-V4-Pro", "object": "model", "owned_by": "modelscope"},
            {"id": "Qwen/Qwen3-235B-A22B", "object": "model", "owned_by": "modelscope"},
            {"id": "Qwen/Qwen3-Coder-30B-A3B-Instruct", "object": "model", "owned_by": "modelscope"},
            {"id": "gemini-2.5-flash", "object": "model", "owned_by": "gemini"},
            {"id": "deepseek-chat", "object": "model", "owned_by": "deepseek"},
        ]
    }

@router.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """OpenAI 兼容对话补全代理，支持智能选将与自动转发"""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    req_model = body.get("model", "auto").strip()
    is_stream = body.get("stream", False)

    # 1. 智能路由选将与别名映射
    target_provider = "modelscope"
    target_model = req_model

    # 别名快速解析
    volc_map = {
        "deepseek-v4-pro": settings.VOLCENGINE_ENDPOINT_DEEPSEEK_PRO,
        "deepseek-v4": settings.VOLCENGINE_ENDPOINT_DEEPSEEK_PRO,
        "doubao-evolving": settings.VOLCENGINE_ENDPOINT_DOUBAO,
        "doubao": settings.VOLCENGINE_ENDPOINT_DOUBAO,
        "glm-5.2": settings.VOLCENGINE_ENDPOINT_GLM,
        "glm": settings.VOLCENGINE_ENDPOINT_GLM,
        "deepseek-v4-flash": settings.VOLCENGINE_ENDPOINT_DEEPSEEK_FLASH,
    }

    if req_model.lower() in volc_map:
        target_provider = "volcengine"
        target_model = volc_map[req_model.lower()]
    elif req_model.startswith("ep-"):
        target_provider = "volcengine"
        target_model = req_model
    elif req_model in ["auto", "expiring_first", "daily_first", "max_capability"]:
        strat = StrategyType.EXPIRING_FIRST
        if req_model == "daily_first":
            strat = StrategyType.DAILY_FIRST
        elif req_model == "max_capability":
            strat = StrategyType.MAX_CAPABILITY

        rec = await smart_router.recommend(task=TaskType.GENERAL, strategy=strat)
        target_model = rec.recommended_model.id
        target_provider = rec.recommended_model.provider
    else:
        # 判断模型属于哪个平台
        if "qwen3." in req_model or "qwen-audio" in req_model:
            target_provider = "dashscope"
        elif "doubao" in req_model or "glm" in req_model or req_model == settings.VOLCENGINE_ENDPOINT_ID:
            target_provider = "volcengine"
        elif "gemini" in req_model or "gemma" in req_model:
            target_provider = "gemini"
        elif req_model in ["deepseek-chat", "deepseek-reasoner"]:
            target_provider = "deepseek"
        else:
            target_provider = "modelscope"

    # 2. 构建转发请求
    forward_headers = {"Content-Type": "application/json"}
    forward_url = ""

    if target_provider == "modelscope":
        forward_url = "https://api-inference.modelscope.cn/v1/chat/completions"
        forward_headers["Authorization"] = f"Bearer {settings.MODELSCOPE_API_KEY}"
    elif target_provider == "volcengine":
        forward_url = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
        forward_headers["Authorization"] = f"Bearer {settings.VOLCENGINE_API_KEY}"
    elif target_provider == "dashscope":
        forward_url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
        forward_headers["Authorization"] = f"Bearer {settings.DASHSCOPE_API_KEY}"
    elif target_provider == "deepseek":
        forward_url = "https://api.deepseek.com/chat/completions"
        forward_headers["Authorization"] = f"Bearer {settings.DEEPSEEK_API_KEY}"
    elif target_provider == "siliconflow":
        forward_url = "https://api.siliconflow.cn/v1/chat/completions"
        forward_headers["Authorization"] = f"Bearer {settings.SILICONFLOW_API_KEY}"
    elif target_provider == "gemini":
        base = settings.GEMINI_BASE_URL.rstrip("/") if settings.GEMINI_BASE_URL else "https://generativelanguage.googleapis.com"
        forward_url = f"{base}/v1beta/openai/chat/completions"
        forward_headers["Authorization"] = f"Bearer {settings.GEMINI_API_KEY}"

    body["model"] = target_model

    # 对国内平台直连，避免被 socks 代理误拦截
    client_kwargs = {"timeout": 60.0}
    if target_provider in ["dashscope", "volcengine", "modelscope", "deepseek", "siliconflow"]:
        client_kwargs["proxy"] = None

    client = httpx.AsyncClient(**client_kwargs)

    if is_stream:
        async def stream_generator():
            try:
                async with client.stream("POST", forward_url, headers=forward_headers, json=body) as resp:
                    async for chunk in resp.aiter_bytes():
                        yield chunk
            finally:
                await client.aclose()

        return StreamingResponse(stream_generator(), media_type="text/event-stream")
    else:
        try:
            resp = await client.post(forward_url, headers=forward_headers, json=body)
            await client.aclose()
            return JSONResponse(status_code=resp.status_code, content=resp.json())
        except Exception as e:
            await client.aclose()
            raise HTTPException(status_code=500, detail=f"Proxy forwarding failed: {str(e)}")

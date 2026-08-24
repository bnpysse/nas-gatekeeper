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
from ...core.estimator import estimator
from ...core.budget_guard import budget_guard

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
            # 火山方舟 1:1 满额循环主力 (受 180万安全水位硬锁保护)
            {"id": "deepseek-v4-pro", "object": "model", "owned_by": "volcengine"},
            {"id": "glm-5.2", "object": "model", "owned_by": "volcengine"},
            {"id": "deepseek-v4-flash", "object": "model", "owned_by": "volcengine"},
            # 硅基流动 0元永久免费保底池
            {"id": "deepseek-ai/DeepSeek-V3", "object": "model", "owned_by": "siliconflow"},
            {"id": "deepseek-v3", "object": "model", "owned_by": "siliconflow"},
            {"id": "BAAI/bge-m3", "object": "model", "owned_by": "siliconflow"},
            {"id": "FunAudioLLM/SenseVoiceSmall", "object": "model", "owned_by": "siliconflow"},
            # 百炼与开源阵列
            {"id": "deepseek-ai/DeepSeek-V4-Pro", "object": "model", "owned_by": "modelscope"},
            {"id": "gemini-2.5-flash", "object": "model", "owned_by": "gemini"},
            {"id": "deepseek-chat", "object": "model", "owned_by": "deepseek"},
        ]
    }

@router.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """OpenAI 兼容对话补全代理，内置 TokenGate 2.0 事前预算硬锁与自动级联分流"""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    req_model = body.get("model", "auto").strip()
    is_stream = body.get("stream", False)
    messages = body.get("messages", [])
    max_tokens = body.get("max_tokens", 2500)

    # 1. 事前 Token 测算
    est_info = estimator.estimate_messages_tokens(messages, max_tokens)
    est_total = est_info["total_tokens_est"]

    # 2. 别名与平台解析
    target_provider = "siliconflow"
    target_model = req_model
    alias = req_model

    volc_map = {
        "deepseek-v4-pro": settings.VOLCENGINE_ENDPOINT_DEEPSEEK_PRO,
        "deepseek-v4": settings.VOLCENGINE_ENDPOINT_DEEPSEEK_PRO,
        "glm-5.2": settings.VOLCENGINE_ENDPOINT_GLM,
        "glm": settings.VOLCENGINE_ENDPOINT_GLM,
        "deepseek-v4-flash": settings.VOLCENGINE_ENDPOINT_DEEPSEEK_FLASH,
        "flash": settings.VOLCENGINE_ENDPOINT_DEEPSEEK_FLASH,
    }

    if req_model.lower() in volc_map:
        target_provider = "volcengine"
        target_model = volc_map[req_model.lower()]
        alias = req_model.lower()
    elif req_model.startswith("ep-"):
        target_provider = "volcengine"
        target_model = req_model
        alias = req_model
    elif req_model in ["doubao", "doubao-evolving", settings.VOLCENGINE_ENDPOINT_DOUBAO]:
        # 豆包被拉黑，直接强制改道硅基流动 DeepSeek-V3
        target_provider = "siliconflow"
        target_model = "deepseek-ai/DeepSeek-V3"
        alias = "deepseek-v3"
    elif req_model in ["auto", "daily_first", "max_capability", "expiring_first"]:
        target_provider = "volcengine"
        target_model = settings.VOLCENGINE_ENDPOINT_DEEPSEEK_PRO
        alias = "deepseek-v4-pro"
    elif "deepseek-v3" in req_model.lower() or "siliconflow" in req_model.lower():
        target_provider = "siliconflow"
        target_model = "deepseek-ai/DeepSeek-V3"
        alias = "deepseek-v3"
    else:
        target_provider = "siliconflow"
        target_model = "deepseek-ai/DeepSeek-V3"
        alias = "deepseek-v3"

    # 3. 事前安全水位硬锁判定
    if target_provider == "volcengine":
        allowed, _, _, _, reason = budget_guard.can_allocate(alias, est_total)
        if not allowed:
            # 触顶熔断，自动安全改道 SiliconFlow DeepSeek-V3 (0元免费)
            target_provider = "siliconflow"
            target_model = "deepseek-ai/DeepSeek-V3"
            alias = "deepseek-v3 (熔断改道)"

    # 4. 构建转发端点
    def get_forward_params(provider: str, model_name: str):
        if provider == "volcengine":
            url = f"{getattr(settings, 'VOLCENGINE_BASE_URL', 'https://ark.cn-beijing.volces.com/api/v3')}/chat/completions"
            hdrs = {"Authorization": f"Bearer {settings.VOLCENGINE_API_KEY}", "Content-Type": "application/json"}
        else:
            url = "https://api.siliconflow.cn/v1/chat/completions"
            hdrs = {"Authorization": f"Bearer {settings.SILICONFLOW_API_KEY}", "Content-Type": "application/json"}
        return url, hdrs

    forward_url, forward_headers = get_forward_params(target_provider, target_model)
    body["model"] = target_model

    client = httpx.AsyncClient(timeout=180.0, trust_env=False)

    if is_stream:
        async def stream_generator():
            accumulated = ""
            current_prov = target_provider
            current_mod = target_model
            current_alias = alias
            try:
                async with client.stream("POST", forward_url, headers=forward_headers, json=body) as resp:
                    if resp.status_code == 403 and current_prov == "volcengine":
                        # 触发自动容灾至 SiliconFlow
                        sf_url, sf_hdrs = get_forward_params("siliconflow", "deepseek-ai/DeepSeek-V3")
                        body["model"] = "deepseek-ai/DeepSeek-V3"
                        current_prov = "siliconflow"
                        current_alias = "deepseek-v3 (403容灾)"
                        async with client.stream("POST", sf_url, headers=sf_hdrs, json=body) as sf_resp:
                            sf_resp.raise_for_status()
                            async for chunk in sf_resp.aiter_bytes():
                                yield chunk
                        return

                    resp.raise_for_status()
                    async for chunk in resp.aiter_bytes():
                        yield chunk
            finally:
                await client.aclose()

        return StreamingResponse(stream_generator(), media_type="text/event-stream")
    else:
        try:
            resp = await client.post(forward_url, headers=forward_headers, json=body)
            if resp.status_code == 403 and target_provider == "volcengine":
                # 403 自动容灾
                sf_url, sf_hdrs = get_forward_params("siliconflow", "deepseek-ai/DeepSeek-V3")
                body["model"] = "deepseek-ai/DeepSeek-V3"
                resp = await client.post(sf_url, headers=sf_hdrs, json=body)
                target_provider = "siliconflow"
                alias = "deepseek-v3 (403容灾)"

            await client.aclose()
            data = resp.json()
            if resp.status_code == 200:
                usage = data.get("usage", {})
                tot = usage.get("total_tokens", est_total)
                budget_guard.record_usage(
                    model_key=alias,
                    actual_tokens=tot,
                    prompt_tokens=usage.get("prompt_tokens", est_info["prompt_tokens_est"]),
                    completion_tokens=usage.get("completion_tokens", max_tokens),
                    provider=target_provider
                )
            return JSONResponse(status_code=resp.status_code, content=data)
        except Exception as e:
            await client.aclose()
            raise HTTPException(status_code=500, detail=f"TokenGate 2.0 转发异常: {str(e)}")

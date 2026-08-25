import json
import httpx
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from ...core.config import settings
from ...core.cascading_router import cascading_router
from ...core.estimator import estimator
from ...core.budget_guard import budget_guard

router = APIRouter(tags=["OpenAI Proxy"])

@router.get("/v1/models")
async def list_openai_models():
    """OpenAI 兼容模型列表 (全网 0 元免费与递减水库矩阵)"""
    return {
        "object": "list",
        "data": [
            {"id": "auto", "object": "model", "owned_by": "tokengate", "description": "智能全自动最优级联路由"},
            {"id": "reasoning", "object": "model", "owned_by": "tokengate", "description": "深度推理/架构拓扑 (Qwen Max ➔ V4-Pro ➔ Kimi K3)"},
            {"id": "distill", "object": "model", "owned_by": "tokengate", "description": "章节 20% 去水提炼 (Qwen Plus ➔ GLM-5.2 ➔ Qwen3 235B)"},
            {"id": "fast", "object": "model", "owned_by": "tokengate", "description": "极速清洗/速读 (Qwen Flash ➔ DS Flash)"},
            # 阿里百炼临期抢跑包
            {"id": "qwen3.7-max-2026-06-08", "object": "model", "owned_by": "dashscope"},
            {"id": "qwen3.7-plus", "object": "model", "owned_by": "dashscope"},
            {"id": "kimi-k3", "object": "model", "owned_by": "dashscope"},
            {"id": "qwen3.8-27b", "object": "model", "owned_by": "dashscope"},
            # 火山方舟递减型水库 (10:08 结算循环)
            {"id": "glm-5.2", "object": "model", "owned_by": "volcengine"},
            {"id": "deepseek-v4-pro", "object": "model", "owned_by": "volcengine"},
            {"id": "deepseek-v4-flash", "object": "model", "owned_by": "volcengine"},
            # 魔搭社区 2000次/天 开源旗舰
            {"id": "modelscope/deepseek-ai/DeepSeek-V4-Pro", "object": "model", "owned_by": "modelscope"},
            {"id": "modelscope/Qwen/Qwen3-235B-A22B-Thinking-2507", "object": "model", "owned_by": "modelscope"},
            {"id": "modelscope/MiniMax/MiniMax-M1-80k", "object": "model", "owned_by": "modelscope"},
            # 硅基流动 0元无限保底
            {"id": "deepseek-ai/DeepSeek-V3", "object": "model", "owned_by": "siliconflow"},
            {"id": "BAAI/bge-m3", "object": "model", "owned_by": "siliconflow"},
            {"id": "BAAI/bge-reranker-v2-m3", "object": "model", "owned_by": "siliconflow"},
            {"id": "FunAudioLLM/SenseVoiceSmall", "object": "model", "owned_by": "siliconflow"},
        ]
    }

@router.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """OpenAI 兼容对话补全代理，统一由 TokenGate 中央仲裁路由"""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    req_model = body.get("model", "auto").strip()
    is_stream = body.get("stream", False)
    messages = body.get("messages", [])
    temperature = body.get("temperature", 0.3)
    max_tokens = body.get("max_tokens", 2500)

    # 映射任务类型
    task_type = "general"
    if req_model in ["distill", "去水", "提炼"] or "distill" in req_model.lower():
        task_type = "distill"
    elif req_model in ["reasoning", "reason", "推演", "出题", "思考"] or "reason" in req_model.lower():
        task_type = "reasoning"
    elif req_model in ["fast", "clean", "flash", "清洗", "速读"] or "fast" in req_model.lower():
        task_type = "fast_clean"

    preferred_model = None if req_model in ["auto", "distill", "reasoning", "fast", "general"] else req_model

    if is_stream:
        async def stream_wrapper():
            async for chunk_str in cascading_router.execute_stream(
                messages=messages,
                task_type=task_type,
                temperature=temperature,
                max_tokens=max_tokens,
                preferred_model=preferred_model
            ):
                # 包装为标准 OpenAI SSE Chunk
                sse_data = {
                    "id": "chatcmpl-tg",
                    "object": "chat.completion.chunk",
                    "created": 1787673600,
                    "model": req_model,
                    "choices": [{"index": 0, "delta": {"content": chunk_str}, "finish_reason": None}]
                }
                yield f"data: {json.dumps(sse_data, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(stream_wrapper(), media_type="text/event-stream")
    else:
        try:
            res = await cascading_router.execute_chat(
                messages=messages,
                task_type=task_type,
                temperature=temperature,
                max_tokens=max_tokens,
                preferred_model=preferred_model
            )
            
            raw_response = res.get("raw_response", {})
            if raw_response and "choices" in raw_response:
                return JSONResponse(status_code=200, content=raw_response)

            # 标准 OpenAI Response 格式包装
            content = res.get("content", "")
            return JSONResponse(
                status_code=200,
                content={
                    "id": "chatcmpl-tokengate-hub",
                    "object": "chat.completion",
                    "created": 1787673600,
                    "model": res.get("model_used", req_model),
                    "provider": res.get("provider", "tokengate"),
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": content},
                            "finish_reason": "stop"
                        }
                    ],
                    "usage": {
                        "prompt_tokens": res.get("tokens_used", 0) // 2,
                        "completion_tokens": res.get("tokens_used", 0) // 2,
                        "total_tokens": res.get("tokens_used", 0)
                    }
                }
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"TokenGate 中央网关调度异常: {str(e)}")

@router.post("/v1/embeddings")
async def create_embeddings(request: Request):
    """OpenAI 兼容向量化接口 (优先调用硅基流动 BGE-M3 0元模型)"""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    url = "https://api.siliconflow.cn/v1/embeddings"
    headers = {
        "Authorization": f"Bearer {settings.SILICONFLOW_API_KEY}",
        "Content-Type": "application/json"
    }
    if "model" not in body:
        body["model"] = "BAAI/bge-m3"

    try:
        async with httpx.AsyncClient(timeout=60.0, trust_env=False) as client:
            resp = await client.post(url, headers=headers, json=body)
            resp.raise_for_status()
            return JSONResponse(status_code=200, content=resp.json())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"TokenGate 向量化代理异常: {str(e)}")

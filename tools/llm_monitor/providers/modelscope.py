import os
import time
import requests

def check_modelscope():
    api_key = os.environ.get("MODELSCOPE_API_KEY", "ms-2b894ffd-d72f-4cc8-a09b-6ac8255ffe54")
    if not api_key:
        return {
            "provider": "魔搭社区 (ModelScope)",
            "status": "未配置",
            "active": False,
            "latency_ms": 0,
            "balance_info": "未检测到 MODELSCOPE_API_KEY",
            "free_models": [],
            "rate_limits": "-",
            "pricing_type": "Serverless 免费推理 API"
        }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    start = time.time()
    try:
        r = requests.get("https://api-inference.modelscope.cn/v1/models", headers=headers, timeout=5)
        latency = int((time.time() - start) * 1000)

        # 核心可用模型精选列表
        free_models = [
            {
                "name": "deepseek-ai/DeepSeek-V4-Pro",
                "context_window": "64K",
                "is_free": True,
                "tier": "免费 · 深度思考 / 旗舰版"
            },
            {
                "name": "deepseek-ai/DeepSeek-V4-Flash-0731",
                "context_window": "64K",
                "is_free": True,
                "tier": "免费 · 极速主升分析"
            },
            {
                "name": "Qwen/Qwen3-235B-A22B",
                "context_window": "128K",
                "is_free": True,
                "tier": "免费 · 2350亿超大旗舰"
            },
            {
                "name": "Qwen/Qwen3-Coder-30B-A3B-Instruct",
                "context_window": "64K",
                "is_free": True,
                "tier": "免费 · 顶级代码专攻"
            },
            {
                "name": "Qwen/Qwen3-VL-235B-A22B-Instruct",
                "context_window": "128K",
                "is_free": True,
                "tier": "免费 · 235B 多模态视觉理解"
            },
            {
                "name": "MiniMax/MiniMax-M1-80k",
                "context_window": "80K",
                "is_free": True,
                "tier": "免费 · 80K长文本+深度思考"
            },
            {
                "name": "Shanghai_AI_Laboratory/Intern-S2-Preview",
                "context_window": "64K",
                "is_free": True,
                "tier": "免费 · 书生旗舰"
            },
            {
                "name": "stepfun-ai/Step-3.5-Flash",
                "context_window": "64K",
                "is_free": True,
                "tier": "免费 · 阶跃星辰极速版"
            }
        ]

        return {
            "provider": "魔搭社区 (ModelScope)",
            "status": "在线 (正常)" if r.status_code == 200 else f"鉴权异常 ({r.status_code})",
            "active": r.status_code == 200,
            "latency_ms": latency,
            "balance_info": f"Serverless 免费推理 (45 个模型池)",
            "free_models": free_models,
            "rate_limits": "Serverless 免费并发",
            "pricing_type": "社区官方免费 Serverless API",
            "models_count": len(free_models)
        }
    except Exception as e:
        return {
            "provider": "魔搭社区 (ModelScope)",
            "status": "连接超时/异常",
            "active": False,
            "latency_ms": int((time.time() - start) * 1000),
            "balance_info": str(e)[:60],
            "free_models": [],
            "rate_limits": "-",
            "pricing_type": "Serverless 免费推理 API"
        }

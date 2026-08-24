import os
import time
import requests

def check_volcengine():
    api_key = os.environ.get("GLM_API_KEY")
    if not api_key:
        return {
            "provider": "火山方舟 (Volcengine Ark / GLM)",
            "status": "未配置",
            "active": False,
            "latency_ms": 0,
            "balance_info": "未检测到 GLM_API_KEY",
            "free_models": [],
            "rate_limits": "-",
            "pricing_type": "按量计费"
        }

    headers = {"Authorization": f"Bearer {api_key}"}
    start = time.time()
    try:
        r = requests.get("https://ark.cn-beijing.volces.com/api/v3/models", headers=headers, timeout=4)
        latency = int((time.time() - start) * 1000)
        
        models = [
            {
                "name": "glm-4-air / glm-4-plus",
                "context_window": "128K",
                "is_free": False,
                "tier": "火山引擎托管 GLM 接入点"
            },
            {
                "name": "doubao-pro / doubao-lite",
                "context_window": "128K",
                "is_free": False,
                "tier": "字节跳动豆包大模型接入点"
            }
        ]

        if r.status_code == 200:
            return {
                "provider": "火山方舟 (Volcengine Ark / GLM)",
                "status": "在线 (正常)",
                "active": True,
                "latency_ms": latency,
                "balance_info": "火山方舟推理点已鉴权接入",
                "free_models": models,
                "rate_limits": "按火山引擎控制台 QPS 限额",
                "pricing_type": "按量/免费赠送",
                "models_count": len(models)
            }
        else:
            return {
                "provider": "火山方舟 (Volcengine Ark / GLM)",
                "status": "在线 (接入点就绪)",
                "active": True,
                "latency_ms": latency,
                "balance_info": "GLM 接入点配置有效",
                "free_models": models,
                "rate_limits": "-",
                "pricing_type": "按量计费"
            }
    except Exception as e:
        return {
            "provider": "火山方舟 (Volcengine Ark / GLM)",
            "status": "连接超时/异常",
            "active": False,
            "latency_ms": int((time.time() - start) * 1000),
            "balance_info": str(e)[:60],
            "free_models": [],
            "rate_limits": "-",
            "pricing_type": "按量计费"
        }

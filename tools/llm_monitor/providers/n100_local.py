import time
import requests

def check_n100():
    url = "http://192.168.2.9:11434/api/tags"
    start = time.time()
    try:
        r = requests.get(url, timeout=2.5)
        latency = int((time.time() - start) * 1000)
        if r.status_code == 200:
            data = r.json()
            raw_models = data.get("models", [])
            models = []
            for m in raw_models:
                name = m.get("name", "")
                details = m.get("details", {})
                params = details.get("parameter_size", "-")
                quant = details.get("quantization_level", "-")
                models.append({
                    "name": name,
                    "context_window": f"{details.get('context_length', 32768) // 1000}K",
                    "is_free": True,
                    "tier": f"本地私有算力 · {params} ({quant}) (100% 永久无限免费)"
                })

            return {
                "provider": "N100 本地私有算力 (Ollama)",
                "status": "局域网在线 (就绪)",
                "active": True,
                "latency_ms": latency,
                "balance_info": "本地硬件裸跑 · 0 Token 成本 · 永久无限调用",
                "free_models": models,
                "rate_limits": "无限制 (受限于 N100 硬件推理吞吐)",
                "pricing_type": "100% 永久免费无限",
                "models_count": len(models)
            }
        else:
            return {
                "provider": "N100 本地私有算力 (Ollama)",
                "status": f"服务响应异常 ({r.status_code})",
                "active": False,
                "latency_ms": latency,
                "balance_info": "Ollama 端口响应异常",
                "free_models": [],
                "rate_limits": "-",
                "pricing_type": "本地私有"
            }
    except Exception as e:
        return {
            "provider": "N100 本地私有算力 (Ollama)",
            "status": "局域网离线/不可达",
            "active": False,
            "latency_ms": int((time.time() - start) * 1000),
            "balance_info": "请确认 N100 (192.168.2.9:11434) 处于开机状态",
            "free_models": [],
            "rate_limits": "-",
            "pricing_type": "本地私有"
        }

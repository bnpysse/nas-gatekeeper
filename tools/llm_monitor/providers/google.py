import os
import time
import requests

def check_google():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return {
            "provider": "Google AI Studio (Gemini)",
            "status": "未配置",
            "active": False,
            "latency_ms": 0,
            "balance_info": "未检测到 GEMINI_API_KEY",
            "free_models": [],
            "rate_limits": "Flash 系列 15 RPM / 1500 RPD 每日免费重置",
            "pricing_type": "永久每日免费重置"
        }

    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    start = time.time()
    try:
        r = requests.get(url, timeout=4)
        latency = int((time.time() - start) * 1000)
        if r.status_code == 200:
            data = r.json()
            models = data.get("models", [])
            # Filter models capable of generateContent
            chat_models = []
            for m in models:
                name = m.get("name", "").replace("models/", "")
                methods = m.get("supportedGenerationMethods", [])
                input_limit = m.get("inputTokenLimit", 0)
                if "generateContent" in methods:
                    # Highlight recommended free models
                    is_free_tier = any(x in name.lower() for x in ["flash", "lite", "gemma"])
                    chat_models.append({
                        "name": name,
                        "context_window": f"{input_limit // 1000}K" if input_limit else "1.0M",
                        "is_free": is_free_tier,
                        "tier": "免费主力 (1500次/天)" if is_free_tier else "高阶试用 (50次/天)"
                    })

            # Sort free models first
            chat_models.sort(key=lambda x: (not x["is_free"], x["name"]))

            return {
                "provider": "Google AI Studio (Gemini)",
                "status": "在线 (正常)",
                "active": True,
                "latency_ms": latency,
                "balance_info": "永久免费配额 (每日自动重置)",
                "free_models": chat_models,
                "rate_limits": "Flash: 15 RPM / 100万 TPM / 1500 RPD；Pro: 2 RPM / 50 RPD",
                "pricing_type": "每日免费重置",
                "models_count": len(chat_models)
            }
        elif r.status_code == 503:
            return {
                "provider": "Google AI Studio (Gemini)",
                "status": "拥堵 (503 High Demand)",
                "active": False,
                "latency_ms": latency,
                "balance_info": "Google 公共免费集群暂时过载，建议稍后重试或切换备用端点",
                "free_models": [],
                "rate_limits": "Flash: 1500 RPD 免费",
                "pricing_type": "每日免费重置"
            }
        else:
            return {
                "provider": "Google AI Studio (Gemini)",
                "status": f"异常 ({r.status_code})",
                "active": False,
                "latency_ms": latency,
                "balance_info": r.text[:80],
                "free_models": [],
                "rate_limits": "-",
                "pricing_type": "每日免费重置"
            }
    except Exception as e:
        return {
            "provider": "Google AI Studio (Gemini)",
            "status": "连接超时/异常",
            "active": False,
            "latency_ms": int((time.time() - start) * 1000),
            "balance_info": str(e)[:60],
            "free_models": [],
            "rate_limits": "-",
            "pricing_type": "每日免费重置"
        }

import os
import time
import requests

def check_deepseek():
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        return {
            "provider": "DeepSeek 官方 API",
            "status": "未配置",
            "active": False,
            "latency_ms": 0,
            "balance_info": "未检测到 DEEPSEEK_API_KEY",
            "free_models": [],
            "rate_limits": "-",
            "pricing_type": "按量计费 (超高性价比)"
        }

    headers = {"Authorization": f"Bearer {api_key}"}
    start = time.time()
    try:
        r = requests.get("https://api.deepseek.com/user/balance", headers=headers, timeout=4)
        latency = int((time.time() - start) * 1000)
        if r.status_code == 200:
            data = r.json()
            balance_infos = data.get("balance_infos", [])
            total = "0.00"
            granted = "0.00"
            topped_up = "0.00"
            currency = "CNY"
            if balance_infos:
                b = balance_infos[0]
                total = b.get("total_balance", "0.00")
                granted = b.get("granted_balance", "0.00")
                topped_up = b.get("topped_up_balance", "0.00")
                currency = b.get("currency", "CNY")

            models = [
                {
                    "name": "deepseek-chat (DeepSeek-V3)",
                    "context_window": "64K",
                    "is_free": False,
                    "tier": "输入 ¥1/M, 输出 ¥2/M (极速高智力)"
                },
                {
                    "name": "deepseek-reasoner (DeepSeek-R1)",
                    "context_window": "64K",
                    "is_free": False,
                    "tier": "输入 ¥4/M, 输出 ¥16/M (深度思维链)"
                }
            ]

            balance_str = f"¥{total} {currency} (充值: ¥{topped_up} / 赠送: ¥{granted})"
            return {
                "provider": "DeepSeek 官方 API",
                "status": "在线 (正常)",
                "active": True,
                "latency_ms": latency,
                "balance_info": balance_str,
                "raw_balance": float(total) if total.replace(".", "", 1).isdigit() else 0.0,
                "free_models": models,
                "rate_limits": "无调用频次硬限制，按余额扣除",
                "pricing_type": "实时余额计费",
                "models_count": len(models)
            }
        else:
            return {
                "provider": "DeepSeek 官方 API",
                "status": f"鉴权异常 ({r.status_code})",
                "active": False,
                "latency_ms": latency,
                "balance_info": r.text[:80],
                "free_models": [],
                "rate_limits": "-",
                "pricing_type": "实时余额计费"
            }
    except Exception as e:
        return {
            "provider": "DeepSeek 官方 API",
            "status": "连接超时/异常",
            "active": False,
            "latency_ms": int((time.time() - start) * 1000),
            "balance_info": str(e)[:60],
            "free_models": [],
            "rate_limits": "-",
            "pricing_type": "实时余额计费"
        }

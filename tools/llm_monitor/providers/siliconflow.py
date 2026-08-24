import os
import time
import requests

def check_siliconflow():
    api_key = os.environ.get("SILICONFLOW_API_KEY")
    if not api_key:
        return {
            "provider": "硅基流动 (SiliconFlow)",
            "status": "未配置",
            "active": False,
            "latency_ms": 0,
            "balance_info": "未检测到 SILICONFLOW_API_KEY",
            "free_models": [],
            "rate_limits": "-",
            "pricing_type": "0元免费专区 + 赠送金"
        }

    headers = {"Authorization": f"Bearer {api_key}"}
    start = time.time()
    try:
        r_user = requests.get("https://api.siliconflow.cn/v1/user/info", headers=headers, timeout=4)
        latency = int((time.time() - start) * 1000)
        
        balance_str = "¥0.00"
        if r_user.status_code == 200:
            user_data = r_user.json().get("data", {})
            total = user_data.get("totalBalance", "0")
            charge = user_data.get("chargeBalance", "0")
            balance_str = f"¥{total} CNY (充值: ¥{charge})"
        
        # Free models directory on SiliconFlow
        free_models = [
            {
                "name": "Qwen/Qwen2.5-Coder-7B-Instruct",
                "context_window": "32K",
                "is_free": True,
                "tier": "0元专区 · 编程首选 (完全免费)"
            },
            {
                "name": "deepseek-ai/DeepSeek-R1-Distill-Qwen-7B",
                "context_window": "32K",
                "is_free": True,
                "tier": "0元专区 · R1 深度思考 (完全免费)"
            },
            {
                "name": "deepseek-ai/DeepSeek-R1-Distill-Qwen-8B",
                "context_window": "32K",
                "is_free": True,
                "tier": "0元专区 · R1 蒸馏 8B (完全免费)"
            },
            {
                "name": "Qwen/Qwen2.5-7B-Instruct",
                "context_window": "32K",
                "is_free": True,
                "tier": "0元专区 · 通用对话 (完全免费)"
            },
            {
                "name": "THUDM/glm-4-9b-chat",
                "context_window": "32K",
                "is_free": True,
                "tier": "0元专区 · 智谱清言 (完全免费)"
            },
            {
                "name": "internlm/internlm2_5-7b-chat",
                "context_window": "32K",
                "is_free": True,
                "tier": "0元专区 · 书生浦语 (完全免费)"
            },
            {
                "name": "meta-llama/Meta-Llama-3.1-8B-Instruct",
                "context_window": "32K",
                "is_free": True,
                "tier": "0元专区 · Llama3 英文/通用 (完全免费)"
            },
            {
                "name": "deepseek-ai/DeepSeek-V3",
                "context_window": "64K",
                "is_free": False,
                "tier": "按量付费 (¥2/M 满血 V3)"
            },
            {
                "name": "deepseek-ai/DeepSeek-R1",
                "context_window": "64K",
                "is_free": False,
                "tier": "按量付费 (¥16/M 满血 R1)"
            }
        ]

        return {
            "provider": "硅基流动 (SiliconFlow)",
            "status": "在线 (正常)" if r_user.status_code == 200 else f"鉴权异常 ({r_user.status_code})",
            "active": r_user.status_code == 200,
            "latency_ms": latency,
            "balance_info": balance_str,
            "free_models": free_models,
            "rate_limits": "0元专区免费模型无硬扣费，QPS 限速按等级",
            "pricing_type": "0元永久免费专区",
            "models_count": len(free_models)
        }
    except Exception as e:
        return {
            "provider": "硅基流动 (SiliconFlow)",
            "status": "连接超时/异常",
            "active": False,
            "latency_ms": int((time.time() - start) * 1000),
            "balance_info": str(e)[:60],
            "free_models": [],
            "rate_limits": "-",
            "pricing_type": "0元永久免费专区"
        }

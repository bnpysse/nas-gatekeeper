import os
import time
import requests

def check_dashscope():
    api_key = os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("QWEN_API_KEY")
    if not api_key:
        return {
            "provider": "阿里百炼 (DashScope / 通义千问)",
            "status": "未配置",
            "active": False,
            "latency_ms": 0,
            "balance_info": "未检测到 DASHSCOPE_API_KEY",
            "free_models": [],
            "rate_limits": "-",
            "pricing_type": "限免模型 + 赠送 Token"
        }

    headers = {"Authorization": f"Bearer {api_key}"}
    start = time.time()
    try:
        r = requests.get("https://dashscope.aliyuncs.com/api/v1/quotas?page_size=30", headers=headers, timeout=4)
        latency = int((time.time() - start) * 1000)
        
        workspace_id = ""
        quotas_map = {}
        if r.status_code == 200:
            data = r.json().get("output", {})
            quotas_list = data.get("quotas", [])
            for q in quotas_list:
                m_name = q.get("model", "")
                workspace_id = q.get("workspace_id", workspace_id)
                m_lim = q.get("model_limit", {}) or {}
                usage_lim = m_lim.get("usage_limit")
                req_lim = m_lim.get("request_limit")
                tpm_str = f"{usage_lim // 1000}K TPM" if usage_lim else "-"
                rpm_str = f"{req_lim} RPM" if req_lim else "-"
                quotas_map[m_name] = f"{tpm_str} / {rpm_str}"

        # Key model showcase with live quota limits
        featured = [
            {
                "name": "qwen3.7-flash / qwen-flash",
                "context_window": "128K",
                "is_free": False,
                "tier": f"限额: {quotas_map.get('qwen3.7-flash', '5000K TPM')} (新用户各模型送 100万 Token)"
            },
            {
                "name": "qwen3.7-plus / qwen-plus",
                "context_window": "128K",
                "is_free": False,
                "tier": f"限额: {quotas_map.get('qwen3.7-plus', '2500K TPM')} (千问主力 · 均衡高智力)"
            },
            {
                "name": "qwen3.8-max / qwen-max",
                "context_window": "32K",
                "is_free": False,
                "tier": f"限额: {quotas_map.get('qwen3.8-max', '500K TPM')} (千问顶配 · 复杂推理)"
            },
            {
                "name": "deepseek-v3",
                "context_window": "64K",
                "is_free": False,
                "tier": "百炼托管 DeepSeek V3 满血版"
            },
            {
                "name": "deepseek-r1",
                "context_window": "64K",
                "is_free": False,
                "tier": "百炼托管 DeepSeek R1 满血版"
            }
        ]

        ws_label = f"Workspace: {workspace_id[:12]}... (含 480+ 模型配额)" if workspace_id else "已激活百炼服务"

        return {
            "provider": "阿里百炼 (DashScope / 通义千问)",
            "status": "在线 (正常)" if r.status_code == 200 else f"鉴权异常 ({r.status_code})",
            "active": r.status_code == 200,
            "latency_ms": latency,
            "balance_info": f"{ws_label} · 免费额度见控制台",
            "free_models": featured,
            "rate_limits": "每个新模型激活通常赠送 100万 Token (有效期 90 天)",
            "pricing_type": "新模型赠 100万 Token",
            "models_count": len(featured)
        }
    except Exception as e:
        return {
            "provider": "阿里百炼 (DashScope / 通义千问)",
            "status": "连接超时/异常",
            "active": False,
            "latency_ms": int((time.time() - start) * 1000),
            "balance_info": str(e)[:60],
            "free_models": [],
            "rate_limits": "-",
            "pricing_type": "按量/包月"
        }

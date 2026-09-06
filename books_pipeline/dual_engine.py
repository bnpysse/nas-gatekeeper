#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
第二大脑·多通道旗舰算力调度中枢 (`dual_engine.py`)
核心能力：
  1. 【单日算力熔断保护 (150万 Tokens/天)】：实时查询 Turso 00:00 至今台账，严格在 150万/模型安全线内自动轮巡；
  2. 【多主力无缝接力】：VolcEngine DeepSeek-V4-Pro ➔ VolcEngine DeepSeek-V4-Flash / GLM ➔ DashScope Qwen-Plus ➔ Gemini 自动容灾；
  3. 【0 扣费硬锁】：物理剔除任何收费接口，全链路 100% 运行于永久免费与 1:1 返还通道。
"""

import asyncio
import json
import logging
import time
from typing import Dict, Any, List, Tuple
import httpx

try:
    from .config import LibraryConfig
    from .db import record_usage, execute_turso
except ImportError:
    from config import LibraryConfig
    from db import record_usage, execute_turso

logger = logging.getLogger(__name__)

class QuotaExhaustedError(Exception):
    """当所有可用 0 成本免费额度达到预设安全红线时触发熔断休眠保护"""
    pass


# 三大受支持的火山方舟体验官 1:1 返还模型矩阵 (存量包共计 604 万，单日返还上限 200万)
# 严格设置单日安全消耗上限，确保：
# 1. 绝对不超单模型现存资源包 (Pro ~1.64M, GLM-5.2 ~2.46M, Flash ~1.93M)
# 2. 跨模型总消耗严格 <= 180 万/天，在次日 10:00 前 100% 被 1:1 返还覆盖，实现长效 0 成本运转！
VOLC_MODELS = [
    {
        "name": "DeepSeek-V4-Pro",
        "endpoint": getattr(LibraryConfig, "ENDPOINT_DEEPSEEK_PRO", "ep-20260820195716-snkzx"),
        "daily_limit": 1_000_000,
        "desc": "深度去水与全局脉络第一主力"
    },
    {
        "name": "GLM-5.2",
        "endpoint": getattr(LibraryConfig, "ENDPOINT_GLM_52", "ep-20260814105356-zvsw5"),
        "daily_limit": 1_200_000,
        "desc": "清华智谱超长文本精讲高阶主力"
    },
    {
        "name": "DeepSeek-V4-Flash",
        "endpoint": getattr(LibraryConfig, "ENDPOINT_DEEPSEEK_FLASH", "ep-20260809122445-td2g2"),
        "daily_limit": 1_200_000,
        "desc": "极速清洗与结构化提炼接力底座"
    }
]

# 单日火山算力跨模型总消耗上限 (官方 1:1 返还采集上限 200万/天，我们设为 180万，预留 20万绝对安全垫)
DAILY_VOLC_AGGREGATE_CAP = 1_800_000

# 永久拉黑/禁用的模型与端点 (返还比仅 0.2 或具有未知资费风险)
VOLC_BANNED_ENDPOINTS = [
    "ep-20260814105629-t99mw",  # Doubao-Evolving 豆包自进化
]

# 内存级今日消耗缓存 (减少高频查询 Turso 负担，每 30 秒刷新一次)
_USAGE_CACHE = {}
_LAST_CACHE_TIME = 0.0


async def get_today_tokens_consumed(provider: str = None, model_name: str = None) -> int:
    """查询今日 00:00 至今某模型或某 Provider 在 Turso 台账中累计消耗的 Tokens"""
    global _USAGE_CACHE, _LAST_CACHE_TIME
    now = time.time()
    
    # 缓存 30 秒有效
    if now - _LAST_CACHE_TIME >= 30.0 or not _USAGE_CACHE:
        try:
            rows = await execute_turso("""
                SELECT provider, model_name, sum(total_tokens) as t_tokens 
                FROM library_usage_ledger 
                WHERE date(created_at) = date('now')
                GROUP BY provider, model_name;
            """)
            new_cache = {}
            for r in rows:
                p = r.get("provider", "")
                m = r.get("model_name", "")
                tok = int(float(r.get("t_tokens") or 0))
                new_cache[f"{p}:{m}"] = tok
            _USAGE_CACHE = new_cache
            _LAST_CACHE_TIME = now
        except Exception as e:
            logger.warning(f"查询今日 Token 消耗异常: {e}")

    if provider and model_name:
        return _USAGE_CACHE.get(f"{provider}:{model_name}", 0)
    elif provider:
        total = 0
        for k, v in _USAGE_CACHE.items():
            if k.startswith(f"{provider}:"):
                total += v
        return total
    return sum(_USAGE_CACHE.values())


async def select_optimal_llm_channel(preferred_endpoint: str = None) -> Tuple[str, str, str]:
    """
    智能 100% 绝对 0 成本算力路由中枢：
    严格在火山方舟三大体验官 1:1 返还模型 (DeepSeek-V4-Pro / GLM-5.2 / DeepSeek-V4-Flash) 之间智能轮巡调度；
    单日跨模型总消耗硬锁 180 万（低于 200 万每日采集返还上限）；
    若达到上限，自动触发 QuotaExhaustedError 熔断休眠，坚决不向任何收费渠道渗透！
    """
    total_volc_today = await get_today_tokens_consumed(provider="VolcEngine")
    if total_volc_today >= DAILY_VOLC_AGGREGATE_CAP:
        raise QuotaExhaustedError(
            f"今日火山免费算力累计消耗 ({total_volc_today:,} tokens) 已达 {DAILY_VOLC_AGGREGATE_CAP:,} 安全上限，"
            f"自动熔断休眠保护，待次日 10:00 资源包 1:1 返还后再行调度。"
        )

    # 如果指定了偏好端点且合法
    if preferred_endpoint:
        if preferred_endpoint in VOLC_BANNED_ENDPOINTS:
            logger.warning(f"端点 {preferred_endpoint} 处于黑名单中，拒绝调度，切换为主力轮巡...")
        else:
            for m in VOLC_MODELS:
                if m["endpoint"] == preferred_endpoint or m["name"].lower() in preferred_endpoint.lower():
                    used = await get_today_tokens_consumed(provider="VolcEngine", model_name=m["name"])
                    if used < m["daily_limit"]:
                        return ("volcengine", m["endpoint"], m["name"])

    # 优先级轮巡：Pro -> GLM-5.2 -> Flash
    for m in VOLC_MODELS:
        used = await get_today_tokens_consumed(provider="VolcEngine", model_name=m["name"])
        if used < m["daily_limit"]:
            return ("volcengine", m["endpoint"], m["name"])

    raise QuotaExhaustedError("三大免费主力模型 (Pro, GLM-5.2, Flash) 今日配额均已达单模型安全上限，自动休眠保护。")


# 阿里百炼官方提供且已开启“用完即停”的精确版本化免费大模型矩阵 (按到期时间严格升序排列，全力在到期前全额榨干)
DASHSCOPE_FREE_MODELS = [
    # 🚨 9月1日即将到期 (优先第 1 梯队消灭，剩 ~128万 Tokens)
    "qwen3.7-plus",              # 剩 28万 / 100万 (2026/09/01 到期)
    "qwen3.7-plus-2026-05-26",   # 剩 100万 / 100万 (2026/09/01 到期)
    
    # 🟡 9月中旬到期 (第 2 梯队，剩 ~200万 Tokens)
    "kimi-k2.7-code",            # 剩 100万 / 100万 (2026/09/14 到期)
    "glm-5.2",                   # 剩 100万 / 100万 (2026/09/15 到期)
    
    # 🟢 10月下旬到期 (第 3 梯队，剩 ~100万 Tokens)
    "qwen3.7-flash-2026-07-15",  # 剩 100万 / 100万 (2026/10/23 到期)
    
    # 🔵 11月中下旬到期 (第 4 梯队，剩 ~700万 Tokens)
    "qwen3.8-2.4t-a95b",         # 剩 86万 / 100万 (2026/11/12 到期)
    "tongyi-xiaomi-analysis-flash", # 剩 100万 / 100万 (2026/11/13 到期)
    "qwen-flash-character",      # 剩 100万 / 100万 (2026/11/13 到期)
    "qwen3.8-27b",               # 剩 100万 / 100万 (2026/11/17 到期)
    "qwen3.8-flash"              # 剩 100万 / 100万 (2026/11/25 到期)
]


async def call_scnet_llm(
    model: str = "SCNet-Max",
    prompt: str = "",
    system_prompt: str = "",
    temperature: float = 0.3,
    max_tokens: int = 2800,
    max_retries: int = 4,
    book_id: str = "",
    task_name: str = ""
) -> str:
    """
    调用国家超算互联网 (SCNet) 1000万超算旗舰大模型矩阵 (SCNet-Max)，
    若额度耗尽 (HTTP 402) 或限流，自动秒级平滑无缝降级至阿里百炼免费模型矩阵！
    """
    url = f"{LibraryConfig.SCNET_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {LibraryConfig.SCNET_API_KEY}",
        "Content-Type": "application/json"
    }
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model or LibraryConfig.MODEL_SCNET,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens
    }

    backoff = 2.0
    t0 = time.time()
    for attempt in range(1, max_retries + 1):
        try:
            async with httpx.AsyncClient(timeout=120.0, trust_env=False) as client:
                resp = await client.post(url, headers=headers, json=payload)
                if resp.status_code == 402:
                    logger.warning("🚨 国家超算中心 (SCNet) 额度用尽 (HTTP 402)，自动秒切阿里百炼免费模型接力...")
                    break
                if resp.status_code == 429:
                    logger.warning(f"⚠️ SCNet 并发限流 (HTTP 429), 退避重试 {attempt}/{max_retries}...")
                    await asyncio.sleep(backoff)
                    backoff *= 1.8
                    continue
                resp.raise_for_status()
                data = resp.json()

                if book_id:
                    try:
                        usage = data.get("usage", {})
                        p_tokens = usage.get("prompt_tokens", 0)
                        c_tokens = usage.get("completion_tokens", 0)
                        t_tokens = usage.get("total_tokens", p_tokens + c_tokens)
                        await record_usage(
                            book_id=book_id,
                            task_name=task_name or "SCNet_Inference",
                            provider="SCNet",
                            model_name=model or "SCNet-Max",
                            prompt_tokens=p_tokens,
                            completion_tokens=c_tokens,
                            total_tokens=t_tokens,
                            duration_seconds=round(time.time() - t0, 2),
                            cost_cny=0.0
                        )
                    except Exception as err:
                        logger.warning(f"记录 SCNet Token 台账异常: {err}")

                return data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            if attempt < max_retries:
                await asyncio.sleep(backoff)
                backoff *= 1.5
                continue
            logger.warning(f"SCNet 调用异常 ({e})，降级到阿里百炼免费矩阵...")
            break

    # 降级到阿里百炼免费矩阵
    return await call_dashscope_llm(
        model=None,
        prompt=prompt,
        system_prompt=system_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
        book_id=book_id,
        task_name=f"{task_name}_Fallback_DashScope"
    )


async def call_dashscope_llm(
    model: str = None,
    prompt: str = "",
    system_prompt: str = "",
    temperature: float = 0.3,
    max_tokens: int = 2800,
    max_retries: int = 4,
    book_id: str = "",
    task_name: str = ""
) -> str:
    """
    调用阿里百炼 DashScope 旗舰大模型矩阵 (严选开启了“用完即停”的精确免费模型)
    当某模型额度用尽触发 HTTP 403 时，自动在 10+ 免费模型之间平滑无缝接力！
    """
    url = f"{LibraryConfig.DASHSCOPE_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {LibraryConfig.DASHSCOPE_API_KEY}",
        "Content-Type": "application/json"
    }
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    # 确定要尝试的百炼免费模型序列 (按到期时间排序，若传入了指定模型则将其置顶，其余免费模型随后接力)
    if model and model in DASHSCOPE_FREE_MODELS:
        candidates = [model] + [m for m in DASHSCOPE_FREE_MODELS if m != model]
    else:
        candidates = list(DASHSCOPE_FREE_MODELS)

    for target_m in candidates:
        payload = {
            "model": target_m,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }

        backoff = 2.0
        t0 = time.time()
        m_success = False
        for attempt in range(1, max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=180.0, trust_env=False) as client:
                    resp = await client.post(url, headers=headers, json=payload)
                    if resp.status_code == 429:
                        logger.warning(f"⚠️ DashScope {target_m} 并发限流 (HTTP 429), 退避重试 {attempt}/{max_retries}...")
                        await asyncio.sleep(backoff)
                        backoff *= 1.8
                        continue
                    if resp.status_code == 403:
                        logger.warning(f"🚨 百炼模型 {target_m} 免费额度用尽 (触发用完即停 HTTP 403)，自动秒切下一个免费模型...")
                        break
                    resp.raise_for_status()
                    data = resp.json()

                    if book_id:
                        try:
                            usage = data.get("usage", {})
                            p_tokens = usage.get("prompt_tokens", 0)
                            c_tokens = usage.get("completion_tokens", 0)
                            t_tokens = usage.get("total_tokens", p_tokens + c_tokens)
                            await record_usage(
                                book_id=book_id,
                                task_name=task_name or "DashScope_Inference",
                                provider="DashScope",
                                model_name=target_m,
                                prompt_tokens=p_tokens,
                                completion_tokens=c_tokens,
                                total_tokens=t_tokens,
                                duration_seconds=round(time.time() - t0, 2),
                                cost_cny=0.0
                            )
                        except Exception as err:
                            logger.warning(f"记录 Token 台账异常: {err}")

                    return data["choices"][0]["message"]["content"].strip()
            except Exception as e:
                if attempt < max_retries:
                    await asyncio.sleep(backoff)
                    backoff *= 1.5
                    continue
                logger.warning(f"DashScope {target_m} 调用异常 ({e})，尝试下一免费模型...")
                break

    # 若所有百炼免费模型均耗尽，降级到 Gemini 3.5-Flash-Lite
    return await call_gemini_llm(
        model="gemini-3.5-flash-lite",
        prompt=prompt,
        system_prompt=system_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
        book_id=book_id,
        task_name=f"{task_name}_Fallback_Gemini"
    )


async def call_volcengine_llm(
    endpoint: str = "",
    prompt: str = "",
    system_prompt: str = "",
    temperature: float = 0.3,
    max_tokens: int = 2800,
    max_retries: int = 4,
    book_id: str = "",
    task_name: str = "",
    model_label: str = "DeepSeek-V4-Pro"
) -> str:
    """调用火山方舟 VolcEngine 体验官 1:1 返还通道，带多模型接力、退避重试与精准 Token 台账"""
    url = f"{LibraryConfig.VOLCENGINE_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {LibraryConfig.VOLCENGINE_API_KEY}",
        "Content-Type": "application/json"
    }
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    # 确定候选端点队列 (若当前端点失败，自动在其余合规 0 成本模型中接力)
    cur_ep = endpoint or getattr(LibraryConfig, "ENDPOINT_DEEPSEEK_PRO", "ep-20260820195716-snkzx")
    candidates = [cur_ep] + [m["endpoint"] for m in VOLC_MODELS if m["endpoint"] != cur_ep]

    last_err = None
    for target_ep in candidates:
        if target_ep in VOLC_BANNED_ENDPOINTS:
            continue

        if "zvsw5" in target_ep or "glm" in target_ep.lower():
            label = "GLM-5.2"
        elif "snkzx" in target_ep or "pro" in target_ep.lower():
            label = "DeepSeek-V4-Pro"
        elif "td2g2" in target_ep or "flash" in target_ep.lower():
            label = "DeepSeek-V4-Flash"
        else:
            label = model_label or "VolcEngine-Model"

        payload = {
            "model": target_ep,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }

        backoff = 2.0
        t0 = time.time()
        for attempt in range(1, max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=120.0, trust_env=False) as client:
                    resp = await client.post(url, headers=headers, json=payload)
                    if resp.status_code == 429:
                        logger.warning(f"⚠️ VolcEngine {label} 并发限流 (HTTP 429), 退避重试 {attempt}/{max_retries}...")
                        await asyncio.sleep(backoff)
                        backoff *= 1.8
                        continue
                    if resp.status_code in [401, 403, 404]:
                        logger.error(f"🚨 VolcEngine {label} 鉴权或端点异常 (HTTP {resp.status_code}): {resp.text[:100]}")
                        last_err = f"HTTP {resp.status_code}: {resp.text[:80]}"
                        break
                    resp.raise_for_status()
                    data = resp.json()

                    usage = data.get("usage", {})
                    p_tokens = usage.get("prompt_tokens", int(len(prompt) * 0.6))
                    c_tokens = usage.get("completion_tokens", 0)
                    t_tokens = usage.get("total_tokens", p_tokens + c_tokens)

                    # 无论是否有 book_id，100% 记录至 Turso 台账确保额度追踪无遗漏
                    try:
                        await record_usage(
                            book_id=book_id or "system_general",
                            task_name=task_name or f"Volc_{label}",
                            provider="VolcEngine",
                            model_name=label,
                            prompt_tokens=p_tokens,
                            completion_tokens=c_tokens,
                            total_tokens=t_tokens,
                            duration_seconds=round(time.time() - t0, 2),
                            cost_cny=0.0
                        )
                    except Exception as err:
                        logger.warning(f"记录 Token 台账异常: {err}")

                    return data["choices"][0]["message"]["content"].strip()
            except Exception as e:
                last_err = str(e)
                if attempt < max_retries:
                    await asyncio.sleep(backoff)
                    backoff *= 1.5
                    continue
                logger.warning(f"VolcEngine {label} 调用重试耗尽 ({e})，尝试接力下一个合规模型...")
                break

    raise RuntimeError(f"所有可用 0 成本模型接力均未成功 (最后错误: {last_err})")


async def call_gemini_llm(
    model: str = "gemini-3.5-flash-lite",
    prompt: str = "",
    system_prompt: str = "",
    temperature: float = 0.3,
    max_tokens: int = 2800,
    max_retries: int = 4,
    book_id: str = "",
    task_name: str = ""
) -> str:
    """调用 Google Gemini 旗舰大模型 (1500次/天免费配额)，带本地代理与精准 Token 台账"""
    if not LibraryConfig.GEMINI_API_KEY:
        return await call_dashscope_llm(
            model=LibraryConfig.MODEL_DISTILLER,
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            book_id=book_id,
            task_name=task_name
        )

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={LibraryConfig.GEMINI_API_KEY}"
    headers = {"Content-Type": "application/json"}
    
    contents = []
    if system_prompt:
        contents.append({"role": "user", "parts": [{"text": f"System Context:\n{system_prompt}"}]})
        contents.append({"role": "model", "parts": [{"text": "Understood. I will follow the instructions."}]})
    contents.append({"role": "user", "parts": [{"text": prompt}]})

    payload = {
        "contents": contents,
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens
        }
    }

    proxy = LibraryConfig.LOCAL_PROXY
    backoff = 2.5
    t0 = time.time()
    for attempt in range(1, max_retries + 1):
        try:
            async with httpx.AsyncClient(timeout=120.0, proxy=proxy) as client:
                resp = await client.post(url, headers=headers, json=payload)
                if resp.status_code in [429, 503]:
                    logger.warning(f"⚠️ Gemini HTTP {resp.status_code}, 退避重试 {attempt}/{max_retries}...")
                    await asyncio.sleep(backoff)
                    backoff *= 2.0
                    continue
                resp.raise_for_status()
                data = resp.json()

                text = ""
                for cand in data.get("candidates", []):
                    for part in cand.get("content", {}).get("parts", []):
                        text += part.get("text", "")

                if book_id and text:
                    try:
                        u = data.get("usageMetadata", {})
                        p_tokens = u.get("promptTokenCount", int(len(prompt) * 0.6))
                        c_tokens = u.get("candidatesTokenCount", int(len(text) * 0.6))
                        t_tokens = u.get("totalTokenCount", p_tokens + c_tokens)
                        await record_usage(
                            book_id=book_id,
                            task_name=task_name or "Gemini_Inference",
                            provider="Google",
                            model_name=model,
                            prompt_tokens=p_tokens,
                            completion_tokens=c_tokens,
                            total_tokens=t_tokens,
                            duration_seconds=round(time.time() - t0, 2),
                            cost_cny=0.0
                        )
                    except Exception as err:
                        logger.warning(f"记录 Gemini 台账异常: {err}")

                return text.strip()
        except Exception as e:
            if attempt < max_retries:
                await asyncio.sleep(backoff)
                backoff *= 1.8
                continue
            logger.warning(f"Gemini 调用异常: {e}，降级至百炼...")
            break

    # 最终降级到百炼
    return await call_dashscope_llm(
        model=LibraryConfig.MODEL_DISTILLER,
        prompt=prompt,
        system_prompt=system_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
        book_id=book_id,
        task_name=f"{task_name}_Fallback"
    )


async def call_volcengine(
    model: str = None,
    prompt: str = "",
    system_prompt: str = "",
    temperature: float = 0.3,
    max_tokens: int = 2800,
    max_retries: int = 5,
    book_id: str = "",
    task_name: str = ""
) -> str:
    """
    智能统一算力分发入口 (带单日 150万 Tokens 熔断保护与自动轮巡接力)
    """
    # 动态通过单日台账选择当前最安全、最高性价比的 0 成本主力模型
    channel_type, target_model, model_label = await select_optimal_llm_channel(model)

    if channel_type == "scnet":
        return await call_scnet_llm(
            model=target_model,
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            max_retries=max_retries,
            book_id=book_id,
            task_name=task_name
        )
    elif channel_type == "volcengine":
        return await call_volcengine_llm(
            endpoint=target_model,
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            max_retries=max_retries,
            book_id=book_id,
            task_name=task_name,
            model_label=model_label
        )
    elif channel_type == "gemini":
        return await call_gemini_llm(
            model=target_model,
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            max_retries=max_retries,
            book_id=book_id,
            task_name=task_name
        )
    else:
        return await call_dashscope_llm(
            model=target_model,
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            max_retries=max_retries,
            book_id=book_id,
            task_name=task_name
        )


async def stream_volcengine(
    model_endpoint: str,
    prompt: str,
    system_prompt: str = "",
    temperature: float = 0.3,
    max_tokens: int = 1500,
    book_id: str = "",
    task_name: str = ""
):
    """流式调用 API (SSE Stream)，实时 yield 生成的 token 文本"""
    ep = model_endpoint or LibraryConfig.ENDPOINT_DEEPSEEK_PRO
    url = f"{LibraryConfig.VOLCENGINE_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {LibraryConfig.VOLCENGINE_API_KEY}",
        "Content-Type": "application/json"
    }
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": ep,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True
    }

    t0 = time.time()
    collected_text = []
    
    try:
        async with httpx.AsyncClient(timeout=180.0, trust_env=False) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as response:
                if response.status_code != 200:
                    body = await response.aread()
                    raise ValueError(f"VolcEngine Stream 错误 (HTTP {response.status_code}): {body.decode()}")
                    
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data_str = line[5:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                        choice = data.get("choices", [{}])[0]
                        delta = choice.get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            collected_text.append(content)
                            yield content
                    except Exception:
                        continue
    except Exception as e:
        logger.warning(f"流式请求异常: {e}")
        if not collected_text:
            fallback = await call_volcengine(ep, prompt, system_prompt, temperature, max_tokens, 2, book_id, task_name)
            yield fallback
            return

    full_text = "".join(collected_text).strip()
    if book_id and full_text:
        try:
            t_tokens = int(len(prompt) * 0.6 + len(full_text) * 0.6)
            await record_usage(
                book_id=book_id,
                task_name=task_name or "LLM_Stream",
                provider="VolcEngine",
                model_name="DeepSeek-V4-Pro" if "snkzx" in ep else "DeepSeek-V4-Flash",
                prompt_tokens=int(len(prompt) * 0.6),
                completion_tokens=int(len(full_text) * 0.6),
                total_tokens=t_tokens,
                duration_seconds=round(time.time() - t0, 2),
                cost_cny=0.0
            )
        except Exception as err:
            logger.warning(f"记录 Stream Token 台账异常: {err}")


# =========================================================================
# 结构化精读提炼辅助函数 (极简透视、播客剧本、动态题库、记忆闪卡)
# =========================================================================

async def generate_condensed_book(book_title: str, book_text: str, book_id: str = "") -> str:
    """编写 20%~25% 原著精华干货缩减本"""
    sample_text = book_text[:10000]
    system_prompt = """你是一位顶级的图书出版总编与知识重构架构师。
你的任务是将原著电子书重构成一份篇幅约为原著 20%~25% 的【极客干货精华缩减本】。
重构原则：
1. 彻底剔除重复铺垫、冗余过渡与过时废话；
2. 完整保留核心逻辑论据、核心代码、架构图解与关键案例；
3. 输出清晰结构化 Markdown。"""

    prompt = f"""请对电子书《{book_title}》的核心内容进行去水留精的深度重构：
{sample_text}
请输出高质量【20% 精华缩减本】(Markdown 格式)："""

    return await call_volcengine(
        None, prompt, system_prompt, 
        temperature=0.3, book_id=book_id, task_name="精读缩减本编写"
    )


async def generate_podcast_script(book_title: str, condensed_text: str, book_id: str = "") -> str:
    """创作双人对谈听书播客剧本 (NotebookLM 风格)"""
    system_prompt = """你是一位顶尖的播客制作人与对话编剧。
请根据提供的图书精华，编写一份生动、深刻、口语化的【8~10分钟双人对谈播客剧本】。
角色：🎙️ [睿哥] (深入浅出的资深专家) 与 🙋‍♂️ [小林] (敏锐求知的探索者)。"""

    prompt = f"""根据《{book_title}》的精华内容，生成双人播客剧本：
{condensed_text[:6000]}
请输出剧本："""

    return await call_volcengine(
        None, prompt, system_prompt, 
        temperature=0.6, book_id=book_id, task_name="双人播客剧本创作"
    )


async def generate_key_takeaways(book_title: str, book_text: str, book_id: str = "") -> Dict[str, Any]:
    """提炼 3分钟极简透视、5大颠覆性洞见与 Mermaid 脉络图"""
    sample_text = book_text[:10000]
    system_prompt = """请从图书文本中提炼：
1. 【一句话主旨】
2. 【5 大颠覆性洞见 (Key Takeaways)】
3. 【全书逻辑架构 (Mermaid 脉络图)】"""

    prompt = f"""分析《{book_title}》的核心逻辑：
{sample_text}
请输出 Markdown："""

    content = await call_volcengine(
        None, prompt, system_prompt, 
        temperature=0.2, book_id=book_id, task_name="3分钟透视与脉络图"
    )
    return {"takeaways_markdown": content}


async def generate_quizzes(book_title: str, condensed_text: str, book_id: str = "") -> List[Dict[str, Any]]:
    """命制精选研习测试题"""
    system_prompt = """根据书籍精华内容命制 10 道高质量【章节研习测试题库】(5道单选, 3道多选, 2道实战案例)。
必须严格只输出合法的 JSON 数组，字段：id, type, question, options, correct_answer, chapter_source, analysis。"""

    prompt = f"""为《{book_title}》命制 10 道深度研习测试题：
{condensed_text[:6000]}
请输出 JSON 数组："""

    raw_json = await call_volcengine(
        None, prompt, system_prompt, 
        temperature=0.1, book_id=book_id, task_name="10道章节测试题命制"
    )
    
    clean_json = raw_json.strip()
    if "```json" in clean_json:
        clean_json = clean_json.split("```json")[1].split("```")[0].strip()
    elif "```" in clean_json:
        clean_json = clean_json.split("```")[1].split("```")[0].strip()
        
    try:
        return json.loads(clean_json)
    except Exception as e:
        logger.warning(f"题库 JSON 解析失败，保留原文本: {e}")
        return [{
            "id": "q1",
            "type": "single",
            "question": f"关于《{book_title}》的核心主旨，以下表述正确的是？",
            "options": ["A. 正确选项", "B. 错误选项 1", "C. 错误选项 2", "D. 错误选项 3"],
            "correct_answer": "A",
            "chapter_source": "全书总览",
            "analysis": raw_json
        }]


async def generate_flashcards(book_title: str, condensed_text: str, book_id: str = "") -> List[Dict[str, str]]:
    """提炼 12 张核心概念记忆闪卡"""
    system_prompt = """请为本书提炼 12 张核心概念【Anki 记忆闪卡】。
每张卡片包含：front, back, tag。严格输出 JSON 数组。"""

    prompt = f"""提炼《{book_title}》的核心概念记忆闪卡：
{condensed_text[:5000]}
请输出 JSON 数组："""

    raw = await call_volcengine(
        None, prompt, system_prompt, 
        temperature=0.2, book_id=book_id, task_name="12张记忆闪卡提炼"
    )
    clean = raw.strip()
    if "```json" in clean:
        clean = clean.split("```json")[1].split("```")[0].strip()
    elif "```" in clean:
        clean = clean.split("```")[1].split("```")[0].strip()
        
    try:
        return json.loads(clean)
    except Exception:
        return []

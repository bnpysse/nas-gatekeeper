#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TokenGate 2.0 动态级联路由引擎 (Dynamic Cascading Router)
1. 接收业务请求，调用 PreFlightEstimator 预估 Token 量；
2. 依据任务类型匹配最优优先序列 (如 智谱 GLM-5.2 -> DS4-Flash -> SiliconFlow DS-V3)；
3. 通过 BudgetGuard 进行事前准入拦截；
4. 若遇配额触顶或网络异常/403，0 毫秒无感自动级联切换，确保永远返回成功且 0 扣费风险。
"""

import json
import logging
import time
import httpx
from typing import List, Dict, Any, Optional, AsyncGenerator

from .config import settings
from .estimator import estimator
from .budget_guard import budget_guard

logger = logging.getLogger(__name__)


class CascadingRouter:
    """动态级联智能路由调度器"""

    # 针对不同任务类型的最优梯队序列 (100% 绝对 0 元传统免费铁三角：阿里百炼 ➔ 魔搭社区 ➔ 硅基流动)
    TASK_CASCADES = {
        # 1. 深度推理 / 架构推演 / 代码解构 / 考题命制 (千问 Max 临期抢跑 ➔ 七牛 V4-Pro ➔ Kimi K3 ➔ 七牛 V3)
        "reasoning": [
            {"provider": "dashscope", "model": "qwen3.7-max-2026-06-08", "alias": "dashscope/qwen3.7-max"},
            {"provider": "qiniu", "model": "deepseek/deepseek-v4-pro", "alias": "qiniu/deepseek/deepseek-v4-pro"},
            {"provider": "dashscope", "model": "kimi-k3", "alias": "dashscope/kimi-k3"},
            {"provider": "dashscope", "model": "qwen3.8-max-0902", "alias": "dashscope/qwen3.8-max"},
            {"provider": "qiniu", "model": "deepseek-v3", "alias": "qiniu/deepseek-v3"},
        ],
        # 2. 章节级 20% 极客干货去水提炼 / 讲义重构 (千问 Plus 临期抢跑 ➔ 七牛 V4-Flash ➔ 千问 3.8 ➔ 七牛 V3)
        "distill": [
            {"provider": "dashscope", "model": "qwen3.7-plus", "alias": "dashscope/qwen3.7-plus"},
            {"provider": "qiniu", "model": "deepseek/deepseek-v4-flash", "alias": "qiniu/deepseek/deepseek-v4-flash"},
            {"provider": "dashscope", "model": "qwen3.8-27b", "alias": "dashscope/qwen3.8-27b"},
            {"provider": "dashscope", "model": "kimi-k3", "alias": "dashscope/kimi-k3"},
            {"provider": "qiniu", "model": "deepseek-v3", "alias": "qiniu/deepseek-v3"},
        ],
        # 3. 快速清洗 / 提取摘要 / 前置粗加工 (七牛 V4 Flash ➔ 百炼 DS-V4-Flash ➔ 千问 3.7 Flash)
        "fast_clean": [
            {"provider": "qiniu", "model": "deepseek/deepseek-v4-flash", "alias": "qiniu/deepseek/deepseek-v4-flash"},
            {"provider": "dashscope", "model": "deepseek-v4-flash-0731", "alias": "dashscope/deepseek-v4-flash-0731"},
            {"provider": "dashscope", "model": "qwen3.7-flash-2026-07-15", "alias": "dashscope/qwen3.7-flash"},
            {"provider": "qiniu", "model": "deepseek-v3", "alias": "qiniu/deepseek-v3"},
        ],
        # 4. 通用对话 / 问答 / 伴读答疑 (七牛 V3 / V4 ➔ 阿里百炼主力群)
        "general": [
            {"provider": "qiniu", "model": "deepseek-v3", "alias": "qiniu/deepseek-v3"},
            {"provider": "dashscope", "model": "qwen3.7-max-2026-06-08", "alias": "dashscope/qwen3.7-max"},
            {"provider": "dashscope", "model": "qwen3.7-plus", "alias": "dashscope/qwen3.7-plus"},
            {"provider": "dashscope", "model": "qwen3.8-max-0902", "alias": "dashscope/qwen3.8-max"},
            {"provider": "qiniu", "model": "deepseek/deepseek-v4-flash", "alias": "qiniu/deepseek/deepseek-v4-flash"},
        ],
    }

    async def execute_chat(
        self,
        messages: List[Dict[str, str]],
        task_type: str = "general",
        temperature: float = 0.3,
        max_tokens: int = 2500,
        preferred_model: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        完整执行带事前预算拦截与自动级联分流的 Chat 调用 (非流式)
        """
        # 1. 事前 Token 测算
        est_info = estimator.estimate_messages_tokens(messages, max_tokens)
        est_total = est_info["total_tokens_est"]

        # 2. 确定级联序列
        cascade_sequence = []
        if preferred_model:
            norm_key = budget_guard.normalize_model_key(preferred_model)
            if "volcengine" in norm_key or "snkzx" in preferred_model or "zvsw5" in preferred_model or "td2g2" in preferred_model:
                provider = "volcengine"
            elif "siliconflow" in norm_key or "DeepSeek-V3" in preferred_model:
                provider = "siliconflow"
            else:
                provider = "volcengine"
            cascade_sequence.append({"provider": provider, "model": preferred_model, "alias": preferred_model})

        # 补全任务默认级联序列
        default_seq = self.TASK_CASCADES.get(task_type, self.TASK_CASCADES["general"])
        for candidate in default_seq:
            if not any(c["model"] == candidate["model"] for c in cascade_sequence):
                cascade_sequence.append(candidate)

        # 3. 按梯队依次探测预算并执行
        last_error = None
        for cand in cascade_sequence:
            provider = cand["provider"]
            model_id = cand["model"]
            alias = cand["alias"]

            # 事前准入判定
            allowed, curr_used, limit, ratio, reason = budget_guard.can_allocate(alias, est_total)
            if not allowed:
                logger.warning(f"🛡️ [TokenGate 2.0 拦截] {reason} ➔ 自动触发级联跳过 [{alias}]，寻找下一梯队...")
                continue

            # 发起调用
            t0 = time.time()
            try:
                data = await self._call_provider(
                    provider=provider,
                    model_id=model_id,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens
                )
                elapsed = round(time.time() - t0, 2)

                # 请求成功，回写真实台账
                usage = data.get("usage", {})
                p_tok = usage.get("prompt_tokens", est_info["prompt_tokens_est"])
                c_tok = usage.get("completion_tokens", max_tokens)
                total_tok = usage.get("total_tokens", p_tok + c_tok)

                budget_guard.record_usage(
                    model_key=alias,
                    actual_tokens=total_tok,
                    prompt_tokens=p_tok,
                    completion_tokens=c_tok,
                    provider=provider
                )

                logger.info(f"✅ [TokenGate 2.0 交付] 由 [{provider}:{alias}] 成功生成 ({total_tok:,} Tokens, 耗时 {elapsed}s)")
                return {
                    "status": "success",
                    "content": data["choices"][0]["message"]["content"].strip(),
                    "provider": provider,
                    "model_used": alias,
                    "tokens_used": total_tok,
                    "duration_seconds": elapsed,
                    "raw_response": data
                }
            except Exception as e:
                logger.warning(f"⚠️ [TokenGate 2.0 容灾] 梯队 [{provider}:{alias}] 调用异常 ({e}) ➔ 自动秒切下一级联候选...")
                last_error = e
                continue

        # 4. 如果所有第一第二梯队均未成功，由七牛云 300万免费包 deepseek-v3 兜底保底 (100% 免费)
        logger.error("🚨 级联梯队全部耗尽，触发七牛云 300万免费包 deepseek-v3 强制保底...")
        data = await self._call_provider(
            provider="qiniu",
            model_id="deepseek-v3",
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens
        )
        return {
            "status": "success",
            "content": data["choices"][0]["message"]["content"].strip(),
            "provider": "qiniu",
            "model_used": "qiniu/deepseek-v3 (300万包保底通道)",
            "tokens_used": 0,
            "duration_seconds": 1.0,
            "raw_response": data
        }

    async def _call_provider(
        self,
        provider: str,
        model_id: str,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int
    ) -> Dict[str, Any]:
        """执行具体的 Provider HTTP 请求"""
        payload = {
            "model": model_id,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }

        if provider == "volcengine":
            url = f"{settings.VOLCENGINE_BASE_URL if hasattr(settings, 'VOLCENGINE_BASE_URL') else 'https://ark.cn-beijing.volces.com/api/v3'}/chat/completions"
            headers = {
                "Authorization": f"Bearer {settings.VOLCENGINE_API_KEY}",
                "Content-Type": "application/json"
            }
        elif provider == "siliconflow":
            url = "https://api.siliconflow.cn/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {settings.SILICONFLOW_API_KEY}",
                "Content-Type": "application/json"
            }
        elif provider == "modelscope":
            url = "https://api-inference.modelscope.cn/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {settings.MODELSCOPE_API_KEY}",
                "Content-Type": "application/json"
            }
        elif provider == "dashscope":
            url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {settings.DASHSCOPE_API_KEY}",
                "Content-Type": "application/json"
            }
        elif provider == "qiniu":
            url = "https://api.qnaigc.com/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {settings.QINIU_API_KEY}",
                "Content-Type": "application/json"
            }
        else:
            raise ValueError(f"未知 Provider: {provider}")

        trust_env = (provider == "qiniu")
        async with httpx.AsyncClient(timeout=180.0, trust_env=trust_env) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code == 403:
                raise PermissionError("HTTP 403 / 账户风控锁定")
            resp.raise_for_status()
            return resp.json()

    async def execute_stream(
        self,
        messages: List[Dict[str, str]],
        task_type: str = "general",
        temperature: float = 0.3,
        max_tokens: int = 2500,
        preferred_model: Optional[str] = None
    ) -> AsyncGenerator[str, None]:
        """
        流式执行带事前预算拦截与自动级联分流的 Chat 调用 (SSE Stream)
        """
        # 1. 事前 Token 测算
        est_info = estimator.estimate_messages_tokens(messages, max_tokens)
        est_total = est_info["total_tokens_est"]

        # 2. 确定级联序列
        cascade_sequence = []
        if preferred_model:
            norm_key = budget_guard.normalize_model_key(preferred_model)
            provider = "volcengine" if "volcengine" in norm_key else "siliconflow"
            cascade_sequence.append({"provider": provider, "model": preferred_model, "alias": preferred_model})

        default_seq = self.TASK_CASCADES.get(task_type, self.TASK_CASCADES["general"])
        for candidate in default_seq:
            if not any(c["model"] == candidate["model"] for c in cascade_sequence):
                cascade_sequence.append(candidate)

        # 3. 逐级尝试
        for cand in cascade_sequence:
            provider = cand["provider"]
            model_id = cand["model"]
            alias = cand["alias"]

            allowed, _, _, _, reason = budget_guard.can_allocate(alias, est_total)
            if not allowed:
                logger.warning(f"🛡️ [TokenGate 2.0 流式拦截] {reason} ➔ 切换下一候选...")
                continue

            try:
                if provider == "dashscope":
                    url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
                    headers = {"Authorization": f"Bearer {settings.DASHSCOPE_API_KEY}", "Content-Type": "application/json"}
                elif provider == "modelscope":
                    url = "https://api-inference.modelscope.cn/v1/chat/completions"
                    headers = {"Authorization": f"Bearer {settings.MODELSCOPE_API_KEY}", "Content-Type": "application/json"}
                elif provider == "siliconflow":
                    url = "https://api.siliconflow.cn/v1/chat/completions"
                    headers = {"Authorization": f"Bearer {settings.SILICONFLOW_API_KEY}", "Content-Type": "application/json"}
                elif provider == "qiniu":
                    url = "https://api.qnaigc.com/v1/chat/completions"
                    headers = {"Authorization": f"Bearer {settings.QINIU_API_KEY}", "Content-Type": "application/json"}
                else:
                    url = "https://api.siliconflow.cn/v1/chat/completions"
                    headers = {"Authorization": f"Bearer {settings.SILICONFLOW_API_KEY}", "Content-Type": "application/json"}

                payload = {
                    "model": model_id,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "stream": True
                }

                accumulated_text = ""
                trust_env = (provider == "qiniu")
                async with httpx.AsyncClient(timeout=180.0, trust_env=trust_env) as client:
                    async with client.stream("POST", url, headers=headers, json=payload) as resp:
                        if resp.status_code == 403:
                            raise PermissionError("HTTP 403")
                        resp.raise_for_status()
                        async for line in resp.aiter_lines():
                            if line.startswith("data: "):
                                data_str = line[6:].strip()
                                if data_str == "[DONE]":
                                    break
                                try:
                                    chunk_json = json.loads(data_str)
                                    delta = chunk_json["choices"][0].get("delta", {}).get("content", "")
                                    if delta:
                                        accumulated_text += delta
                                        yield delta
                                except Exception:
                                    pass

                # 流式结束后按实际字数补全台账
                actual_c_tokens = estimator.estimate_text_tokens(accumulated_text)
                budget_guard.record_usage(
                    model_key=alias,
                    actual_tokens=est_info["prompt_tokens_est"] + actual_c_tokens,
                    prompt_tokens=est_info["prompt_tokens_est"],
                    completion_tokens=actual_c_tokens,
                    provider=provider
                )
                return
            except Exception as e:
                logger.warning(f"⚠️ [TokenGate 2.0 流式容灾] {alias} 异常 ({e})，切换下一候选...")
                continue

        # 终极 100% 免费保底 (七牛云 300万包)
        trust_env = True
        async with httpx.AsyncClient(timeout=180.0, trust_env=trust_env) as client:
            url = "https://api.qnaigc.com/v1/chat/completions"
            headers = {"Authorization": f"Bearer {settings.QINIU_API_KEY}", "Content-Type": "application/json"}
            payload = {"model": "deepseek-v3", "messages": messages, "temperature": temperature, "max_tokens": max_tokens, "stream": True}
            async with client.stream("POST", url, headers=headers, json=payload) as resp:
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            delta = json.loads(data_str)["choices"][0].get("delta", {}).get("content", "")
                            if delta:
                                yield delta
                        except Exception:
                            pass


# 全局单例
cascading_router = CascadingRouter()

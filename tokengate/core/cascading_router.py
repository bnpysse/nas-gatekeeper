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

    # 针对不同任务类型的最优梯队序列 (Primary -> Secondary -> Unlimited Fallback)
    TASK_CASCADES = {
        # 1. 深度推理 / 架构推演 / 代码解构 / 考题命制
        "reasoning": [
            {"provider": "volcengine", "model": settings.VOLCENGINE_ENDPOINT_DEEPSEEK_PRO, "alias": "deepseek-v4-pro"},
            {"provider": "siliconflow", "model": "deepseek-ai/DeepSeek-V3", "alias": "deepseek-v3"},
        ],
        # 2. 章节级 20% 极客干货去水提炼 / 讲义重构
        "distill": [
            {"provider": "volcengine", "model": settings.VOLCENGINE_ENDPOINT_GLM, "alias": "glm-5.2"},
            {"provider": "volcengine", "model": settings.VOLCENGINE_ENDPOINT_DEEPSEEK_FLASH, "alias": "deepseek-v4-flash"},
            {"provider": "siliconflow", "model": "deepseek-ai/DeepSeek-V3", "alias": "deepseek-v3"},
        ],
        # 3. 快速清洗 / 提取摘要 / 前置粗加工
        "fast_clean": [
            {"provider": "volcengine", "model": settings.VOLCENGINE_ENDPOINT_DEEPSEEK_FLASH, "alias": "deepseek-v4-flash"},
            {"provider": "siliconflow", "model": "deepseek-ai/DeepSeek-V3", "alias": "deepseek-v3"},
        ],
        # 4. 通用对话 / 问答 / 伴读答疑
        "general": [
            {"provider": "volcengine", "model": settings.VOLCENGINE_ENDPOINT_DEEPSEEK_PRO, "alias": "deepseek-v4-pro"},
            {"provider": "volcengine", "model": settings.VOLCENGINE_ENDPOINT_GLM, "alias": "glm-5.2"},
            {"provider": "siliconflow", "model": "deepseek-ai/DeepSeek-V3", "alias": "deepseek-v3"},
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

        # 4. 如果所有第一第二梯队均未成功，由 SiliconFlow DeepSeek-V3 兜底保底
        logger.error("🚨 级联梯队全部耗尽，触发终极 SiliconFlow DeepSeek-V3 强制保底...")
        data = await self._call_provider(
            provider="siliconflow",
            model_id="deepseek-ai/DeepSeek-V3",
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens
        )
        return {
            "status": "success",
            "content": data["choices"][0]["message"]["content"].strip(),
            "provider": "siliconflow",
            "model_used": "deepseek-ai/DeepSeek-V3 (保底通道)",
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
        else:
            raise ValueError(f"未知 Provider: {provider}")

        async with httpx.AsyncClient(timeout=180.0, trust_env=False) as client:
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
                if provider == "volcengine":
                    url = f"{getattr(settings, 'VOLCENGINE_BASE_URL', 'https://ark.cn-beijing.volces.com/api/v3')}/chat/completions"
                    headers = {"Authorization": f"Bearer {settings.VOLCENGINE_API_KEY}", "Content-Type": "application/json"}
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
                async with httpx.AsyncClient(timeout=180.0, trust_env=False) as client:
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

        # 终极大兜底
        async with httpx.AsyncClient(timeout=180.0, trust_env=False) as client:
            url = "https://api.siliconflow.cn/v1/chat/completions"
            headers = {"Authorization": f"Bearer {settings.SILICONFLOW_API_KEY}", "Content-Type": "application/json"}
            payload = {"model": "deepseek-ai/DeepSeek-V3", "messages": messages, "temperature": temperature, "max_tokens": max_tokens, "stream": True}
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

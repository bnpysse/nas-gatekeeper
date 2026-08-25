#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
火山方舟双引擎精读核心 (Doubao-Evolving + DeepSeek-V4-Pro)
每日 200万循环免费算力驱动：全景去水重构、播客剧本、深度研习题库与记忆闪卡
"""

import json
import logging
import time
from typing import Dict, Any, List
import httpx
try:
    from .config import LibraryConfig
    from .db import record_usage
except ImportError:
    from config import LibraryConfig
    from db import record_usage

logger = logging.getLogger(__name__)

async def call_siliconflow_llm(
    model: str = "deepseek-ai/DeepSeek-V3", 
    prompt: str = "", 
    system_prompt: str = "", 
    temperature: float = 0.3, 
    max_tokens: int = 2800,
    max_retries: int = 5,
    book_id: str = "",
    task_name: str = ""
) -> str:
    """调用硅基流动 SiliconFlow 满血免费模型 (DeepSeek-V3 0元永久免费)，带自动重试与精准 Token 台账"""
    url = f"{LibraryConfig.SILICONFLOW_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {LibraryConfig.SILICONFLOW_API_KEY}",
        "Content-Type": "application/json"
    }
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens
    }

    import asyncio
    backoff = 2.0
    t0 = time.time()
    for attempt in range(1, max_retries + 1):
        try:
            async with httpx.AsyncClient(timeout=180.0, trust_env=False) as client:
                resp = await client.post(url, headers=headers, json=payload)
                if resp.status_code == 429:
                    logger.warning(f"⚠️ SiliconFlow 限流 (HTTP 429), 退避重试 {attempt}/{max_retries} (等待 {backoff:.1f}s)...")
                    await asyncio.sleep(backoff)
                    backoff *= 1.8
                    continue
                resp.raise_for_status()
                data = resp.json()
                
                # 记录 Token 消耗到 Turso 台账 (provider: SiliconFlow, cost: 0.0)
                if book_id:
                    try:
                        usage = data.get("usage", {})
                        p_tokens = usage.get("prompt_tokens", 0)
                        c_tokens = usage.get("completion_tokens", 0)
                        t_tokens = usage.get("total_tokens", p_tokens + c_tokens)
                        model_label = "DeepSeek-V3" if "DeepSeek-V3" in model else model
                        await record_usage(
                            book_id=book_id,
                            task_name=task_name or "SiliconFlow_Inference",
                            provider="SiliconFlow",
                            model_name=model_label,
                            prompt_tokens=p_tokens,
                            completion_tokens=c_tokens,
                            total_tokens=t_tokens,
                            duration_seconds=round(time.time() - t0, 2),
                            cost_cny=0.0
                        )
                    except Exception as err:
                        logger.warning(f"记录 Token 台账异常: {err}")
                        
                return data["choices"][0]["message"]["content"].strip()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429 and attempt < max_retries:
                await asyncio.sleep(backoff)
                backoff *= 1.8
                continue
            raise e
        except Exception as e:
            if attempt < max_retries:
                await asyncio.sleep(backoff)
                backoff *= 1.5
                continue
            raise e

    raise RuntimeError(f"SiliconFlow API 调用失败，已重试 {max_retries} 次仍未成功")

import sys
from pathlib import Path
tokengate_parent = str(Path(__file__).resolve().parent.parent)
if tokengate_parent not in sys.path:
    sys.path.insert(0, tokengate_parent)

try:
    from tokengate.core.cascading_router import cascading_router
    from tokengate.core.budget_guard import budget_guard
except ImportError:
    cascading_router = None
    budget_guard = None

async def call_volcengine(
    model_endpoint: str, 
    prompt: str, 
    system_prompt: str = "", 
    temperature: float = 0.3, 
    max_tokens: int = 2500,
    max_retries: int = 5,
    book_id: str = "",
    task_name: str = ""
) -> str:
    """TokenGate 2.0 智能安全调用层：优先在 180 万安全水位内享用 1:1 旗舰，触顶自动秒切 SiliconFlow 0元保底"""
    if cascading_router is not None:
        task = "distill" if ("精读" in task_name or "章节" in task_name) else ("reasoning" if ("透视" in task_name or "真题" in task_name) else "general")
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        res = await cascading_router.execute_chat(
            messages=messages,
            task_type=task,
            temperature=temperature,
            max_tokens=max_tokens,
            preferred_model=model_endpoint
        )
        
        # 写入 Turso 算力台账
        if book_id:
            try:
                raw_resp = res.get("raw_response", {})
                usage = raw_resp.get("usage", {})
                p_tok = usage.get("prompt_tokens", 0)
                c_tok = usage.get("completion_tokens", 0)
                t_tok = usage.get("total_tokens", p_tok + c_tok)
                prov = res.get("provider", "SiliconFlow")
                mod_name = res.get("model_used", "DeepSeek-V3")
                
                prov_display_map = {
                    "modelscope": "ModelScope",
                    "volcengine": "VolcEngine",
                    "siliconflow": "SiliconFlow",
                    "dashscope": "DashScope"
                }
                prov_key = prov_display_map.get(prov.lower(), prov)
                
                if "Qwen3-235B" in mod_name or "235B" in mod_name:
                    model_key = "Qwen-3-235B-Thinking"
                elif "DeepSeek-V4-Pro" in mod_name or "v4-pro" in mod_name:
                    model_key = "DeepSeek-V4-Pro"
                elif "DeepSeek-V4-Flash" in mod_name or "v4-flash" in mod_name:
                    model_key = "DeepSeek-V4-Flash"
                elif "GLM-5.2" in mod_name or "glm-5.2" in mod_name:
                    model_key = "GLM-5.2"
                elif "MiniMax" in mod_name:
                    model_key = "MiniMax-M1-80k"
                elif "DeepSeek-V3" in mod_name:
                    model_key = "DeepSeek-V3"
                elif "qwen3.7-plus" in mod_name or "qwen-plus" in mod_name:
                    model_key = "Qwen-3.7-Plus"
                else:
                    model_key = mod_name.split("/")[-1]
                    
                await record_usage(
                    book_id=book_id,
                    task_name=task_name or "LLM_Inference",
                    provider=prov_key,
                    model_name=model_key,
                    prompt_tokens=p_tok,
                    completion_tokens=c_tok,
                    total_tokens=t_tok,
                    duration_seconds=res.get("duration_seconds", 0.0),
                    cost_cny=0.0
                )
            except Exception as err:
                logger.warning(f"记录 TokenGate 台账异常: {err}")

        return res["content"]

    # 本地备用直连逻辑
    if "deepseek-ai" in model_endpoint or "siliconflow" in model_endpoint.lower() or "Qwen" in model_endpoint:
        return await call_siliconflow_llm(
            model=model_endpoint,
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            max_retries=max_retries,
            book_id=book_id,
            task_name=task_name
        )
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model_endpoint,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens
    }

    import asyncio
    backoff = 3.0
    t0 = time.time()
    for attempt in range(1, max_retries + 1):
        try:
            async with httpx.AsyncClient(timeout=360.0, trust_env=False) as client:
                resp = await client.post(url, headers=headers, json=payload)
                if resp.status_code == 429:
                    logger.warning(f"⚠️ 火山方舟并发限流 (HTTP 429), 正在进行第 {attempt}/{max_retries} 次退避重试 (等待 {backoff:.1f}s)...")
                    await asyncio.sleep(backoff)
                    backoff *= 1.8
                    continue
                if resp.status_code == 403:
                    logger.warning("🚨 火山方舟 403/欠费异常，自动触发无感容灾切换至硅基流动 DeepSeek-V3 0元引擎...")
                    return await call_siliconflow_llm(
                        model="deepseek-ai/DeepSeek-V3",
                        prompt=prompt,
                        system_prompt=system_prompt,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        book_id=book_id,
                        task_name=task_name
                    )
                resp.raise_for_status()
                data = resp.json()
                
                # 记录 Token 消耗到 Turso 台账
                if book_id:
                    try:
                        usage = data.get("usage", {})
                        p_tokens = usage.get("prompt_tokens", 0)
                        c_tokens = usage.get("completion_tokens", 0)
                        t_tokens = usage.get("total_tokens", p_tokens + c_tokens)
                        if "zvsw5" in model_endpoint.lower() or "glm" in model_endpoint.lower():
                            model_label = "智谱 GLM-5.2"
                        elif "td2g2" in model_endpoint.lower() or "flash" in model_endpoint.lower():
                            model_label = "DeepSeek-V4-Flash"
                        elif "snkzx" in model_endpoint.lower() or "pro" in model_endpoint.lower():
                            model_label = "DeepSeek-V4-Pro"
                        elif "t99mw" in model_endpoint.lower() or "doubao" in model_endpoint.lower():
                            model_label = "Doubao-Evolving"
                        else:
                            model_label = model_endpoint
                        await record_usage(
                            book_id=book_id,
                            task_name=task_name or "LLM_Inference",
                            provider="VolcEngine",
                            model_name=model_label,
                            prompt_tokens=p_tokens,
                            completion_tokens=c_tokens,
                            total_tokens=t_tokens,
                            duration_seconds=round(time.time() - t0, 2)
                        )
                    except Exception as err:
                        logger.warning(f"记录 Token 台账异常: {err}")
                        
                return data["choices"][0]["message"]["content"].strip()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429 and attempt < max_retries:
                await asyncio.sleep(backoff)
                backoff *= 1.8
                continue
            if e.response.status_code == 403:
                logger.warning("🚨 火山方舟 403 异常，自动秒切硅基流动 DeepSeek-V3 0元引擎...")
                return await call_siliconflow_llm(
                    model="deepseek-ai/DeepSeek-V3",
                    prompt=prompt,
                    system_prompt=system_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    book_id=book_id,
                    task_name=task_name
                )
            raise e
        except Exception as e:
            if attempt < max_retries:
                await asyncio.sleep(backoff)
                backoff *= 1.5
                continue
            raise e

    raise RuntimeError(f"大模型 API 调用失败，已重试 {max_retries} 次仍未成功")

async def stream_volcengine(
    model_endpoint: str,
    prompt: str,
    system_prompt: str = "",
    temperature: float = 0.3,
    max_tokens: int = 1500,
    book_id: str = "",
    task_name: str = ""
):
    """
    流式调用火山方舟 API (SSE Stream)，实时 yield 生成的 token 文本。
    首字响应通常仅需 1~3 秒，大幅消除终端、Web 页面与 TG Bot 的等待焦虑。
    """
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
        "model": model_endpoint,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True
    }

    import asyncio
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
        # 如果流式中断，退回到非流式作为保底
        if not collected_text:
            fallback = await call_volcengine(model_endpoint, prompt, system_prompt, temperature, max_tokens, 2, book_id, task_name)
            yield fallback
            return

    full_text = "".join(collected_text).strip()
    if book_id and full_text:
        try:
            t_tokens = int(len(prompt) * 0.6 + len(full_text) * 0.6)
            model_label = "Doubao-Evolving" if ("t99mw" in model_endpoint.lower() or "doubao" in model_endpoint.lower()) else "DeepSeek-V4-Pro"
            await record_usage(
                book_id=book_id,
                task_name=task_name or "LLM_Stream",
                provider="VolcEngine",
                model_name=model_label,
                prompt_tokens=int(len(prompt) * 0.6),
                completion_tokens=int(len(full_text) * 0.6),
                total_tokens=t_tokens,
                duration_seconds=round(time.time() - t0, 2)
            )
        except Exception as err:
            logger.warning(f"记录 Stream Token 台账异常: {err}")

# =========================================================================
# 引擎 1：精读缩减本与播客剧本 (DeepSeek-V4-Pro / Doubao 双擎驱动)
# =========================================================================

async def generate_condensed_book(book_title: str, book_text: str, book_id: str = "") -> str:
    """由 DeepSeek-V4-Pro / Doubao 编写 20%~25% 原著精华干货缩减本"""
    sample_text = book_text[:10000]
    
    system_prompt = """你是一位享誉全球的顶级图书出版总编与知识重构架构师。
你的任务是将用户提供的原著电子书，重构成一份篇幅约为原著 20%~25% 的【极客干货精华缩减本】。
重构原则：
1. 彻底剔除出版业为了凑字数而撰写的重复铺垫、冗余过渡与过时废话；
2. 完整保留原书核心逻辑论据、数学公式、核心代码、架构图解与不可或缺的关键案例；
3. 采用清晰结构化排版：
   - 📌 【核心概念与理论体系】
   - ⚙️ 【底层原理解构与关键实现】
   - 💡 【经典案例剖析与反向避坑】
   - 🛠️ 【实战落地 Checklist 与行动指南】"""

    prompt = f"""请对以下电子书《{book_title}》的核心内容进行去水留精的深度重构：

《{book_title}》原著文本摘要：
{sample_text}

请输出高质量、结构缜密的【20% 精华缩减本】(Markdown 格式)："""

    return await call_volcengine(
        LibraryConfig.ENDPOINT_DEEPSEEK_PRO, prompt, system_prompt, 
        temperature=0.3, book_id=book_id, task_name="精读缩减本编写 (DeepSeek)"
    )

async def generate_podcast_script(book_title: str, condensed_text: str, book_id: str = "") -> str:
    """由 DeepSeek-V4-Pro 创作双人对谈听书播客剧本 (NotebookLM 风格)"""
    system_prompt = """你是一位顶尖的播客制作人与对话编剧。
请根据提供的图书精华，编写一份生动、深刻、口语化的【8~10分钟双人对谈播客剧本】。
角色设定：
- 🎙️ [睿哥]：资深实战派专家，深入浅出，善于用精彩比喻把复杂原理讲得透彻；
- 🙋‍♂️ [小林]：求知欲极强的探索者，善于代表听众提出最尖锐、最实际的痛点问题与追问。
要求：
- 对话自然流畅，充满思维碰撞，拒绝念稿感；
- 格式每行清晰标明：`[睿哥]：...` 或 `[小林]：...`"""

    prompt = f"""根据《{book_title}》的精华内容，生成一期精彩的双人对谈听书剧本：

【图书精华内容】：
{condensed_text[:6000]}

请输出双人播客对谈剧本："""

    return await call_volcengine(
        LibraryConfig.ENDPOINT_DEEPSEEK_PRO, prompt, system_prompt, 
        temperature=0.6, book_id=book_id, task_name="双人播客剧本创作 (DeepSeek)"
    )

# =========================================================================
# 引擎 2：DeepSeek-V4-Pro (火山推演旗舰 · 擅长反常识洞见与深度题库命制)
# =========================================================================

async def generate_key_takeaways(book_title: str, book_text: str, book_id: str = "") -> Dict[str, Any]:
    """由 DeepSeek-V4-Pro 提炼 3分钟极简透视、5大颠覆性洞见与 Mermaid 脉络图"""
    sample_text = book_text[:10000]
    system_prompt = """你是一位深邃的哲学家与顶级技术战略家。
请从图书文本中提炼出：
1. 【一句话主旨】：直击灵魂的一句话定位。
2. 【5 大颠覆性洞见 (Key Takeaways)】：打破常规直觉、最具启发性的核心观点。
3. 【全书逻辑架构 (Mermaid 脉络图)】：用 mermaid 代码块呈现章节递进与因果网。
请以严谨规范的 Markdown 格式输出。"""

    prompt = f"""分析《{book_title}》的核心逻辑：
{sample_text}

请输出 3分钟极简透视、5大颠覆性洞见与 Mermaid 知识脉络图："""

    content = await call_volcengine(
        LibraryConfig.ENDPOINT_DEEPSEEK_PRO, prompt, system_prompt, 
        temperature=0.2, book_id=book_id, task_name="3分钟透视与脉络图 (DeepSeek)"
    )
    return {"takeaways_markdown": content}

async def generate_quizzes(book_title: str, condensed_text: str, book_id: str = "") -> List[Dict[str, Any]]:
    """由 DeepSeek-V4-Pro 命制 10 道精选研习测试题 (带章节溯源与错项深度排查)"""
    system_prompt = """你是一位严谨的大学教授与认证考核命题专家。
请根据书籍精华内容，命制一套高质量的【章节研习测试题库】。
要求包含：
- 5 道单选题 (single)
- 3 道多选题 (multiple)
- 2 道实战情境案例题 (case)
每道题必须严格输出 JSON 数组格式，字段包括：
- id: 题目序号 (如 q1, q2)
- type: single / multiple / case
- question: 题干描述
- options: 选项列表 ["A. ...", "B. ...", "C. ...", "D. ..."]
- correct_answer: 正确选项 (如 "B" 或 "A,C")
- chapter_source: 原书对应的章节知识点
- analysis: 深度解析（为什么选这个、其他选项错在何处）
请只返回合法的 JSON 代码块，不要包含任何多余文字。"""

    prompt = f"""为《{book_title}》命制 10 道深度研习测试题：

【书籍精华】：
{condensed_text[:6000]}

请严格输出 JSON 数组："""

    raw_json = await call_volcengine(
        LibraryConfig.ENDPOINT_DEEPSEEK_PRO, prompt, system_prompt, 
        temperature=0.1, book_id=book_id, task_name="10道章节测试题命制 (DeepSeek)"
    )
    
    # 清洗 JSON
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
    """由 DeepSeek-V4-Pro 提炼 12 张核心概念记忆闪卡 (Anki / 艾宾浩斯)"""
    system_prompt = """请为本书提炼 12 张核心概念【Anki 记忆闪卡】。
每张卡片包含：
- front: 正面提问（核心概念、定义或关键问题）
- back: 背面回答（精准原著金句、定理或 Checklist）
- tag: 标签分类
请严格输出 JSON 数组格式。"""

    prompt = f"""提炼《{book_title}》的核心概念记忆闪卡：
{condensed_text[:5000]}

请输出 JSON 数组："""

    raw = await call_volcengine(
        LibraryConfig.ENDPOINT_DEEPSEEK_PRO, prompt, system_prompt, 
        temperature=0.2, book_id=book_id, task_name="12张记忆闪卡提炼 (DeepSeek)"
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

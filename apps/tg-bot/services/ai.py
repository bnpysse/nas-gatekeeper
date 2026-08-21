#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import sys
import logging
import mimetypes
from pathlib import Path
import requests
import json
import asyncio
from concurrent.futures import ThreadPoolExecutor

parent_dir = str(Path(__file__).resolve().parent.parent)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from config import Config
from openai import OpenAI, AsyncOpenAI
import google.generativeai as genai
import httpx

logger = logging.getLogger(__name__)

CUSTOM_MIME_MAP = {
    ".m4a": "audio/mp4",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".aac": "audio/aac",
    ".opus": "audio/opus",
    ".ogg": "audio/ogg",
    ".webm": "audio/webm",
    ".mp4": "video/mp4",
    ".flv": "video/x-flv",
    ".mkv": "video/x-matroska",
}

def get_mime_type(file_path: Path) -> str:
    ext = file_path.suffix.lower()
    if ext in CUSTOM_MIME_MAP:
        return CUSTOM_MIME_MAP[ext]
    guessed, _ = mimetypes.guess_type(str(file_path))
    return guessed or "audio/mp4"

def get_tokengate_async_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        http_client=httpx.AsyncClient(proxy=None, timeout=25.0),
        api_key=Config.DASHSCOPE_API_KEY or "tg-sk",
        base_url="https://tg.donglida.xyz/v1"
    )

def clean_markdown_fence(text: str) -> str:
    """清洗大模型输出的多余最外层 ```markdown 或 ``` 代码块包裹"""
    s = (text or "").strip()
    if s.startswith("```markdown") and s.endswith("```"):
        s = s[len("```markdown"): -3].strip()
    elif s.startswith("```md") and s.endswith("```"):
        s = s[len("```md"): -3].strip()
    elif s.startswith("```") and s.endswith("```"):
        s = s[3:-3].strip()
    return s

def get_dashscope_async_client() -> AsyncOpenAI:
    return AsyncOpenAI(http_client=httpx.AsyncClient(proxy=None), 
        api_key=Config.DASHSCOPE_API_KEY,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
    )

def get_volcengine_async_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        http_client=httpx.AsyncClient(proxy=None),
        api_key=Config.VOLCENGINE_API_KEY,
        base_url="https://ark.cn-beijing.volces.com/api/v3"
    )

def transcribe_audio_sensevoice(audio_path: Path, preferred_models: list = None) -> str:
    """使用阿里云百炼 DashScope 智能多模型级联进行语音识别 (首选 paraformer-v2 -> paraformer-v1 -> sensevoice-v1)"""
    if preferred_models is None:
        preferred_models = ["paraformer-v2", "paraformer-v1", "sensevoice-v1"]

    import dashscope
    from dashscope.audio.asr import Transcription
    dashscope.api_key = Config.DASHSCOPE_API_KEY

    logger.info(f"🎙️ 正在上传音频至 DashScope 空间: {audio_path.name}")
    upload_res = dashscope.Files.upload(file_path=str(audio_path), purpose="inference", description="telegram_voice_sync")
    file_id = upload_res.output.get("uploaded_files", [{}])[0].get("file_id")
    if not file_id:
        raise RuntimeError(f"音频上传至 DashScope 失败: {upload_res}")

    try:
        file_info = dashscope.Files.get(file_id=file_id)
        file_url = file_info.output.get("url")
        if not file_url:
            raise RuntimeError("未能获取到 DashScope 音频文件访问链接")

        last_error = None
        for model in preferred_models:
            logger.info(f"🎙️ 正在尝试调用百炼 ASR 模型 [{model}] 进行语音识别...")
            try:
                task = Transcription.async_call(
                    model=model,
                    file_urls=[file_url],
                    language_hints=['zh', 'en']
                )
                if task.status_code != 200:
                    logger.warning(f"模型 [{model}] 提交失败: {task.message}，尝试下一模型...")
                    last_error = task.message
                    continue

                result = Transcription.wait(task=task.output.task_id)
                if result.status_code != 200 or result.output.get("task_status") != "SUCCEEDED":
                    logger.warning(f"模型 [{model}] 转录未成功: {result.output}，尝试下一模型...")
                    last_error = str(result.output)
                    continue

                trans_url = result.output["results"][0]["transcription_url"]
                data = requests.get(trans_url, timeout=30).json()
                transcripts = data.get("transcripts", [])
                raw_text = "".join([t.get("text", "") for t in transcripts])
                cleaned_text = re.sub(r"<\|[^|]+\|>", "", raw_text).strip()

                logger.info(f"✅ 模型 [{model}] 转录成功！共识别 {len(cleaned_text)} 字")
                return cleaned_text
            except Exception as e:
                logger.warning(f"模型 [{model}] 执行异常: {e}，尝试下一模型...")
                last_error = str(e)
                continue

        raise RuntimeError(f"所有 ASR 模型转录均失败，最后错误: {last_error}")
    finally:
        try:
            dashscope.Files.delete(file_id=file_id)
        except Exception:
            pass

async def _summarize_with_qwen_stream(text: str, title: str):
    prompt = (
        f"视频/文章标题：《{title}》\n\n"
        f"【严格约束】：你必须 100% 严格基于以下提供的【真实原文内容】进行分析与提炼！"
        f"严禁脱离原文依据进行任何凭空猜测、臆测编造或虚构事实。如果原文没有提及，一律不得推断为既成事实。\n\n"
        f"【格式要求】：直接输出 Markdown 正文，严禁在最外层使用 ```markdown 或 ``` 代码块包裹！\n\n"
        f"【真实原文内容】：\n{text[:20000]}\n\n"
        f"请输出 Markdown 格式的深度提炼（包含：🎯 核心观点摘要、📌 关键脉络与论据、💡 核心洞察）："
    )
    try:
        client = get_tokengate_async_client()
        response = await client.chat.completions.create(
            model="auto",
            messages=[{"role": "user", "content": prompt}],
            stream=True
        )
        async for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
    except Exception as tg_err:
        logger.warning(f"TokenGate 代理调用异常 ({tg_err})，自动降级至百炼原生直连...")
        try:
            client = get_dashscope_async_client()
            response = await client.chat.completions.create(
                model=Config.DASHSCOPE_CHAT_MODEL,
                messages=[{"role": "user", "content": prompt}],
                stream=True
            )
            async for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            logger.error(f"Qwen 总结彻底失败: {e}")
            yield f"\n\n> [!WARNING] Qwen 分析失败: {e}"

async def _summarize_with_volcengine_stream(text: str, title: str):
    prompt = (
        f"视频/文章标题：《{title}》\n\n"
        f"【严格约束】：你必须 100% 严格基于以下提供的【真实原文内容】进行分析与提炼！"
        f"严禁脱离原文依据进行任何凭空猜测、臆测编造或虚构事实。如果原文没有提及，一律不得推断为既成事实。\n\n"
        f"【格式要求】：直接输出 Markdown 正文，严禁在最外层使用 ```markdown 或 ``` 代码块包裹！\n\n"
        f"【真实原文内容】：\n{text[:20000]}\n\n"
        f"请输出 Markdown 格式的深度提炼（包含：🎯 核心观点摘要、📌 关键脉络与论据、💡 核心洞察）："
    )
    try:
        client = get_volcengine_async_client()
        model_id = Config.VOLCENGINE_ENDPOINT_ID or "ep-20260820195716-snkzx"
        response = await client.chat.completions.create(
            model=model_id,
            messages=[{"role": "user", "content": prompt}],
            stream=True
        )
        async for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
    except Exception as e:
        logger.error(f"Volcengine DeepSeek 总结失败: {e}")
        yield f"\n\n> [!WARNING] Volcengine DeepSeek 分析失败: {e}"

async def multi_model_summarize_stream(text: str, title: str, update_callback=None) -> str:
    """并行调用双模型，支持流式返回状态，带有严格防幻觉校验与 Markdown 净空"""
    clean_text = (text or "").strip()
    if len(clean_text) < 30:
        raise ValueError("未能获取到有效的原文或字幕内容（文本不足 30 字）。为杜绝脱离原文的凭空臆测，系统已安全中止总结。")

    state = {"qwen": "", "volc": ""}
    
    async def run_qwen():
        async for chunk in _summarize_with_qwen_stream(clean_text, title):
            state["qwen"] += chunk
            if update_callback:
                await update_callback(state)
                
    async def run_volc():
        async for chunk in _summarize_with_volcengine_stream(clean_text, title):
            state["volc"] += chunk
            if update_callback:
                await update_callback(state)
                
    await asyncio.gather(run_qwen(), run_volc())

    # 关键：彻底清洗两者的外层 ```markdown 代码块包裹
    volc_clean = clean_markdown_fence(state["volc"])
    qwen_clean = clean_markdown_fence(state["qwen"])
    
    combined = f"## 📊 双模型深度交叉分析报告\n\n### 🐳 火山引擎 DeepSeek-V4 (每日循环保底)\n\n{volc_clean}\n\n---\n\n### 🔵 阿里百炼 Qwen (TokenGate 抢跑调度)\n\n{qwen_clean}\n"
    return combined

async def analyze_audio_with_sensevoice_and_multi_stream(audio_path: Path, video_title: str, update_callback=None) -> dict:
    """使用阿里云 SenseVoice-V1 提取文本 (在线程中防阻塞)，然后多模型流式总结"""
    transcript = await asyncio.to_thread(transcribe_audio_sensevoice, audio_path)
    
    combined_summary = await multi_model_summarize_stream(transcript, video_title, update_callback)
    
    full_content = combined_summary + f"\n\n---\n\n## 🎙️ 语音转写原文\n\n{transcript}"
    return {
        "title": video_title,
        "content": full_content
    }

async def analyze_web_url_stream(url: str, update_callback=None) -> dict:
    """使用 Jina Reader 抓取网页正文并由多模型流式提炼总结"""
    logger.info(f"正在使用 Jina Reader 抓取网页: {url}")
    jina_url = f"https://r.jina.ai/{url}"
    
    proxies = {}
    if Config.HTTP_PROXY:
        proxies["http"] = Config.HTTP_PROXY
        proxies["https"] = Config.HTTPS_PROXY

    def fetch_jina():
        resp = requests.get(jina_url, proxies=proxies, timeout=30)
        resp.raise_for_status()
        return resp.text

    try:
        raw_markdown = await asyncio.to_thread(fetch_jina)
        
        # Check if Jina returned an error JSON instead of markdown
        if raw_markdown.strip().startswith('{"data":null,"code":'):
            raise ValueError("Jina IP 被封禁或需要认证")
            
        if len(raw_markdown.strip()) < 100:
            raise ValueError("提取的正文过短，可能遭遇反爬或动态渲染")
            
    except Exception as e:
        logger.error(f"Jina 抓取失败: {e}")
        return {
            "title": "抓取失败",
            "content": f"❌ **无法获取原文正文。**\n> 失败原因：`{e}`\n\n此链接可能是需要登录的页面、纯动态渲染或是防爬虫系统拦截。为避免大模型由于没有原文依据而产生“幻觉”和强行猜测，系统已自动终止后续的摘要分析任务。"
        }

    title = "网页/文章剪藏"
    for line in raw_markdown.splitlines()[:5]:
        if line.startswith("Title:"):
            title = line.replace("Title:", "").strip()
            break

    combined_summary = await multi_model_summarize_stream(raw_markdown, title, update_callback)
    
    full_content = combined_summary + f"\n\n---\n\n### 网页原始抓取正文\n\n{raw_markdown[:15000]}"
    return {
        "title": title,
        "content": full_content
    }

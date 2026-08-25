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
    """
    智能多级语音识别级联引擎：
    1. 首选：硅基流动 SiliconFlow SenseVoiceSmall (原生永久 0 费用免费，国内极速)
    2. 备用：阿里百炼 DashScope (paraformer-v2 -> paraformer-v1 -> sensevoice-v1)
    """
    # 1. 优先尝试硅基流动 SenseVoiceSmall (永久免费 0 元)
    sf_key = os.getenv("SILICONFLOW_API_KEY", "sk-wewpjlyfvwflfcqivobyumvhybqldextibizkxtkmajkkqvs")
    if sf_key:
        try:
            logger.info(f"🎙️ [首选] 正在调用硅基流动 SenseVoiceSmall 进行语音转写 (0元永久免费)...")
            with open(audio_path, "rb") as f:
                files = {"file": (audio_path.name, f, get_mime_type(audio_path))}
                data = {"model": "FunAudioLLM/SenseVoiceSmall"}
                headers = {"Authorization": f"Bearer {sf_key}"}
                with httpx.Client(timeout=60.0) as client:
                    res = client.post("https://api.siliconflow.cn/v1/audio/transcriptions", headers=headers, files=files, data=data)
                    if res.status_code == 200:
                        text = res.json().get("text", "").strip()
                        cleaned_text = re.sub(r"<\|[^|]+\|>", "", text).strip()
                        if len(cleaned_text) > 0:
                            logger.info(f"✅ 硅基流动 SenseVoiceSmall 转写成功！共 {len(cleaned_text)} 字")
                            return cleaned_text
                    else:
                        logger.warning(f"硅基流动 SenseVoice 返回非200: {res.status_code} {res.text}")
        except Exception as sf_err:
            logger.warning(f"硅基流动 SenseVoice 调用异常: {sf_err}，平滑切换至阿里百炼...")

    # 2. 备用降级：阿里百炼 DashScope 级联
    if preferred_models is None:
        preferred_models = ["paraformer-v2", "paraformer-v1", "sensevoice-v1", "paraformer-realtime-8k-v2"]

    import dashscope
    from dashscope.audio.asr import Transcription
    dashscope.api_key = Config.DASHSCOPE_API_KEY

    logger.info(f"🎙️ [备用] 正在上传音频至 DashScope 空间: {audio_path.name}")
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

# 引入 TokenGate 2.0 预算与水库硬锁门神
import sys
tokengate_parent = str(Path(__file__).resolve().parent.parent.parent)
if tokengate_parent not in sys.path:
    sys.path.insert(0, tokengate_parent)

try:
    from tokengate.core.budget_guard import budget_guard
    from tokengate.core.estimator import estimator
except ImportError:
    budget_guard = None
    estimator = None

async def _summarize_with_glm_stream(text: str, title: str):
    """由智谱 GLM-5.2 进行事实脉络与文脉深度分析 (Volcengine 180万安全池 ➔ SiliconFlow 0元备用)"""
    prompt = (
        f"视频/文章标题：《{title}》\n\n"
        f"【严格约束】：你必须 100% 严格基于以下提供的【真实原文内容】进行分析与提炼！"
        f"严禁脱离原文依据进行任何凭空猜测、臆测编造或虚构事实。如果原文没有提及，一律不得推断为既成事实。\n\n"
        f"【格式要求】：直接输出 Markdown 正文，严禁在最外层使用 ```markdown 或 ``` 代码块包裹！\n\n"
        f"【真实原文内容】：\n{text[:20000]}\n\n"
        f"请输出 Markdown 格式的深度提炼（包含：🎯 核心观点摘要、📌 关键脉络与论据、💡 核心洞察）："
    )

    est_tokens = estimator.estimate_text_tokens(prompt) + 2500 if estimator else 5000
    # 1. 优先走 TokenGate 2.0 智能中央网关 (自动级联阿里百炼 / 魔搭 235B / 硅基流动)
    try:
        tg_client = get_tokengate_async_client()
        response = await tg_client.chat.completions.create(
            model="distill",
            messages=[{"role": "user", "content": prompt}],
            stream=True
        )
        accumulated = ""
        async for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                delta = chunk.choices[0].delta.content
                accumulated += delta
                yield delta
        return
    except Exception as tg_err:
        logger.warning(f"TokenGate 网关调度异常 ({tg_err})，自动切换至阿里百炼 / 硅基流动备用...")

    # 2. 备用容灾：硅基流动 SiliconFlow
    try:
        sf_key = os.getenv("SILICONFLOW_API_KEY", "sk-wewpjlyfvwflfcqivobyumvhybqldextibizkxtkmajkkqvs")
        sf_client = AsyncOpenAI(http_client=httpx.AsyncClient(proxy=None, timeout=45.0), api_key=sf_key, base_url="https://api.siliconflow.cn/v1")
        response = await sf_client.chat.completions.create(
            model="zai-org/GLM-5.2",
            messages=[{"role": "user", "content": prompt}],
            stream=True
        )
        async for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
    except Exception as e:
        logger.error(f"GLM-5.2 总结双通道均失败: {e}")
        yield f"\n\n> [!WARNING] GLM-5.2 分析失败: {e}"

async def _summarize_with_volcengine_stream(text: str, title: str):
    """由 DeepSeek-V4-Pro 进行深度推理与逻辑解构 (Volcengine 180万安全池 ➔ SiliconFlow DeepSeek 0元备用)"""
    prompt = (
        f"视频/文章标题：《{title}》\n\n"
        f"【严格约束】：你必须 100% 严格基于以下提供的【真实原文内容】进行分析与提炼！"
        f"严禁脱离原文依据进行任何凭空猜测、臆测编造或虚构事实。如果原文没有提及，一律不得推断为既成事实。\n\n"
        f"【格式要求】：直接输出 Markdown 正文，严禁在最外层使用 ```markdown 或 ``` 代码块包裹！\n\n"
        f"【真实原文内容】：\n{text[:20000]}\n\n"
        f"请输出 Markdown 格式的深度提炼（包含：🎯 核心观点摘要、📌 关键脉络与论据、💡 核心洞察）："
    )

    est_tokens = estimator.estimate_text_tokens(prompt) + 2500 if estimator else 5000
    allow_volc = True
    if budget_guard:
        allowed, _, _, _, reason = budget_guard.can_allocate("deepseek-v4-pro", est_tokens)
        if not allowed:
            logger.warning(f"🛡️ [TG-Bot 预算门神] DeepSeek-V4-Pro {reason} ➔ 自动切换至硅基流动 DeepSeek 0元保底池")
            allow_volc = False

    # 1. 优先在安全水位内调用火山方舟 DeepSeek-V4-Pro
    if allow_volc:
        try:
            client = get_volcengine_async_client()
            model_id = os.getenv("VOLCENGINE_ENDPOINT_DEEPSEEK_PRO", "ep-20260820195716-snkzx")
            response = await client.chat.completions.create(
                model=model_id,
                messages=[{"role": "user", "content": prompt}],
                stream=True
            )
            accumulated = ""
            async for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content:
                    delta = chunk.choices[0].delta.content
                    accumulated += delta
                    yield delta
            if budget_guard and estimator:
                act = estimator.estimate_text_tokens(accumulated) + est_tokens
                budget_guard.record_usage("deepseek-v4-pro", act, provider="volcengine")
            return
        except Exception as volc_err:
            logger.warning(f"火山方舟 DeepSeek 异常 ({volc_err})，自动切换至硅基流动 DeepSeek 备用...")

    # 2. 备用容灾：硅基流动 SiliconFlow
    try:
        sf_key = os.getenv("SILICONFLOW_API_KEY", "sk-wewpjlyfvwflfcqivobyumvhybqldextibizkxtkmajkkqvs")
        sf_client = AsyncOpenAI(http_client=httpx.AsyncClient(proxy=None, timeout=45.0), api_key=sf_key, base_url="https://api.siliconflow.cn/v1")
        response = await sf_client.chat.completions.create(
            model="deepseek-ai/DeepSeek-V3",
            messages=[{"role": "user", "content": prompt}],
            stream=True
        )
        async for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
    except Exception as e:
        logger.error(f"DeepSeek 总结双通道均失败: {e}")
        yield f"\n\n> [!WARNING] DeepSeek 分析失败: {e}"

async def multi_model_summarize_stream(text: str, title: str, update_callback=None) -> str:
    """并行调用双模型 (DeepSeek-V4-Pro + GLM-5.2)，支持流式返回状态，带有严格防幻觉校验与 Markdown 净空"""
    clean_text = (text or "").strip()
    if len(clean_text) < 30:
        raise ValueError("未能获取到有效的原文或字幕内容（文本不足 30 字）。为杜绝脱离原文的凭空臆测，系统已安全中止总结。")

    state = {"glm": "", "volc": ""}
    
    async def run_glm():
        async for chunk in _summarize_with_glm_stream(clean_text, title):
            state["glm"] += chunk
            if update_callback:
                await update_callback(state)
                
    async def run_volc():
        async for chunk in _summarize_with_volcengine_stream(clean_text, title):
            state["volc"] += chunk
            if update_callback:
                await update_callback(state)
                
    await asyncio.gather(run_glm(), run_volc())

    # 关键：彻底清洗两者的外层 ```markdown 代码块包裹
    volc_clean = clean_markdown_fence(state["volc"])
    glm_clean = clean_markdown_fence(state["glm"])
    
    combined = f"## 📊 双旗舰模型深度交叉分析报告 (1:1 零费用算力矩阵)\n\n### 🐳 DeepSeek-V4-Pro (深度推理与逻辑解构)\n\n{volc_clean}\n\n---\n\n### 🇨🇳 智谱 GLM-5.2 (事实脉络与文脉深度分析)\n\n{glm_clean}\n"
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
    """使用 Jina Reader / Trafilatura 抓取网页正文并由多模型流式提炼总结"""
    logger.info(f"正在抓取网页: {url}")
    
    # 针对微信公众号链接，直接调用专属微信提取引擎
    if "mp.weixin.qq.com" in url:
        return await extract_and_analyze_wechat_article(url, update_callback)
        
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

async def extract_and_analyze_wechat_article(url: str, update_callback=None) -> dict:
    """专为微信公众号定制的高保真 100% 正文抓取与 AI 深度拆解引擎"""
    logger.info(f"正在提取微信公众号文章正文: {url}")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.38",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    }
    
    def fetch_wechat():
        import bs4
        try:
            import trafilatura
        except ImportError:
            trafilatura = None
            
        resp = requests.get(url, headers=headers, timeout=20)
        resp.encoding = "utf-8"
        html = resp.text
        
        soup = bs4.BeautifulSoup(html, "html.parser")
        
        # 1. 提取标题
        title_el = soup.find("h1", class_="rich_media_title") or soup.find(id="activity-name")
        meta_title = soup.find("meta", property="og:title")
        title = (title_el.get_text(strip=True) if title_el else "") or (meta_title["content"].strip() if meta_title else "微信精选文章")
        
        # 2. 提取公众号名称 / 作者
        author_el = soup.find("a", id="js_name") or soup.find(class_="profile_nickname")
        meta_author = soup.find("meta", property="og:article:author")
        account = (author_el.get_text(strip=True) if author_el else "") or (meta_author["content"].strip() if meta_author else "微信公众号")
        
        # 3. 提取 100% 完整正文
        content_el = soup.find(id="js_content")
        raw_text = ""
        if content_el:
            # 清除不可见脚本与样式
            for tag in content_el(["script", "style", "svg"]):
                tag.decompose()
            raw_text = content_el.get_text(separator="\n\n", strip=True)
            
        if not raw_text or len(raw_text) < 100:
            if trafilatura:
                extracted = trafilatura.extract(html, include_tables=True)
                if extracted and len(extracted) >= 100:
                    raw_text = extracted.strip()
                    
        return title, account, raw_text

    try:
        title, account, raw_text = await asyncio.to_thread(fetch_wechat)
        if not raw_text or len(raw_text) < 50:
            raise ValueError("微信文章内容为空或已被作者删除/访问受限")
    except Exception as e:
        logger.error(f"微信文章抓取失败: {e}")
        return {
            "title": "微信文章抓取失败",
            "account": "微信公众号",
            "raw_content": "",
            "summary_content": f"❌ **无法提取微信文章正文**\n> 原因：`{e}`",
            "is_error": True
        }

    # 调用 DeepSeek-V4 进行结构化深度拆解
    prompt = f"""你是一个专业的高级情报与商业科技分析专家。
请仔细阅读以下这篇来自微信公众号【{account}】的完整文章，撰写一份结构清晰、深度到位的精华精读简报。

文章标题：{title}
来源公众号：{account}
原文链接：{url}

文章完整正文：
{raw_text[:20000]}

请按以下格式输出 Markdown 简报：
## 🎯 核心要旨 (TL;DR)
[用精炼生动的 2-3 句话总结全篇精髓与核心结论]

## 🧩 核心论点与逻辑演进 (Key Arguments & Evidence)
- **[论点 1]**：[具体论据、数据支撑或案例]
- **[论点 2]**：[具体论据、数据支撑或案例]
- **[论点 3]**：[具体论据、数据支撑或案例]

## 💡 决策启示与深度思考 (Actionable Insights)
- [对读者个人、技术实践或商业投资的关键启发与落地建议]

## 🏷️ 关键标签
#微信精选 #{account.replace(' ', '_')}
"""
    client = get_volcengine_async_client()
    try:
        resp = await client.chat.completions.create(
            model=Config.VOLCENGINE_ENDPOINT_ID or "ep-20260809122445-td2g2",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=4096
        )
        summary = clean_markdown_fence(resp.choices[0].message.content)
    except Exception as e:
        logger.error(f"微信文章 AI 提炼异常: {e}")
        summary = f"⚠️ AI 简报生成异常: {e}"

    return {
        "title": title,
        "account": account,
        "raw_content": raw_text,
        "summary_content": summary,
        "is_error": False
    }


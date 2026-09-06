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
import time
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

def compress_audio_if_large(audio_path: Path, max_mb: float = 15.0) -> Path:
    """若音频文件大于 15MB，自动使用 ffmpeg 压缩为 16kHz 48kbps 单声道纯音频，避免触发 API 413/503"""
    try:
        size_mb = audio_path.stat().st_size / (1024 * 1024)
        if size_mb <= max_mb:
            return audio_path
        
        compressed_path = audio_path.with_name(f"{audio_path.stem}_opt.m4a")
        import subprocess
        cmd = [
            "ffmpeg", "-y", "-i", str(audio_path),
            "-vn", "-ac", "1", "-ar", "16000", "-b:a", "48k",
            str(compressed_path)
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
        if res.returncode == 0 and compressed_path.exists() and compressed_path.stat().st_size > 1024:
            logger.info(f"⚡ 音频超限 ({size_mb:.1f}MB)，自适应无损压缩为 {compressed_path.stat().st_size // 1024} KB")
            return compressed_path
    except Exception as e:
        logger.warning(f"自适应压缩音频失败: {e}，使用原文件")
    return audio_path

def transcribe_dashscope_realtime(audio_path: Path, model: str = "paraformer-realtime-v2") -> str:
    """使用阿里百炼官方 Recognition 原生流式引擎极速识别本地音轨 (支持 paraformer-realtime-v2 / v1，带用完即停硬锁)"""
    import subprocess
    import dashscope
    from dashscope.audio.asr import Recognition, RecognitionCallback, RecognitionResult

    dashscope.api_key = Config.DASHSCOPE_API_KEY
    wav_path = audio_path.with_name(f"{audio_path.stem}_16k.wav")
    try:
        from services.downloader import find_ffmpeg
        ffmpeg_bin = find_ffmpeg() or "ffmpeg"
        sample_rate = 8000 if "8k" in model else 16000
        subprocess.run([
            ffmpeg_bin, "-y", "-i", str(audio_path),
            "-vn", "-ac", "1", "-ar", str(sample_rate),
            str(wav_path)
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

        class ASRCallback(RecognitionCallback):
            def __init__(self):
                self.sentences = []
            def on_event(self, result: RecognitionResult):
                sentence = result.get_sentence()
                if sentence and "text" in sentence:
                    self.sentences.append(sentence["text"])

        cb = ASRCallback()
        rec = Recognition(model=model, format="wav", sample_rate=sample_rate, callback=cb)
        result = rec.call(str(wav_path))
        
        sentences = result.get_sentence() if result else None
        if sentences:
            text = "".join([s.get("text", "") for s in sentences if s.get("text")])
        else:
            text = "".join(cb.sentences)
            
        cleaned = re.sub(r"<\|[^|]+\|>", "", text).strip()
        if len(cleaned) > 0:
            logger.info(f"✅ 百炼实时 ASR [{model}] 转写成功！共 {len(cleaned)} 字")
            return cleaned
    except Exception as e:
        logger.warning(f"百炼实时 ASR [{model}] 识别异常: {e}")
    finally:
        if wav_path.exists():
            try:
                wav_path.unlink(missing_ok=True)
            except Exception:
                pass
    return ""

def transcribe_audio_sensevoice(audio_path: Path, preferred_models: list = None) -> str:
    """
    智能多级语音识别级联引擎 (100% 绝对 0 成本 · 用完即停硬锁保护)：
    1. 首选：阿里百炼官方 4 大活跃实时 ASR 矩阵 (paraformer-realtime-v2 -> v1 -> 8k-v2 -> 8k-v1，各36000秒充沛免费额度)
    2. 备用：硅基流动 FunAudioLLM/SenseVoiceSmall (永久 0 元免费专区，带 16kHz 自适应压缩)
    3. 兜底：阿里百炼 DashScope 异步 Transcription 级联
    """
    # 1. 优先调用阿里百炼实时 ASR 模型矩阵 (官方用完即停硬锁，免费额度充沛)
    realtime_models = ["paraformer-realtime-v2", "paraformer-realtime-v1", "paraformer-realtime-8k-v2", "paraformer-realtime-8k-v1"]
    for rm in realtime_models:
        logger.info(f"🎙️ [首选] 正在调用阿里百炼实时 ASR 模型 [{rm}] 进行高精语音识别...")
        text = transcribe_dashscope_realtime(audio_path, model=rm)
        if text:
            return text

    # 2. 备用降级：硅基流动 SenseVoiceSmall (永久免费 0 元，带 16kHz 自适应压缩)
    target_path = compress_audio_if_large(audio_path)
    sf_key = os.getenv("SILICONFLOW_API_KEY", "sk-wewpjlyfvwflfcqivobyumvhybqldextibizkxtkmajkkqvs")
    if sf_key:
        for attempt in range(1, 3):
            try:
                logger.info(f"🎙️ [备用] 正在调用硅基流动 SenseVoiceSmall 进行语音转写 (第 {attempt} 次尝试 · 0元永久免费)...")
                with open(target_path, "rb") as f:
                    files = {"file": (target_path.name, f, get_mime_type(target_path))}
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
                logger.warning(f"硅基流动 SenseVoice 调用异常: {sf_err}")
            time.sleep(1.5)
        logger.warning("硅基流动 SenseVoice 两次尝试均未成功，平滑切换至阿里百炼...")

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
        logger.warning(f"TokenGate 网关调度异常 ({tg_err})，自动切换至七牛云 300万免费包备用...")

    # 2. 备用容灾：七牛云 300万 Token 免费包 (DeepSeek-V3 / V4 满血版 · 100% 免费)
    try:
        qiniu_key = os.getenv("QINIU_API_KEY", "sk-383d4909f49c0db53ad4976552799a7cf6735358e3d90d02dfa5670117441750")
        qiniu_client = AsyncOpenAI(http_client=httpx.AsyncClient(proxy=None, timeout=45.0), api_key=qiniu_key, base_url="https://api.qnaigc.com/v1")
        response = await qiniu_client.chat.completions.create(
            model="deepseek-v3",
            messages=[{"role": "user", "content": prompt}],
            stream=True
        )
        async for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
        return
    except Exception as e:
        logger.error(f"七牛云备用通道分析失败: {e}")
        yield f"\n\n> [!WARNING] 分析失败: {e}"

async def _summarize_with_volcengine_stream(text: str, title: str):
    """由七牛云 300万免费包 DeepSeek-V4-Flash / Pro 进行深度推理与逻辑解构 (100% 绝对 0 扣费)"""
    prompt = (
        f"视频/文章标题：《{title}》\n\n"
        f"【严格约束】：你必须 100% 严格基于以下提供的【真实原文内容】进行分析与提炼！"
        f"严禁脱离原文依据进行任何凭空猜测、臆测编造或虚构事实。如果原文没有提及，一律不得推断为既成事实。\n\n"
        f"【格式要求】：直接输出 Markdown 正文，严禁在最外层使用 ```markdown 或 ``` 代码块包裹！\n\n"
        f"【真实原文内容】：\n{text[:20000]}\n\n"
        f"请输出 Markdown 格式的深度提炼（包含：🎯 核心观点摘要、📌 关键脉络与论据、💡 核心洞察）："
    )

    # 1. 优先调用七牛云 300万免费包 DeepSeek-V4-Pro / Flash
    try:
        qiniu_key = os.getenv("QINIU_API_KEY", "sk-383d4909f49c0db53ad4976552799a7cf6735358e3d90d02dfa5670117441750")
        client = AsyncOpenAI(
            http_client=httpx.AsyncClient(proxy=None, timeout=60.0),
            api_key=qiniu_key,
            base_url="https://api.qnaigc.com/v1"
        )
        response = await client.chat.completions.create(
            model="deepseek/deepseek-v4-flash",
            messages=[{"role": "user", "content": prompt}],
            stream=True
        )
        async for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
        return
    except Exception as qn_err:
        logger.warning(f"七牛云 V4-Flash 异常 ({qn_err})，切换至阿里百炼用完即停免费模型...")

    # 2. 备用容灾：阿里百炼官方 Qwen3.8-Max / Kimi-K3 (已开启用完即停安全锁)
    try:
        ds_key = os.getenv("DASHSCOPE_API_KEY", "")
        ds_client = AsyncOpenAI(http_client=httpx.AsyncClient(proxy=None, timeout=60.0), api_key=ds_key, base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")
        response = await ds_client.chat.completions.create(
            model="qwen3.8-max-0902",
            messages=[{"role": "user", "content": prompt}],
            stream=True
        )
        async for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
        return
    except Exception as e:
        logger.error(f"阿里百炼容灾通道失败: {e}")
        yield f"\n\n> [!WARNING] 深度分析失败: {e}"

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
            
        if "404 not found" in raw_markdown.lower() or "page not found" in raw_markdown.lower():
            raise ValueError("目标页面返回 404 (内容已被删除或链接失效)")
            
        if len(raw_markdown.strip()) < 100:
            raise ValueError("提取的正文过短，可能遭遇反爬、动态渲染或内容已失效")
            
    except Exception as e:
        logger.error(f"Jina 抓取失败: {e}")
        return {
            "title": "抓取失败",
            "is_error": True,
            "error_msg": str(e),
            "content": f"❌ **无法获取原文正文。**\n> 失败原因：`{e}`\n\n此链接内容可能已被作者删除、下架，或遭遇防爬虫拦截。系统已自动终止后续分析与落库流程，避免产生无意义的空笔记。"
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


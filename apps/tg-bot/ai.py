#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
AI 分析模块：使用 Gemini API (多模态音频理解) 进行语音转文字与正文总结
包含自动模型平滑降级机制
"""

import os
import sys
import logging
import mimetypes
from pathlib import Path
import requests

project_root = str(Path(__file__).resolve().parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from config import Config
from openai import OpenAI

logger = logging.getLogger(__name__)

# 预置常用音视频扩展名与 MIME 类型映射，防止 Linux-slim 缺少 /etc/mime.types 时 guess_type 返回 None
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

def get_dashscope_client() -> OpenAI:
    """初始化配置 DashScope API 的 Client"""
    proxies = None
    if Config.HTTP_PROXY:
        proxies = {
            "http://": Config.HTTP_PROXY,
            "https://": Config.HTTPS_PROXY,
        }
    import httpx; return OpenAI(http_client=httpx.Client(proxy=None), 
        api_key=Config.DASHSCOPE_API_KEY,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
    )

def get_deepseek_client() -> OpenAI:
    """初始化配置 DeepSeek API 的 Client"""
    proxies = None
    if Config.HTTP_PROXY:
        proxies = {
            "http://": Config.HTTP_PROXY,
            "https://": Config.HTTPS_PROXY,
        }
    import httpx; return OpenAI(http_client=httpx.Client(proxy=None), 
        api_key=Config.DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com"
    )

import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold

def analyze_audio_with_gemini(audio_path: Path, video_title: str) -> dict:
    """使用 Gemini 1.5 Pro 原生多模态能力分析本地音频"""
    mime_type = get_mime_type(audio_path)
    logger.info(f"开始使用 Gemini API 分析音频: {audio_path} (MIME: {mime_type})")
    
    if Config.HTTP_PROXY:
        os.environ["HTTP_PROXY"] = Config.HTTP_PROXY
        os.environ["HTTPS_PROXY"] = Config.HTTPS_PROXY
        
    genai.configure(api_key=Config.GEMINI_API_KEY)
    uploaded_file = None
    try:
        logger.info("开始上传音频到 Gemini...")
        uploaded_file = genai.upload_file(path=str(audio_path), mime_type=mime_type)
        logger.info(f"音频上传成功，File URI: {uploaded_file.uri}")

        prompt = f"""你是一个高效的个人知识管理 (PKM) AI 助手。
我为你上传了一段完整的音频（视频标题为：《{video_title}》）。
请你仔细聆听这段音频的全部内容，然后直接输出以下 Markdown 格式的深度总结（不要废话）：

### 核心摘要
- [用 3-5 句精炼的话总结本视频的核心观点和要点]

### 详细提炼
- (根据视频长短，列出 3-8 点详细的核心逻辑、数据论证或事实细节，请尽可能详尽还原播主的深度思考)

### 关键标签
- 推荐 3-5 个分类标签（例如：#股市分析 #投资策略 #个人知识管理 #AI硬件等）
"""
        model = genai.GenerativeModel("gemini-1.5-pro")
        logger.info("正在等待 Gemini 1.5 Pro 生成分析报告...")
        safety_settings = {
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
        }
        try:
            response = model.generate_content([uploaded_file, prompt], safety_settings=safety_settings)
        except Exception as api_err:
            if "429" in str(api_err) or "exhausted" in str(api_err).lower() or "quota" in str(api_err).lower():
                logger.warning(f"Gemini 1.5 Pro 额度耗尽，自动降级至 Gemini 1.5 Flash: {api_err}")
                model_flash = genai.GenerativeModel("gemini-1.5-flash")
                response = model_flash.generate_content([uploaded_file, prompt], safety_settings=safety_settings)
            else:
                raise
        logger.info("Gemini 分析完成！")
        return {
            "title": video_title,
            "content": response.text,
        }
    except Exception as e:
        logger.error(f"Gemini 音频分析异常: {e}")
        raise RuntimeError(f"Gemini API 处理音频失败: {e}")
    finally:
        if uploaded_file:
            try:
                genai.delete_file(uploaded_file.name)
                logger.info(f"清理了 Gemini 云端的临时文件: {uploaded_file.name}")
            except Exception as clean_e:
                logger.warning(f"清理临时文件失败: {clean_e}")

import dashscope
from dashscope import MultiModalConversation

def analyze_audio_with_qwen(audio_path: Path, video_title: str) -> dict:
    """使用百炼的两步走平替方案分析音频 (ASR + LLM)"""
    logger.info(f"开始使用 百炼 (平替两步走) 分析音频: {audio_path}")
            
    dashscope.api_key = Config.DASHSCOPE_API_KEY
    
    # 第一步：使用 paraformer-v1 (有免费额度) 进行语音转文字
    logger.info("百炼平替步骤一：正在上传音频进行语音转写(ASR)...")
    try:
        from dashscope.audio.asr import Transcription
        task = Transcription.async_call(model='paraformer-v1', file_urls=[f"file://{audio_path.absolute()}"])
        task_response = Transcription.wait(task=task.output.task_id)
        
        if task_response.status_code != 200:
            logger.error(f"百炼 ASR 失败: {task_response.message}")
            raise RuntimeError(f"百炼 ASR 失败: {task_response.message}")
            
        transcript_text = ""
        for result in task_response.output.results:
            if result.subtask_status == 'SUCCEEDED':
                url = result.transcription_url
                import requests
                res = requests.get(url, timeout=30)
                data = res.json()
                if "transcripts" in data and len(data["transcripts"]) > 0:
                    transcript_text += data["transcripts"][0].get("text", "")
                    
        if not transcript_text:
            raise RuntimeError("百炼 ASR 未能提取出有效文本 (转写结果为空)")
            
        logger.info(f"百炼平替步骤一完成，成功提取字数: {len(transcript_text)}")
    except Exception as e:
        logger.error(f"百炼 ASR 步骤异常: {e}")
        raise RuntimeError(f"百炼 ASR 处理音频失败: {e}")

    # 第二步：使用大语言模型进行文本总结
    logger.info("百炼平替步骤二：启动大语言模型进行总结...")
    prompt = f"""你是一个高效的个人知识管理 (PKM) AI 助手。
我为你提供了一段完整的视频/音频转录文本（视频标题为：《{video_title}》）。
请你仔细阅读这段转录文本的内容，然后直接输出以下 Markdown 格式的深度总结（不要废话）：

### 核心摘要
- [用 3-5 句精炼的话总结本视频的核心观点和要点]

### 详细提炼
- (根据内容长短，列出 3-8 点详细的核心逻辑、数据论证或事实细节，请尽可能详尽还原播主的深度思考)

### 关键标签
- 推荐 3-5 个分类标签（例如：#股市分析 #投资策略 #个人知识管理 #AI硬件等）

========== 以下是语音转录出来的文本 ==========
{transcript_text}
"""
    try:
        from dashscope import Generation
        response = Generation.call(
            model='qwen3.7-flash-2026-07-15',
            messages=[{'role': 'user', 'content': prompt}]
        )
        
        if response.status_code == 200:
            content = response.output.choices[0].message.content
            logger.info("百炼 (Qwen) 平替两步走分析全部完成！")
            return {
                "title": video_title,
                "content": content
            }
        else:
            logger.error(f"百炼 LLM 失败: {response.code} - {response.message}")
            raise RuntimeError(f"百炼 LLM 失败: {response.message}")
            
    except Exception as e:
        logger.error(f"百炼 LLM 分析异常: {e}")
        raise RuntimeError(f"百炼 LLM 总结文本失败: {e}")

def analyze_web_url(url: str) -> dict:
    """使用 Jina Reader 抓取网页正文并由 Gemini 提炼总结"""
    logger.info(f"正在使用 Jina Reader 抓取网页: {url}")
    jina_url = f"https://r.jina.ai/{url}"
    
    proxies = {}
    if Config.HTTP_PROXY:
        proxies["http"] = Config.HTTP_PROXY
        proxies["https"] = Config.HTTPS_PROXY

    try:
        resp = requests.get(jina_url, proxies=proxies, timeout=30)
        resp.raise_for_status()
        raw_markdown = resp.text
    except Exception as e:
        logger.error(f"Jina 抓取失败: {e}")
        raw_markdown = f"抓取正文失败: {e}"

    logger.info("开始使用 DashScope API 分析网页正文...")
    client = get_dashscope_client()
    prompt = f"""你是一个高效的个人知识管理 AI 助手。请分析以下网页/文章正文：

原始链接: {url}

{raw_markdown[:8000]}

请在输出的第一行写上文章标题，格式为：
标题：你的文章标题

### 核心要点总结
- 3-5 句核心观点总结

### 推荐标签
- 3-5 个相关标签

---

### 抓取正文
{raw_markdown[:15000]}
"""

    title = "网页/文章剪藏"
    # 尝试从 Jina Markdown 开头提取 Title
    for line in raw_markdown.splitlines()[:5]:
        if line.startswith("Title:"):
            title = line.replace("Title:", "").strip()
            break

    try:
        response = client.chat.completions.create(
            model="qwen3.7-flash",
            messages=[{"role": "user", "content": prompt}],
            stream=False
        )
        summary_text = response.choices[0].message.content
        # 尝试从 AI 输出提取第一行标题
        first_line = summary_text.splitlines()[0] if summary_text else ""
        if "标题：" in first_line or "标题:" in first_line:
            ai_title = first_line.split("：")[-1].split(":")[-1].strip()
            if ai_title:
                title = ai_title

        return {
            "title": title,
            "content": summary_text
        }
    except Exception as e:
        logger.error(f"Gemini 网页分析失败: {e}")
        return {
            "title": title,
            "content": raw_markdown
        }

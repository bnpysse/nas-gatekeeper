#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
AI 分析服务：调用 Gemini API (支持 Gemini Flash 多模态音频理解) 进行语音转文字与文章总结
优先使用最新的 gemini-flash-latest / gemini-3.6-flash 模型
"""

import os
import sys
import logging
from pathlib import Path
import requests

parent_dir = str(Path(__file__).resolve().parent.parent)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from config import Config
from google import genai

logger = logging.getLogger(__name__)

def get_gemini_client() -> genai.Client:
    """初始化配置有 API Key 和 Proxy 的 Gemini Client"""
    if Config.HTTP_PROXY:
        os.environ["HTTP_PROXY"] = Config.HTTP_PROXY
        os.environ["http_proxy"] = Config.HTTP_PROXY
    if Config.HTTPS_PROXY:
        os.environ["HTTPS_PROXY"] = Config.HTTPS_PROXY
        os.environ["https_proxy"] = Config.HTTPS_PROXY

    return genai.Client(api_key=Config.GEMINI_API_KEY)

def generate_with_fallback(client: genai.Client, contents) -> str:
    """优先使用极速最新模型 (gemini-flash-latest -> gemini-3.6-flash -> gemini-2.5-flash)"""
    models_to_try = ["gemini-flash-latest", "gemini-3.6-flash", "gemini-2.5-flash", "gemini-2.0-flash"]
    last_err = None

    for model_name in models_to_try:
        try:
            logger.info(f"正在尝试使用 Gemini 最新模型: {model_name}")
            response = client.models.generate_content(
                model=model_name,
                contents=contents
            )
            if response and response.text:
                return response.text
        except Exception as e:
            logger.warning(f"模型 {model_name} 请求失败: {e}，尝试下一个模型...")
            last_err = e

    raise RuntimeError(f"所有 Gemini 模型请求失败，最后错误: {last_err}")

def analyze_audio_with_gemini(audio_path: Path, video_title: str) -> dict:
    """
    将 MP3 音频文件上传至 Gemini File API 并提炼总结与逐字稿
    """
    logger.info(f"开始使用 Gemini API 分析音频: {audio_path}")
    client = get_gemini_client()

    uploaded_file = client.files.upload(file=audio_path)
    logger.info(f"音频文件已上传至 Gemini File API: {uploaded_file.name}")

    prompt = f"""你是一个高效的个人知识管理 (PKM) AI 助手。
请分析附带的音频内容（视频标题为：《{video_title}》）。

请按照以下 Markdown 格式输出分析结果：

### 核心摘要
- [用 3-5 句精炼的话总结本视频的核心观点和要点]

### 关键标签
- 推荐 3-5 个分类标签（例如：#视频转录 #AI #知识管理）

---

### 完整逐字稿转录
[请将音频中的中文语音尽可能完整准确地转写为文字稿。如有标点符号和段落分段，请合理整理。]
"""

    try:
        result_text = generate_with_fallback(client, [uploaded_file, prompt])
        
        try:
            client.files.delete(name=uploaded_file.name)
        except Exception as e:
            logger.warning(f"清理 Gemini 临时文件失败: {e}")

        return {
            "title": video_title,
            "content": result_text,
        }

    except Exception as e:
        logger.error(f"Gemini 音频分析异常: {e}")
        raise RuntimeError(f"Gemini API 处理音频失败: {e}")

def analyze_web_url(url: str) -> dict:
    """
    使用 Jina Reader (https://r.jina.ai/<URL>) 抓取网页并由 Gemini 进行总结
    """
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
        raw_markdown = f"抓取原文失败: {e}"

    client = get_gemini_client()
    prompt = f"""你是一个高效的个人知识管理 AI 助手。请分析以下网页文本：

原始链接: {url}

{raw_markdown[:8000]}

请按以下格式输出：
### 核心要点总结
- 3-5 句核心观点总结

### 推荐标签
- 3-5 个标签

---

### 抓取正文
{raw_markdown[:15000]}
"""

    try:
        summary_text = generate_with_fallback(client, prompt)
        return {
            "title": "网页剪藏与分析",
            "content": summary_text
        }
    except Exception as e:
        logger.error(f"Gemini 网页分析失败: {e}")
        return {
            "title": "网页剪藏 (未经AI总结)",
            "content": raw_markdown
        }

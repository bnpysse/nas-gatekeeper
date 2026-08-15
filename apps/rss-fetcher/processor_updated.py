import os
import json
import urllib.request
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_PKM_API_KEY", os.getenv("GEMINI_API_KEY")))

def translate_with_ollama(text: str) -> str:
    if not text or not text.strip():
        return ""
    
    url = 'http://localhost:11434/api/generate'
    prompt = f"请将以下英文文本翻译成流畅、专业、易懂的中文。不要做任何删改或总结，只需直接返回中文翻译结果：\n\n{text}"
    data = {
        'model': 'qwen2.5:7b',
        'prompt': prompt,
        'stream': False
    }
    req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8'), headers={'Content-Type': 'application/json'})
    
    try:
        print("⏳ 正在使用本地 Qwen2.5 翻译长文本 (这可能需要一两分钟)...")
        with urllib.request.urlopen(req, timeout=600) as response:
            result = json.loads(response.read().decode())
            return result.get('response', '').strip()
    except Exception as e:
        print(f"⚠️ Ollama 本地翻译失败: {e}")
        return text

def generate_content_with_fallback(prompt: str) -> str:
    models_to_try = [
        'gemini-3.6-flash-latest',
        'gemini-3.6-flash',
        'gemini-2.5-flash-latest',
        'gemini-2.5-flash',
        'gemini-2.0-flash'
    ]
    
    for model_name in models_to_try:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
            )
            return response.text
        except Exception as e:
            print(f"⚠️ 模型 {model_name} 调用失败: {e}。尝试降级...")
            continue
            
    raise RuntimeError("❌ 所有 Gemini 模型均调用失败。")

def analyze_github_repo(repo_url: str, readme_content: str) -> tuple:
    translated_text = translate_with_ollama(readme_content[:15000])
    prompt = f"""你是一个资深的开源技术专家。我给你一个 Github 项目的链接和它翻译后的 README 内容。
请帮我生成一份结构化的中文分析报告，适合存入 Obsidian。

项目链接: {repo_url}

翻译后的 README:
{translated_text[:10000]}

请输出以下 Markdown 结构:
# [推测的项目名称]

## 📝 一句话简介
(用一句话概括这个项目是干什么的)

## 🛠 技术栈
(推测其主要的技术栈)

## 🌟 核心亮点
(3-5点核心优势)

## 🎯 适用场景
(适合用来解决什么问题)
"""
    summary = generate_content_with_fallback(prompt)
    return translated_text, summary

def analyze_ebook(filename: str, description: str = "") -> str:
    prompt = f"我刚刚收到了一本电子书。\n文件名: {filename}\n发布者描述/简介: {description}\n请生成书籍卡片。"
    return generate_content_with_fallback(prompt)

def analyze_youtube_transcript(video_title: str, channel_name: str, video_url: str, transcript_text: str) -> tuple:
    raw_text = transcript_text[:50000]
    translated_text = translate_with_ollama(raw_text)
    
    prompt = f"""
    你是一位顶级的知识提炼专家。我为你提供了一个经过本地大模型翻译的 YouTube 视频中文记录。
    请帮我进行“脱水”处理，提炼出最核心的干货。
    
    频道名称: {channel_name}
    视频标题: {video_title}
    视频链接: {video_url}
    
    翻译后的字幕:
    {translated_text[:15000]}
    
    请输出以下 Markdown 结构，直接返回内容，不要额外的寒暄：
    # 🎬 {video_title}
    
    **来源频道**: {channel_name}
    **视频链接**: {video_url}
    
    ## 📝 核心主旨 (TL;DR)
    (用一两百字概括)
    
    ## 💡 关键知识点 / 核心观点
    (分条列出关键点展开)
    """
    summary = generate_content_with_fallback(prompt)
    return translated_text, summary

def analyze_reddit_post(title: str, sub_name: str, url: str, content: str) -> tuple:
    translated_text = translate_with_ollama(content[:15000])
    
    prompt = f"""你是一个专业的技术情报分析师。
请阅读以下已经被翻译成中文的 Reddit {sub_name} 版块的热门帖子，撰写一份高质量的精华简报。

帖子标题：{title}
帖子链接：{url}

翻译后的正文：
{translated_text[:10000]} 

要求：
1. 用一段话总结核心信息（TL;DR）。
2. 列出核心观点或技术细节。
3. 提炼其讨论的【核心痛点】。
4. 使用 Markdown 格式。
"""
    summary = generate_content_with_fallback(prompt)
    return translated_text, summary

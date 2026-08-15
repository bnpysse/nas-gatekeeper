import os
import time
import json
import urllib.request
import httpx
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

def translate_with_ollama(text: str) -> str:
    if not text or not text.strip():
        return ""
    
    url = 'http://localhost:11434/api/generate'
    system_prompt = "你是一位专业的资深中英文翻译专家。你的任务是将用户提供的英文文本完美翻译为中文，且不丢失任何细节。必须严格保留原文的段落换行、Markdown符号及排版格式。不要做任何删改、不要总结，也不要输出任何无关的解释性文字，只需返回直接的中文翻译结果。"
    prompt = f"请翻译以下文本：\n\n{text}"
    data = {
        'model': 'qwen2.5:7b',
        'system': system_prompt,
        'prompt': prompt,
        'stream': False
    }
    req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8'), headers={'Content-Type': 'application/json'})
    
    try:
        print("⏳ 正在使用本地 Qwen2.5 (7B) 翻译长文本 (这可能需要几分钟)...")
        with urllib.request.urlopen(req, timeout=1800) as response:
            result = json.loads(response.read().decode())
            return result.get('response', '').strip()
    except Exception as e:
        print(f"⚠️ Ollama 本地翻译失败: {e}")
        return text

def generate_summary_with_dashscope(content: str, is_raw_content: bool = True) -> str:
    """
    使用 DashScope API 生成总结
    """
    api_key = os.environ.get("DASHSCOPE_API_KEY")
    if not api_key:
        print("未设置 DASHSCOPE_API_KEY 环境变量，跳过总结。")
        return ""
        
    client = OpenAI(
        api_key=api_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        http_client=httpx.Client(trust_env=False)
    )
    
    if is_raw_content:
        prompt = f"""你是一个高效的知识管理助手。请对以下内容进行简短总结，提取核心观点，并输出 3-5 个中文标签。
格式要求：
### 核心总结
- [要点1]
- [要点2]

### 标签
#标签1 #标签2

内容：
{content[:8000]}
"""
    else:
        prompt = content
    try:
        response = client.chat.completions.create(
            model="qwen-plus",
            messages=[{"role": "user", "content": prompt}],
            stream=False
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"DashScope 生成总结失败: {e}")
        return "摘要生成失败。"

def analyze_github_repo(repo_url: str, readme_content: str) -> tuple:
    translated_text = translate_with_ollama(readme_content[:15000])
    summary = generate_summary_with_dashscope(translated_text)
    return translated_text, summary

def analyze_youtube_transcript(video_title: str, channel_name: str, video_url: str, transcript_text: str) -> tuple:
    raw_text = transcript_text[:50000]
    translated_text = translate_with_ollama(raw_text)
    
    summary = generate_summary_with_dashscope(translated_text)
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
    summary = generate_summary_with_dashscope(prompt, is_raw_content=False)
    return translated_text, summary

def analyze_blog_post(title: str, blog_name: str, url: str, content: str) -> tuple:
    translated_text = translate_with_ollama(content[:25000])
    prompt = f"""你是一个专业的技术与商业分析师。
请阅读以下已经被翻译成中文的知名博客/Newsletter文章，撰写一份高质量的精华简报。

来源专栏：{blog_name}
文章标题：{title}
文章链接：{url}

翻译后的正文：
{translated_text[:15000]} 

要求：
1. 用一段话总结核心主旨（TL;DR）。
2. 列出文章的核心观点或技术/商业洞察（深度展开）。
3. 提炼其对行业的【启发与影响】。
4. 使用 Markdown 格式。
"""
    summary = generate_summary_with_dashscope(prompt, is_raw_content=False)
    return translated_text, summary

import os
import time
import json
import re
import httpx
from dotenv import load_dotenv
from pathlib import Path
from openai import OpenAI

env_paths = [
    Path("/opt/SecondBrain-Flow/.env"),
    Path(__file__).parent.parent / ".env",
    Path(__file__).parent.parent.parent / ".env"
]
for p in env_paths:
    if p.exists():
        load_dotenv(dotenv_path=p)
        break
else:
    load_dotenv()

VOLCENGINE_API_KEY = os.getenv("VOLCENGINE_API_KEY", "")
VOLCENGINE_ENDPOINT_ID = os.getenv("VOLCENGINE_ENDPOINT_ID", "ep-20260809122445-td2g2")

if not VOLCENGINE_API_KEY:
    print("⚠️ 警告: 未找到 VOLCENGINE_API_KEY 环境变量！")

def get_deepseek_client() -> OpenAI:
    return OpenAI(
        api_key=VOLCENGINE_API_KEY,
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        http_client=httpx.Client(trust_env=False) # Bypass proxy if any
    )

def is_primarily_chinese(text: str) -> bool:
    """判断文本是否主要为中文"""
    chinese_chars = len(re.findall(r'[\u4e00-\u9fa5]', text))
    return chinese_chars > 30 and (chinese_chars / max(1, len(text[:500]))) > 0.2

def translate_with_deepseek(text: str) -> str:
    if not text or not text.strip():
        return ""
        
    # 如果原文主要已经是中文，直接保留原文，避免误触发中英翻译任务
    if is_primarily_chinese(text):
        return text
        
    client = get_deepseek_client()
    system_prompt = "你是一位专业的资深中英文翻译专家。你的任务是将用户提供的英文文本完美翻译为中文。为了保留英文原意，请直接返回'原文+中文翻译'的混合排版格式。即：一段英文，紧跟着一段对应的中文翻译。必须严格保留原文的Markdown符号及排版格式。若输入本身已是中文，请原样返回。"
    prompt = f"请翻译以下文本：\n\n{text}"
    
    try:
        print("⏳ 正在使用火山方舟 DeepSeek 进行全文翻译 (含中英对照)...")
        response = client.chat.completions.create(
            model=VOLCENGINE_ENDPOINT_ID,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            stream=False,
            timeout=300
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"⚠️ DeepSeek 翻译失败: {e}")
        return text

def generate_summary_with_deepseek(content: str, is_raw_content: bool = True) -> str:
    client = get_deepseek_client()
    
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
        print("⏳ 正在使用火山方舟 DeepSeek 生成深度简报...")
        response = client.chat.completions.create(
            model=VOLCENGINE_ENDPOINT_ID,
            messages=[
                {"role": "system", "content": "你是一个专业的情报分析师。"},
                {"role": "user", "content": prompt}
            ],
            stream=False,
            timeout=300
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"⚠️ DeepSeek 生成总结失败: {e}")
        return "摘要生成失败。"

def analyze_github_repo(repo_url: str, readme_content: str) -> tuple:
    translated_text = translate_with_deepseek(readme_content[:15000])
    summary = generate_summary_with_deepseek(translated_text)
    return translated_text, summary

def analyze_youtube_transcript(video_title: str, channel_name: str, video_url: str, transcript_text: str) -> tuple:
    raw_text = transcript_text[:30000]
    translated_text = translate_with_deepseek(raw_text)
    
    prompt = f"""你是一个专业的情报与音视频内容分析专家。
请阅读以下音视频逐字稿，撰写一份结构严密、洞察深刻的深度精读简报。

视频标题：{video_title}
频道来源：{channel_name}
视频链接：{video_url}

逐字稿内容：
{translated_text[:15000]}

要求：
1. **🌟 核心要义 (TL;DR)**：用一段精炼的话总结视频的核心观点。
2. **📈 关键论点与核心论据 (Key Takeaways)**：分条展开 3-5 个核心论点与数据案例。
3. **💡 决策启示或行动建议 (Actionable Insights)**：对观众或投资者的核心启发。
4. 使用 Markdown 格式。
"""
    summary = generate_summary_with_deepseek(prompt, is_raw_content=False)
    return translated_text, summary

def analyze_reddit_post(title: str, sub_name: str, url: str, content: str) -> tuple:
    translated_text = translate_with_deepseek(content[:15000])
    prompt = f"""你是一个专业的技术情报分析师。
请阅读以下中英对照的 Reddit {sub_name} 版块的热门帖子，撰写一份高质量的精华简报。

帖子标题：{title}
帖子链接：{url}

正文：
{translated_text[:10000]} 

要求：
1. 用一段话总结核心信息（TL;DR）。
2. 列出核心观点或技术细节。
3. 提炼其讨论的【核心痛点】。
4. 使用 Markdown 格式。
"""
    summary = generate_summary_with_deepseek(prompt, is_raw_content=False)
    return translated_text, summary

def analyze_blog_post(title: str, blog_name: str, url: str, content: str) -> tuple:
    translated_text = translate_with_deepseek(content[:25000])
    prompt = f"""你是一个专业的技术与商业分析师。
请阅读以下中英对照的知名博客/Newsletter文章，撰写一份高质量的精华简报。

来源专栏：{blog_name}
文章标题：{title}
文章链接：{url}

正文：
{translated_text[:15000]} 

要求：
1. 用一段话总结核心主旨（TL;DR）。
2. 列出文章的核心观点或技术/商业洞察（深度展开）。
3. 提炼其对行业的【启发与影响】。
4. 使用 Markdown 格式。
"""
    summary = generate_summary_with_deepseek(prompt, is_raw_content=False)
    return translated_text, summary

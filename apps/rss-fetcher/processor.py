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

DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
SILICONFLOW_API_KEY = os.getenv("SILICONFLOW_API_KEY", "")

def get_deepseek_client() -> tuple:
    """获取 100% 传统免费大模型客户端 (优先 TokenGate 网关 ➔ 阿里百炼 ➔ 硅基流动)"""
    # 1. 优先尝试本地/远程 TokenGate 中央网关
    for base_url in ["http://127.0.0.1:8800/v1", "https://tg.donglida.com/v1", "https://tg.donglida.xyz/v1"]:
        try:
            with httpx.Client(timeout=3.0, trust_env=False) as c:
                r = c.get(f"{base_url}/models")
                if r.status_code == 200:
                    return OpenAI(
                        api_key="tg-sk",
                        base_url=base_url,
                        http_client=httpx.Client(trust_env=False, timeout=httpx.Timeout(60.0))
                    ), "auto"
        except Exception:
            pass

    # 2. 直连七牛云 (300万 Token 免费包，满血 DeepSeek-V3 / Flash)
    qiniu_key = os.getenv("QINIU_API_KEY", "sk-383d4909f49c0db53ad4976552799a7cf6735358e3d90d02dfa5670117441750")
    if qiniu_key:
        return OpenAI(
            api_key=qiniu_key,
            base_url="https://api.qnaigc.com/v1",
            http_client=httpx.Client(trust_env=True, timeout=httpx.Timeout(60.0))
        ), "deepseek/deepseek-v4-flash"

    # 3. 直连阿里百炼 DashScope (qwen3.8-max-0902 / qwen3.7-flash 用完即停安全池)
    if DASHSCOPE_API_KEY:
        return OpenAI(
            api_key=DASHSCOPE_API_KEY,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            http_client=httpx.Client(trust_env=False, timeout=httpx.Timeout(60.0))
        ), "qwen3.7-flash"

def is_primarily_chinese(text: str) -> bool:
    """判断文本是否主要为中文"""
    chinese_chars = len(re.findall(r'[\u4e00-\u9fa5]', text))
    return chinese_chars > 30 and (chinese_chars / max(1, len(text[:500]))) > 0.2

def clean_markdown_fence(text: str) -> str:
    """彻底剥离大模型在整篇回复外层误加的 ```markdown ... ``` 代码块包裹"""
    if not text:
        return ""
    body = text.strip()
    if body.startswith("```markdown"):
        body = re.sub(r'^\s*```markdown\s*\n', '', body)
    elif body.startswith("```") and not body.startswith("```mermaid"):
        body = re.sub(r'^\s*```\s*\n', '', body)
    if body.endswith("```") and body.count("```") % 2 == 1:
        body = re.sub(r'\n```\s*$', '', body)
    return body.strip()

def convert_mermaid_to_image(content: str) -> str:
    """将文本中的 ```mermaid ... ``` 代码块转为 base64 编码的直接可渲染矢量 SVG 图片链接 (并附带折叠源码)"""
    import base64
    import json
    pattern = r'```mermaid\s*\n(.*?)\n```'
    def _repl(match):
        code = match.group(1).strip()
        obj = {"code": code, "mermaid": {"theme": "default"}}
        b64 = base64.b64encode(json.dumps(obj).encode('utf-8')).decode('ascii')
        svg_url = f"https://mermaid.ink/svg/{b64}"
        return f"\n\n![架构流程图]({svg_url})\n\n<details><summary>📊 查看 Mermaid 流程图源码</summary>\n\n```mermaid\n{code}\n```\n</details>\n\n"
    return re.sub(pattern, _repl, content, flags=re.DOTALL)

def postprocess_markdown(text: str) -> str:
    """综合后处理：清洗外层包裹并转换图表"""
    return convert_mermaid_to_image(clean_markdown_fence(text))


def translate_with_deepseek(text: str) -> str:
    if not text or not text.strip():
        return ""
        
    # 如果原文主要已经是中文，直接保留原文，避免误触发中英翻译任务
    if is_primarily_chinese(text):
        return text
        
    client, model_name = get_deepseek_client()
    system_prompt = "你是一位专业的资深中英文翻译专家。你的任务是将用户提供的英文文本完美翻译为中文。为了保留英文原意，请直接返回'原文+中文翻译'的混合排版格式。即：一段英文，紧跟着一段对应的中文翻译。必须严格保留原文的Markdown符号及排版格式。若输入本身已是中文，请原样返回。"
    
    # 截断输入避免爆上下文与超时
    truncated_input = text[:5000]
    prompt = f"请翻译以下文本：\n\n{truncated_input}"
    
    try:
        print("⏳ 正在使用 AI 引擎进行全文翻译 (含中英对照)...")
        stream = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            stream=True,
            temperature=0.3,
            max_tokens=4096
        )
        chunks = []
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                chunks.append(chunk.choices[0].delta.content)
        result = "".join(chunks).strip()
        return result if result else text
    except Exception as e:
        print(f"⚠️ 翻译调用失败: {e}")
        return text

def generate_summary_with_deepseek(content: str, is_raw_content: bool = True) -> str:
    client, model_name = get_deepseek_client()
    
    if is_raw_content:
        prompt = f"""你是一个高效的知识管理助手。请对以下内容进行简短总结，提取核心观点，并输出 3-5 个中文标签。
格式要求：
### 核心总结
- [要点1]
- [要点2]

### 标签
#标签1 #标签2

内容：
{content[:6000]}
"""
    else:
        prompt = content[:6000]
        
    try:
        print("⏳ 正在使用 AI 引擎生成深度简报...")
        stream = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": "你是一个专业的情报分析师。"},
                {"role": "user", "content": prompt}
            ],
            stream=True,
            temperature=0.3,
            max_tokens=4096
        )
        chunks = []
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                chunks.append(chunk.choices[0].delta.content)
        result = "".join(chunks).strip()
        return postprocess_markdown(result) if result else "摘要生成为空。"
    except Exception as e:
        print(f"⚠️ 生成总结失败: {e}")
        return "摘要生成失败。"

def analyze_github_repo(repo_url: str, readme_content: str) -> tuple:
    clean_readme = readme_content[:4000] if readme_content else "README content unavailable."
    try:
        translated_text = translate_with_deepseek(clean_readme)
    except Exception as e:
        print(f"⚠️ Github 翻译跳过: {e}")
        translated_text = clean_readme
    try:
        summary = generate_summary_with_deepseek(translated_text)
    except Exception as e:
        print(f"⚠️ Github 简报跳过: {e}")
        summary = "Github 仓库简报生成失败。"
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

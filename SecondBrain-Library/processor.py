import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

# 初始化 DashScope 客户端
client = OpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
)

def generate_content_with_fallback(prompt: str) -> str:
    """调用阿里百炼的 qwen3.7-flash 模型"""
    try:
        response = client.chat.completions.create(
            model="qwen3.7-plus",
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"⚠️ DashScope 模型调用失败: {e}")
        raise RuntimeError("❌ 调用失败，请检查您的 API Key 或网络环境。")

def analyze_github_repo(repo_url: str, readme_content: str) -> str:
    """
    使用 DashScope 分析 Github 仓库的 README 并生成 Markdown 摘要
    """
    prompt = f"""
    你是一个资深的开源技术专家。我给你一个 Github 项目的链接和它的 README 内容。
    请帮我生成一份结构化的中文分析报告，适合存入 Obsidian。
    
    项目链接: {repo_url}
    
    README 内容:
    {readme_content[:15000]} # 截断以防超出 token 限制
    
    请输出以下 Markdown 结构:
    # [项目名称]
    
    ## 📝 一句话简介
    (用一句话概括这个项目是干什么的)
    
    ## 🛠 技术栈
    (列出主要的技术栈，如 Python, React, Rust 等)
    
    ## 🌟 核心亮点
    (3-5点核心优势或创新点)
    
    ## 🎯 适用场景
    (这个项目适合用来解决什么问题)
    """
    return generate_content_with_fallback(prompt)

def analyze_ebook(filename: str, description: str = "") -> str:
    """
    分析电子书信息，生成书签和简介
    """
    prompt = f"""
    我刚刚在 Telegram 上收到了一本电子书。
    文件名: {filename}
    发布者描述/简介: {description}
    
    请帮我生成一份适合存入 Obsidian 的书籍卡片，Markdown 格式。
    请从文件名和描述中推断书名、作者（如果可能），并给出一个分类建议。
    
    结构如下：
    # 📖 [推断书名]
    
    **作者**: (如果未知填未知)
    **类别**: (例如: 技术编程, 金融投资, 文学等)
    **文件**: `{filename}`
    
    ## 💡 内容简介
    (基于提供的信息，生成一个简短的内容介绍)
    """
    return generate_content_with_fallback(prompt)

def analyze_youtube_transcript(video_title: str, channel_name: str, video_url: str, transcript_text: str) -> str:
    """
    使用 DashScope 分析 YouTube 视频字幕并生成深度总结
    """
    prompt = f"""
    你是一位顶级的知识提炼专家（精通金融投资、AI科技、编程架构等领域）。
    我为你提供了一个 YouTube 视频的完整字幕记录。由于口语化严重且冗长，请你帮我进行“脱水”处理，提炼出最核心的干货。
    
    频道名称: {channel_name}
    视频标题: {video_title}
    视频链接: {video_url}
    
    字幕文本:
    {transcript_text[:50000]} # 防止超长，截取前 50000 字符（约半小时内容）
    
    请输出以下 Markdown 结构，直接返回内容，不要额外的寒暄：
    # 🎬 {video_title}
    
    **来源频道**: {channel_name}
    **视频链接**: {video_url}
    
    ## 📝 核心主旨 (TL;DR)
    (用一两百字概括这个视频最核心的结论或主旨)
    
    ## 💡 关键知识点 / 核心观点
    (分条列出视频中提到的关键技术点、市场预测、核心逻辑等，建议 3-5 点，需详细展开)
    
    ## 🏷️ 提及的重要概念/公司/代码
    (如果是财经类，列出提及的股票代码；如果是技术类，列出提到的框架或项目名称)
    """
    return generate_content_with_fallback(prompt)

def analyze_article(title: str, author_or_feed: str, url: str, content: str) -> str:
    """
    使用 DashScope 分析长文章/资讯并生成深度总结 (专用于 Substack/RSS 等文字媒体)
    """
    prompt = f"""
    你是一位顶级的知识提炼专家（精通科技、AI、半导体供应链、编程架构等领域）。
    我为你提供了一篇 Substack/RSS 文章的内容。请你帮我进行“脱水”处理，提炼出最核心的干货。
    
    专栏/作者: {author_or_feed}
    文章标题: {title}
    文章链接: {url}
    
    文章内容:
    {content[:30000]} # 防止超长，截取前 30000 字符
    
    请输出以下 Markdown 结构，直接返回内容，不要额外的寒暄：
    # 📰 {title}
    
    **来源**: {author_or_feed}
    **链接**: {url}
    
    ## 📝 核心主旨 (TL;DR)
    (用一段话概括这篇文章最核心的结论或主旨)
    
    ## 💡 关键知识点 / 核心观点
    (分条列出文章中提到的关键技术点、行业趋势、核心逻辑等，建议 3-5 点，需详细展开)
    
    ## 🏷️ 提及的重要概念/公司/模型
    (列出提到的公司、AI模型架构、工具框架或行业专业词汇)
    """
    return generate_content_with_fallback(prompt)

def analyze_reddit_post(title: str, subreddit: str, url: str, content: str) -> str:
    """
    使用 DashScope 分析 Reddit 帖子并生成干货总结
    """
    prompt = f"""
    你是一位顶级的知识提炼专家（精通科技、AI、硬件等领域）。
    我为你提供了一篇 Reddit ({subreddit}) 上的热门帖子内容及部分高赞评论。请你帮我进行“脱水”处理，提炼出最核心的干货和社区共识。
    
    帖子标题: {title}
    帖子链接: {url}
    
    帖子及评论内容:
    {content[:30000]}
    
    请输出以下 Markdown 结构，直接返回内容，不要额外的寒暄：
    # 👾 {title}
    
    **来源**: {subreddit}
    **链接**: {url}
    
    ## 📝 核心主旨 (TL;DR)
    (用一段话概括这篇帖子的核心讨论内容或新闻)
    
    ## 💡 社区核心观点 / 争议点
    (分条列出帖子内容和评论区的高赞观点、网友共识、重要争议或技术解析，3-5 点)
    
    ## 🏷️ 提及的重要概念/项目/术语
    (列出提到的开源项目、工具、硬件型号或专业词汇)
    """
    return generate_content_with_fallback(prompt)

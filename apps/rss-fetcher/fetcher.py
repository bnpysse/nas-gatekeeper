import os
import asyncio
from telethon import TelegramClient, events
from dotenv import load_dotenv
import re
from processor import analyze_github_repo, analyze_ebook

load_dotenv()

# 初始化环境变量
API_ID = os.getenv("TG_API_ID")
API_HASH = os.getenv("TG_API_HASH")

# 您在 list_channels.py 找出的目标频道 ID 填在这里
# 例如: [-1001234567, -1009876543]
TARGET_CHANNELS = [] 

# 输出到 Vault 的路径
VAULT_PATH = "/Users/woodman/dev/nas-gatekeeper/SecondBrain-Quartz/content/notes/TG_Clippings"

if not API_ID or not API_HASH:
    raise ValueError("请在 .env 中设置 TG_API_ID 和 TG_API_HASH")

client = TelegramClient('session_gatekeeper', int(API_ID), API_HASH)

def save_to_vault(filename: str, content: str):
    """
    保存 Markdown 到 Obsidian Vault
    """
    os.makedirs(VAULT_PATH, exist_ok=True)
    file_path = os.path.join(VAULT_PATH, filename)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"✅ 已保存至 Obsidian: {file_path}")

@client.on(events.NewMessage(chats=TARGET_CHANNELS))
async def handler(event):
    message_text = event.message.message or ""
    
    # 1. 检查 Github 链接
    github_match = re.search(r'https://github\.com/([\w.-]+)/([\w.-]+)', message_text)
    if github_match:
        repo_url = github_match.group(0)
        repo_name = f"{github_match.group(1)}_{github_match.group(2)}"
        print(f"🔍 发现 Github 项目: {repo_url}")
        
        # TODO: 这里需要写一段代码调用 Github API 或 Jina 去抓取 README
        # readme_content = fetch_readme(repo_url)
        readme_content = "这里是占位的 README 内容..." 
        
        # 调用 Gemini 分析
        print("🧠 正在请求 Gemini 2.0 进行提炼分析...")
        analysis = analyze_github_repo(repo_url, readme_content)
        
        # 加上 Frontmatter 和 标签
        final_md = f"---\ntitle: {repo_name}\ntags: [TG_资讯池, Github]\n---\n\n" + analysis
        save_to_vault(f"{repo_name}.md", final_md)
        return

    # 2. 检查电子书附件 (.epub / .pdf)
    if event.message.document:
        doc = event.message.document
        filename = "unknown"
        for attr in doc.attributes:
            if hasattr(attr, 'file_name'):
                filename = attr.file_name
                
        if filename.endswith(('.epub', '.pdf', '.mobi')):
            print(f"📚 发现电子书资源: {filename}")
            
            # 调用 Gemini 分析书籍简介
            print("🧠 正在请求 Gemini 2.0 生成卡片...")
            analysis = analyze_ebook(filename, message_text)
            
            final_md = f"---\ntitle: {filename}\ntags: [TG_资讯池, EBook]\n---\n\n" + analysis
            save_to_vault(f"EBook_{filename}.md", final_md)
            return

async def main():
    if not TARGET_CHANNELS:
        print("⚠️ TARGET_CHANNELS 为空！请先运行 list_channels.py 找到您想监听的频道 ID 并填入本脚本。")
        return
        
    print("🚀 Gatekeeper TG Fetcher 启动！正在监听目标频道...")
    await client.start()
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())

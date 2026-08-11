import time
import feedparser
import re
import os
from database import is_processed, mark_processed
from processor import analyze_youtube_transcript, analyze_github_repo, analyze_article
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.formatters import TextFormatter

import os

import json

def load_feeds():
    feeds_path = os.path.join(os.path.dirname(__file__), "feeds.json")
    if not os.path.exists(feeds_path):
        print(f"⚠️ 找不到配置文件: {feeds_path}")
        return []
    with open(feeds_path, "r", encoding="utf-8") as f:
        return json.load(f)

RSS_FEEDS = load_feeds()

VAULT_PATH = os.getenv("VAULT_PATH", "/Users/woodman/dev/nas-gatekeeper/SecondBrain-Quartz/content/notes/Auto_Clippings")

def save_to_vault(filename: str, content: str):
    os.makedirs(VAULT_PATH, exist_ok=True)
    file_path = os.path.join(VAULT_PATH, filename)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"✅ 已保存至 Obsidian: {file_path}")

def get_youtube_transcript(video_id: str) -> str:
    """提取 YouTube 视频英/中文字幕并转为纯文本"""
    try:
        # 尝试获取中文或英文字幕
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        try:
            transcript = transcript_list.find_transcript(['zh-Hans', 'zh-Hant', 'zh-CN', 'zh', 'en']).fetch()
        except:
            # 如果没有指定语言，退而求其次获取生成的字幕并翻译为中文
            transcript = transcript_list.find_transcript(['en']).translate('zh-Hans').fetch()
            
        formatter = TextFormatter()
        return formatter.format_transcript(transcript)
    except Exception as e:
        print(f"⚠️ 无法获取字幕 {video_id}: {e}")
        return ""

def process_youtube_entry(feed_name: str, entry):
    video_id = entry.yt_videoid
    video_url = entry.link
    title = entry.title
    
    if is_processed(video_id):
        return
        
    print(f"🎬 发现新 YouTube 视频: {title}")
    
    # 提取字幕
    transcript = get_youtube_transcript(video_id)
    if not transcript:
        print("⏭️ 忽略无字幕视频。")
        mark_processed(video_id, "youtube")
        return
        
    print("🧠 正在使用 Gemini 2.0 提炼视频精华...")
    analysis = analyze_youtube_transcript(title, feed_name, video_url, transcript)
    
    # 过滤掉非法文件名字符
    safe_title = re.sub(r'[\\/*?:"<>|]', "", title)
    
    final_md = f"---\ntitle: {safe_title}\ntags: [YT_深度解读]\n---\n\n" + analysis
    save_to_vault(f"YT_{safe_title}.md", final_md)
    
    # 记录到数据库防重
    mark_processed(video_id, "youtube")

def process_substack_entry(feed_name: str, entry):
    article_id = entry.id if hasattr(entry, 'id') else entry.link
    article_url = entry.link
    title = entry.title
    
    if is_processed(article_id):
        return
        
    print(f"📰 发现新 Substack 文章: {title}")
    
    # 获取正文内容（不同 RSS 源的结构可能略有不同）
    content = ""
    if hasattr(entry, 'content'):
        content = entry.content[0].value
    elif hasattr(entry, 'description'):
        content = entry.description
    elif hasattr(entry, 'summary'):
        content = entry.summary
        
    if not content:
        print("⏭️ 忽略无正文的文章。")
        mark_processed(article_id, "substack")
        return
        
    import bs4
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(content, 'html.parser')
    text_content = soup.get_text(separator=' ', strip=True)
        
    print("🧠 正在使用大模型提炼文章精华...")
    analysis = analyze_article(title, feed_name, article_url, text_content)
    
    safe_title = re.sub(r'[\\/*?:"<>|]', "", title)
    
    final_md = f"---\ntitle: \"{safe_title}\"\ntags: [Substack_深度解读]\n---\n\n" + analysis
    save_to_vault(f"Substack_{safe_title}.md", final_md)
    
    mark_processed(article_id, "substack")

from processor import analyze_reddit_post

def process_reddit_entry(feed_name: str, entry):
    video_id = entry.id
    url = entry.link
    title = entry.title
    
    if is_processed(video_id):
        return
        
    print(f"🔥 发现新 Reddit 热门: {title}")
    
    # 解析 HTML 内容
    raw_html = entry.content[0].value if 'content' in entry else entry.summary
    import bs4
    soup = bs4.BeautifulSoup(raw_html, 'html.parser')
    text_content = soup.get_text(separator=' ', strip=True)
    
    print("🧠 正在使用大模型提炼 Reddit 帖子...")
    analysis = analyze_reddit_post(title, feed_name, url, text_content)
    
    safe_title = re.sub(r'[\\/*?:"<>|]', "", title)[:60]
    final_md = f"---\ntitle: \"{safe_title}\"\ntags: [Reddit_热榜, {feed_name.replace('/', '_')}]\n---\n\n" + analysis
    save_to_vault(f"Reddit_{safe_title}.md", final_md)
    mark_processed(video_id, "reddit")


def run_rss_fetcher():
    print("🚀 Gatekeeper RSS/YT Fetcher 启动！")
    
    for feed in RSS_FEEDS:
        if feed["url"] == "YOUR_YOUTUBE_RSS_URL_HERE":
            continue
            
        print(f"📡 正在拉取: {feed['name']}")
        parsed_feed = feedparser.parse(feed["url"])
        
        for entry in parsed_feed.entries:
            if feed["type"] == "youtube":
                process_youtube_entry(feed["name"], entry)
            elif feed["type"] == "substack":
                process_substack_entry(feed["name"], entry)
            elif feed["type"] == "reddit":
                process_reddit_entry(feed["name"], entry)
                break # Reddit只拉取当天的Top 1，绝不泛滥

if __name__ == "__main__":
    run_rss_fetcher()

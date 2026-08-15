import os
os.environ['HTTP_PROXY'] = 'http://192.168.2.3:7890'
os.environ['HTTPS_PROXY'] = 'http://192.168.2.3:7890'
import time
import feedparser
import re
from database import is_processed, mark_processed
from processor import analyze_youtube_transcript, analyze_github_repo, analyze_reddit_post
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.formatters import TextFormatter
import bs4

RSS_FEEDS = [
    {"name": "r/LocalLLaMA", "url": "https://www.reddit.com/r/LocalLLaMA/top/.rss?t=day", "type": "reddit"},
    {"name": "r/CursorAI", "url": "https://www.reddit.com/r/CursorAI/top/.rss?t=day", "type": "reddit"},
    {"name": "r/hardware", "url": "https://www.reddit.com/r/hardware/top/.rss?t=day", "type": "reddit"},
    {"name": "AI Explained", "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UCNJ1Ymd5yWuZZxgIE3t2E3g", "type": "youtube"}
]

VAULT_PATH = os.getenv("VAULT_PATH", "/Users/woodman/dev/nas-gatekeeper/SecondBrain-Quartz/content/notes/Auto_Clippings")

def save_to_vault(filename: str, content: str):
    os.makedirs(VAULT_PATH, exist_ok=True)
    file_path = os.path.join(VAULT_PATH, filename)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"✅ 已保存至 Obsidian: {file_path}")

def get_youtube_transcript(video_id: str) -> str:
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        try:
            transcript = transcript_list.find_transcript(['zh-Hans', 'zh-Hant', 'zh-CN', 'zh', 'en']).fetch()
        except:
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
    
    transcript = get_youtube_transcript(video_id)
    if not transcript:
        print("⏭️ 忽略无字幕视频。")
        mark_processed(video_id, "youtube")
        return
        
    print("🧠 正在使用 本地Qwen + 云端Gemini 提炼视频精华...")
    translated_text, analysis = analyze_youtube_transcript(title, feed_name, video_url, transcript)
    
    safe_title = re.sub(r'[\\/*?:"<>|]', "", title)
    
    # 保存原文翻译
    raw_md = f"---\ntitle: {safe_title}_全翻译\ntags: [YT_全文翻译]\n---\n\n{translated_text}"
    save_to_vault(f"Raw_翻译_{safe_title}.md", raw_md)
    
    # 保存总结简报
    final_md = f"---\ntitle: {safe_title}_简报\ntags: [YT_深度解读]\n---\n\n{analysis}"
    save_to_vault(f"Auto_简报_{safe_title}.md", final_md)
    
    mark_processed(video_id, "youtube")

def process_reddit_entry(feed_name: str, entry):
    video_id = entry.id
    url = entry.link
    title = entry.title
    
    if is_processed(video_id):
        return
        
    print(f"🔥 发现新 Reddit 热门: {title}")
    
    raw_html = entry.content[0].value if 'content' in entry else entry.summary
    soup = bs4.BeautifulSoup(raw_html, 'html.parser')
    text_content = soup.get_text(separator=' ', strip=True)
    
    print("🧠 正在使用 本地Qwen + 云端Gemini 提炼 Reddit 帖子...")
    translated_text, analysis = analyze_reddit_post(title, feed_name, url, text_content)
    
    safe_title = re.sub(r'[\\/*?:"<>|]', "", title)[:60]
    
    # 保存原文翻译
    raw_md = f"---\ntitle: {safe_title}_全翻译\ntags: [Reddit_全文翻译, {feed_name.replace('/', '_')}]\n---\n\n{translated_text}"
    save_to_vault(f"Raw_翻译_{safe_title}.md", raw_md)
    
    # 保存总结简报
    final_md = f"---\ntitle: {safe_title}_简报\ntags: [Reddit_热榜, {feed_name.replace('/', '_')}]\n---\n\n{analysis}"
    save_to_vault(f"Auto_简报_{safe_title}.md", final_md)
    
    mark_processed(video_id, "reddit")

def run_rss_fetcher():
    print("🚀 Gatekeeper 混合架构 (Qwen+Gemini) RSS/YT Fetcher 启动！")
    
    for feed in RSS_FEEDS:
        if feed["url"] == "YOUR_YOUTUBE_RSS_URL_HERE":
            continue
            
        print(f"📡 正在拉取: {feed['name']}")
        parsed_feed = feedparser.parse(feed["url"])
        
        for entry in parsed_feed.entries:
            if feed["type"] == "youtube":
                process_youtube_entry(feed["name"], entry)
                break 
            elif feed["type"] == "reddit":
                process_reddit_entry(feed["name"], entry)
                break 

if __name__ == "__main__":
    run_rss_fetcher()

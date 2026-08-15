import os
os.environ['HTTP_PROXY'] = 'http://192.168.2.3:7890'
os.environ['HTTPS_PROXY'] = 'http://192.168.2.3:7890'
os.environ['NO_PROXY'] = 'localhost,127.0.0.1'
import time
import feedparser
import re
import urllib.request
import bs4
from database import is_processed, mark_processed
from processor import analyze_youtube_transcript, analyze_github_repo, analyze_reddit_post
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.formatters import TextFormatter

# 扩充信息源
RSS_FEEDS = [
    # 原有 AI 与硬件
    {"name": "r/LocalLLaMA", "url": "https://www.reddit.com/r/LocalLLaMA/top/.rss?t=day", "type": "reddit"},
    {"name": "r/CursorAI", "url": "https://www.reddit.com/r/CursorAI/top/.rss?t=day", "type": "reddit"},
    {"name": "r/hardware", "url": "https://www.reddit.com/r/hardware/top/.rss?t=day", "type": "reddit"},
    # 新增编程语言与 AI 学术
    {"name": "r/Python", "url": "https://www.reddit.com/r/Python/top/.rss?t=day", "type": "reddit"},
    {"name": "r/rust", "url": "https://www.reddit.com/r/rust/top/.rss?t=day", "type": "reddit"},
    {"name": "r/MachineLearning", "url": "https://www.reddit.com/r/MachineLearning/top/.rss?t=day", "type": "reddit"},
    # YouTube 顶级编程与 AI 频道
    {"name": "AI Explained", "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UCNJ1Ymd5yWuZZxgIE3t2E3g", "type": "youtube"},
    {"name": "Fireship", "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UCsBjURrPoezykLs9EqgamOA", "type": "youtube"},
    {"name": "Two Minute Papers", "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UCbfYPyITQ-7l4upoX8nvctg", "type": "youtube"}
]

VAULT_PATH = os.getenv("VAULT_PATH", "/opt/SecondBrain-Quartz/content/notes/Auto_Clippings")

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
        
    print(f"🧠 正在使用 本地Qwen + 云端Gemini 提炼 {feed_name} 视频精华...")
    translated_text, analysis = analyze_youtube_transcript(title, feed_name, video_url, transcript)
    
    safe_title = re.sub(r'[\\/*?:"<>|]', "", title)
    
    raw_md = f"---\ntitle: {safe_title}_全翻译\ntags: [YT_全文翻译]\n---\n\n{translated_text}"
    save_to_vault(f"Raw_翻译_{safe_title}.md", raw_md)
    
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
    
    print(f"🧠 正在使用 本地Qwen + 云端Gemini 提炼 {feed_name} 帖子...")
    translated_text, analysis = analyze_reddit_post(title, feed_name, url, text_content)
    
    safe_title = re.sub(r'[\\/*?:"<>|]', "", title)[:60]
    
    raw_md = f"---\ntitle: {safe_title}_全翻译\ntags: [Reddit_全文翻译, {feed_name.replace('/', '_')}]\n---\n\n{translated_text}"
    save_to_vault(f"Raw_翻译_{safe_title}.md", raw_md)
    
    final_md = f"---\ntitle: {safe_title}_简报\ntags: [Reddit_热榜, {feed_name.replace('/', '_')}]\n---\n\n{analysis}"
    save_to_vault(f"Auto_简报_{safe_title}.md", final_md)
    
    mark_processed(video_id, "reddit")

def process_github_trending():
    print("💻 开始扫描 Github 每日趋势热榜...")
    trending_url = "https://github.com/trending"
    try:
        req = urllib.request.Request(trending_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=30) as response:
            html = response.read().decode('utf-8')
        soup = bs4.BeautifulSoup(html, 'html.parser')
        
        # 提取排名第一的仓库
        repo_element = soup.select_one('article.Box-row h2.h3 a')
        if not repo_element:
            print("⏭️ 未在页面找到仓库链接。")
            return
            
        repo_path = repo_element.get('href').strip() # e.g. /username/repo
        repo_id = f"github_trending{repo_path}"
        
        if is_processed(repo_id):
            return
            
        repo_full_url = f"https://github.com{repo_path}"
        print(f"🔥 发现新的 Github 榜首项目: {repo_path}")
        
        # 尝试拉取 README.md
        readme_url = f"https://raw.githubusercontent.com{repo_path}/master/README.md"
        readme_url_main = f"https://raw.githubusercontent.com{repo_path}/main/README.md"
        
        readme_content = ""
        try:
            readme_req = urllib.request.Request(readme_url, headers={'User-Agent': 'Mozilla/5.0'})
            readme_content = urllib.request.urlopen(readme_req, timeout=10).read().decode('utf-8')
        except:
            try:
                readme_req_main = urllib.request.Request(readme_url_main, headers={'User-Agent': 'Mozilla/5.0'})
                readme_content = urllib.request.urlopen(readme_req_main, timeout=10).read().decode('utf-8')
            except Exception as e:
                print(f"⚠️ 无法获取该仓库的 README: {e}")
                readme_content = "README content unavailable."
        
        print("🧠 正在使用 本地Qwen + 云端Gemini 提炼 Github README...")
        translated_text, analysis = analyze_github_repo(repo_full_url, readme_content)
        
        safe_title = repo_path.replace("/", "_")
        
        raw_md = f"---\ntitle: {safe_title}_全翻译\ntags: [Github_Trending, 全文翻译]\n---\n\n{translated_text}"
        save_to_vault(f"Raw_翻译_Github_{safe_title}.md", raw_md)
        
        final_md = f"---\ntitle: {safe_title}_简报\ntags: [Github_Trending, 深度解读]\n---\n\n{analysis}"
        save_to_vault(f"Auto_简报_Github_{safe_title}.md", final_md)
        
        mark_processed(repo_id, "github")
    except Exception as e:
        print(f"⚠️ Github 榜单获取失败: {e}")

def run_rss_fetcher():
    print("🚀 Gatekeeper 混合架构 (Qwen+Gemini) RSS/YT Fetcher 启动！")
    
    # 1. 抓取 RSS 源
    for feed in RSS_FEEDS:
        if feed["url"] == "YOUR_YOUTUBE_RSS_URL_HERE":
            continue
            
        print(f"📡 正在拉取: {feed['name']}")
        try:
            parsed_feed = feedparser.parse(feed["url"])
            for entry in parsed_feed.entries:
                if feed["type"] == "youtube":
                    process_youtube_entry(feed["name"], entry)
                    break 
                elif feed["type"] == "reddit":
                    process_reddit_entry(feed["name"], entry)
                    break 
        except Exception as e:
            print(f"⚠️ 拉取 {feed['name']} 失败: {e}")
            
    # 2. 抓取 Github 趋势
    process_github_trending()

if __name__ == "__main__":
    run_rss_fetcher()

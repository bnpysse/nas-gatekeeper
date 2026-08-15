import os
from datetime import datetime
os.environ['HTTP_PROXY'] = 'http://192.168.2.3:7890'
os.environ['HTTPS_PROXY'] = 'http://192.168.2.3:7890'
os.environ['NO_PROXY'] = 'localhost,127.0.0.1'
import sys
from pathlib import Path
project_root = str(Path(__file__).resolve().parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)
import time
import feedparser
import re
import urllib.request
import bs4
from database import is_processed, mark_processed, init_db
from processor import analyze_youtube_transcript, analyze_github_repo, analyze_reddit_post, analyze_blog_post
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.formatters import TextFormatter

# 扩充信息源 (今日第一 + 实时前五 + 财经 + 大咖)
RSS_FEEDS = [
    # AI 与硬件 (今日第一 + 实时前五)
    {"name": "r/LocalLLaMA", "urls": ["https://www.reddit.com/r/LocalLLaMA/top/.rss?t=day", "https://www.reddit.com/r/LocalLLaMA/.rss"], "type": "reddit"},
    {"name": "r/CursorAI", "urls": ["https://www.reddit.com/r/CursorAI/top/.rss?t=day", "https://www.reddit.com/r/CursorAI/.rss"], "type": "reddit"},
    {"name": "r/hardware", "urls": ["https://www.reddit.com/r/hardware/top/.rss?t=day", "https://www.reddit.com/r/hardware/.rss"], "type": "reddit"},
    
    # 编程语言与 AI 学术
    {"name": "r/Python", "urls": ["https://www.reddit.com/r/Python/top/.rss?t=day", "https://www.reddit.com/r/Python/.rss"], "type": "reddit"},
    {"name": "r/rust", "urls": ["https://www.reddit.com/r/rust/top/.rss?t=day", "https://www.reddit.com/r/rust/.rss"], "type": "reddit"},
    {"name": "r/MachineLearning", "urls": ["https://www.reddit.com/r/MachineLearning/top/.rss?t=day", "https://www.reddit.com/r/MachineLearning/.rss"], "type": "reddit"},
    
    # 财经与市场
    {"name": "r/SecurityAnalysis", "urls": ["https://www.reddit.com/r/SecurityAnalysis/top/.rss?t=day", "https://www.reddit.com/r/SecurityAnalysis/.rss"], "type": "reddit"},
    {"name": "r/Economics", "urls": ["https://www.reddit.com/r/Economics/top/.rss?t=day", "https://www.reddit.com/r/Economics/.rss"], "type": "reddit"},
    {"name": "r/investing", "urls": ["https://www.reddit.com/r/investing/top/.rss?t=day", "https://www.reddit.com/r/investing/.rss"], "type": "reddit"},
    {"name": "r/wallstreetbets", "urls": ["https://www.reddit.com/r/wallstreetbets/top/.rss?t=day"], "type": "reddit"},
    
    # 科技与财经大咖 (Substack/Blog)
    {"name": "SemiAnalysis", "urls": ["https://www.semianalysis.com/feed"], "type": "substack"},
    {"name": "Morgan Stanley Insights", "urls": ["https://www.morganstanley.com/ideas.rss"], "type": "substack"},
    {"name": "Noahpinion (Economics)", "urls": ["https://www.noahpinion.blog/feed"], "type": "substack"},
    {"name": "The Pragmatic Engineer", "urls": ["https://blog.pragmaticengineer.com/rss/"], "type": "substack"},
    {"name": "Lenny's Newsletter", "urls": ["https://www.lennysnewsletter.com/feed"], "type": "substack"},
    {"name": "Stratechery", "urls": ["https://stratechery.com/feed/"], "type": "substack"},
    
    # YouTube 顶级编程与 AI 频道
    {"name": "Fundstrat (Tom Lee)", "urls": ["https://www.youtube.com/feeds/videos.xml?channel_id=UCcBzKSM4A-pIHMJWSnxmi_g"], "type": "youtube"},
    {"name": "AI Explained", "urls": ["https://www.youtube.com/feeds/videos.xml?channel_id=UCNJ1Ymd5yWuZZxgIE3t2E3g"], "type": "youtube"},
    {"name": "Fireship", "urls": ["https://www.youtube.com/feeds/videos.xml?channel_id=UCsBjURrPoezykLs9EqgamOA"], "type": "youtube"},
    {"name": "Two Minute Papers", "urls": ["https://www.youtube.com/feeds/videos.xml?channel_id=UCbfYPyITQ-7l4upoX8nvctg"], "type": "youtube"}
]

LOW_VALUE_PATTERNS = [
    r'^\s*(\+1|赞|点赞|顶|mark|收藏|mark一下|蹲|留名|支持|好帖|分|好|不错|nb|666|牛逼)\s*$',
    r'^\s*(upvoted|this|agree|same|lol|lmao|nice|thanks|thank you|bump|following|me too|first|second)\s*$',
    r'^\s*submitted by\s+/u/\S+\s+to\s+r/\S+\s*$',
]

def clean_reddit_content(raw_text: str) -> str:
    """清理 Reddit 特有的样板文本"""
    text = re.sub(r'submitted by\s+/u/\S+\s+\[link\]\s+\[comments\]', '', raw_text, flags=re.IGNORECASE)
    text = re.sub(r'\[link\]\s+\[comments\]', '', text, flags=re.IGNORECASE)
    return text.strip()

def is_substantive_content(title: str, text: str, min_chars: int = 100) -> bool:
    """判断抓取的内容是否具备实质性的知识/分析价值，坚决过滤纯点赞、纯跟帖、空内容"""
    if not text or not text.strip():
        return False
    
    clean_text = clean_reddit_content(text)
    
    # 过滤纯点赞/单字无营养回复
    for pat in LOW_VALUE_PATTERNS:
        if re.match(pat, clean_text, re.IGNORECASE) or re.match(pat, title, re.IGNORECASE):
            return False
            
    # 如果正文只有极短的几句话（< min_chars），判定为无实质营养内容
    if len(clean_text) < min_chars:
        return False
        
    return True

def save_to_vault(filename: str, content: str):
    # 严格内容有效性校验，杜绝保存空内容或纯 Frontmatter 文件
    body_lines = [
        l.strip() for l in content.splitlines() 
        if l.strip() and not l.startswith("---") and not l.startswith("title:") and not l.startswith("tags:") and not l.startswith("date:") and not l.startswith("rag_processed:")
    ]
    if len("\n".join(body_lines).strip()) < 50:
        print(f"⚠️ 拦截空内容文件落库: {filename}")
        return

    os.makedirs(VAULT_PATH, exist_ok=True)
    file_path = os.path.join(VAULT_PATH, filename)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"✅ 已保存至 Obsidian: {file_path}")
    
    # 获取文件夹名称 (Auto_Clippings 或 Auto_Summary)
    folder_name = os.path.basename(os.path.dirname(file_path)) if "Auto_" in file_path else "Auto_Clippings"
    
    try:
        import subprocess
        print("☁️ 同步至 Google Drive (根目录)...")
        subprocess.run(["rclone", "copy", file_path, f"gdrive:{folder_name}/"], check=False)
        print("☁️ 同步至 OneDrive...")
        subprocess.run(["rclone", "copy", file_path, f"onedrive:应用/remotely-save/notes/{folder_name}/"], check=False)
    except Exception as e:
        print(f"⚠️ 云盘同步异常: {e}")

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
    if not transcript or len(transcript.strip()) < 100:
        print(f"⏭️ 忽略无字幕或过短视频: 《{title}》")
        mark_processed(video_id, "youtube")
        return
        
    print(f"🧠 正在使用 本地Qwen + 云端Gemini 提炼 {feed_name} 视频精华...")
    translated_text, analysis = analyze_youtube_transcript(title, feed_name, video_url, transcript)
    
    safe_title = re.sub(r'[\\/*?:"<>|?#%&+=？!！()]', "", title).strip(' .')[:60].strip(' .')
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    raw_md = f"---\ntitle: \"{safe_title}_全翻译\"\ndate: {date_str}\ntags: [YT_全文翻译]\n---\n\n{translated_text}"
    save_to_vault(f"Raw_翻译_{safe_title}.md", raw_md)
    
    final_md = f"---\ntitle: \"{safe_title}_简报\"\ndate: {date_str}\ntags: [YT_深度解读]\n---\n\n{analysis}"
    save_to_vault(f"Auto_简报_{safe_title}.md", final_md)
    
    mark_processed(video_id, "youtube")

def process_reddit_entry(feed_name: str, entry):
    video_id = entry.id
    url = entry.link
    title = entry.title
    
    if is_processed(video_id):
        return
        
    raw_html = entry.content[0].value if 'content' in entry else entry.summary
    soup = bs4.BeautifulSoup(raw_html, 'html.parser')
    text_content = soup.get_text(separator='\n\n', strip=True)
    clean_text = clean_reddit_content(text_content)
    
    # 严格实质性质量过滤：过滤纯点赞、无实质内容或字符不足120字的主题
    if not is_substantive_content(title, clean_text, min_chars=120):
        print(f"⏭️ 过滤低营养/无实质内容 Reddit 帖子: 《{title}》 (有效字符: {len(clean_text)})")
        mark_processed(video_id, "reddit")
        return

    print(f"🔥 发现新 Reddit 高价值热门: {title}")
    print(f"🧠 正在使用 本地Qwen + 云端Gemini 提炼 {feed_name} 帖子...")
    translated_text, analysis = analyze_reddit_post(title, feed_name, url, f"【帖子标题】：{title}\n\n【帖子正文】：\n{clean_text}")
    
    safe_title = re.sub(r'[\\/*?:"<>|?#%&+=？!！()]', "", title).strip(' .')[:60].strip(' .')
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    raw_md = f"---\ntitle: \"{safe_title}_全翻译\"\ndate: {date_str}\ntags: [Reddit_全文翻译, {feed_name.replace('/', '_')}]\n---\n\n{translated_text}"
    save_to_vault(f"Raw_翻译_{safe_title}.md", raw_md)
    
    final_md = f"---\ntitle: \"{safe_title}_简报\"\ndate: {date_str}\ntags: [Reddit_热榜, {feed_name.replace('/', '_')}]\n---\n\n{analysis}"
    save_to_vault(f"Auto_简报_{safe_title}.md", final_md)
    
    mark_processed(video_id, "reddit")

def process_substack_entry(feed_name: str, entry):
    video_id = entry.id if 'id' in entry else entry.link
    url = entry.link
    title = entry.title
    
    if is_processed(video_id):
        return
        
    raw_html = entry.content[0].value if 'content' in entry else entry.summary
    soup = bs4.BeautifulSoup(raw_html, 'html.parser')
    text_content = soup.get_text(separator='\n\n', strip=True)
    
    # 过滤空内容或过短文章
    if not is_substantive_content(title, text_content, min_chars=150):
        print(f"⏭️ 过滤正文过短或空文章: 《{title}》 (有效字符: {len(text_content)})")
        mark_processed(video_id, "substack")
        return

    print(f"🔥 发现新博客/Newsletter: {title}")
    print(f"🧠 正在使用 本地Qwen + 云端Gemini 提炼 {feed_name} 文章...")
    translated_text, analysis = analyze_blog_post(title, feed_name, url, f"【文章标题】：{title}\n\n【文章正文】：\n{text_content}")
    
    safe_title = re.sub(r'[\\/*?:"<>|?#%&+=？!！()]', "", title).strip(' .')[:60].strip(' .')
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    raw_md = f"---\ntitle: \"{safe_title}_全翻译\"\ndate: {date_str}\ntags: [大咖视点_全文翻译, {feed_name.replace(' ', '_')}]\n---\n\n{translated_text}"
    save_to_vault(f"Raw_翻译_{safe_title}.md", raw_md)
    
    final_md = f"---\ntitle: \"{safe_title}_简报\"\ndate: {date_str}\ntags: [大咖视点_深度解读, {feed_name.replace(' ', '_')}]\n---\n\n{analysis}"
    save_to_vault(f"Auto_简报_{safe_title}.md", final_md)
    
    mark_processed(video_id, "substack")

def process_github_trending():
    print("💻 开始扫描 Github 每日趋势热榜 (Top 5)...")
    trending_url = "https://github.com/trending"
    try:
        req = urllib.request.Request(trending_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=30) as response:
            html = response.read().decode('utf-8')
        soup = bs4.BeautifulSoup(html, 'html.parser')
        
        # 提取排名前五的仓库
        repo_elements = soup.select('article.Box-row h2.h3 a')[:5]
        if not repo_elements:
            print("⏭️ 未在页面找到仓库链接。")
            return
            
        for repo_element in repo_elements:
            repo_path = repo_element.get('href').strip() # e.g. /username/repo
            repo_id = f"github_trending{repo_path}"
            
            if is_processed(repo_id):
                continue
                
            repo_full_url = f"https://github.com{repo_path}"
            print(f"🔥 发现新的 Github 榜单项目: {repo_path}")
            
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
            
            date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            raw_md = f"---\ntitle: \"{safe_title}_全翻译\"\ndate: {date_str}\ntags: [Github_Trending, 全文翻译]\n---\n\n{translated_text}"
            save_to_vault(f"Raw_翻译_Github_{safe_title}.md", raw_md)
            
            final_md = f"---\ntitle: \"{safe_title}_简报\"\ndate: {date_str}\ntags: [Github_Trending, 深度解读]\n---\n\n{analysis}"
            save_to_vault(f"Auto_简报_Github_{safe_title}.md", final_md)
            
            mark_processed(repo_id, "github")
    except Exception as e:
        print(f"⚠️ Github 榜单获取失败: {e}")

def run_rss_fetcher():
    print("🚀 Gatekeeper 混合架构 (Qwen+Gemini) RSS/YT Fetcher 启动！")
    try:
        init_db()
    except Exception as e:
        print(f"⚠️ 数据库初始化警告 (离线或网络受限): {e}")
    
    # 1. 抓取 RSS 源
    for feed in RSS_FEEDS:
        for url in feed["urls"]:
            print(f"📡 正在拉取: {feed['name']} ({url})")
            try:
                parsed_feed = feedparser.parse(url)
                count = 0
                limit = 1 if "top/.rss" in url else (5 if feed["type"] in ["reddit", "substack"] else 3)
                
                for entry in parsed_feed.entries:
                    if feed["type"] == "youtube":
                        process_youtube_entry(feed["name"], entry)
                        count += 1
                    elif feed["type"] == "reddit":
                        process_reddit_entry(feed["name"], entry)
                        count += 1
                    elif feed["type"] == "substack":
                        process_substack_entry(feed["name"], entry)
                        count += 1
                        
                    if count >= limit:
                        break 
            except Exception as e:
                print(f"⚠️ 拉取 {feed['name']} 失败: {e}")
            
    # 2. 抓取 Github 趋势 (获取前 5 名)
    process_github_trending()

if __name__ == "__main__":
    run_rss_fetcher()

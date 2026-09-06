import os
import sys
import json
import time
import re
import urllib.request
from datetime import datetime
from pathlib import Path

# 配置代理与运行环境
os.environ['HTTP_PROXY'] = 'http://192.168.2.3:7890'
os.environ['HTTPS_PROXY'] = 'http://192.168.2.3:7890'
os.environ['http_proxy'] = 'http://192.168.2.3:7890'
os.environ['https_proxy'] = 'http://192.168.2.3:7890'
os.environ['ALL_PROXY'] = 'http://192.168.2.3:7890'
os.environ['all_proxy'] = 'http://192.168.2.3:7890'
os.environ['NO_PROXY'] = 'localhost,127.0.0.1,dashscope.aliyuncs.com,ark.cn-beijing.volces.com'
os.environ['no_proxy'] = 'localhost,127.0.0.1,dashscope.aliyuncs.com,ark.cn-beijing.volces.com'

project_root = str(Path(__file__).resolve().parent.parent.parent)
tg_bot_dir = str(Path(__file__).resolve().parent.parent / "tg-bot")
if project_root not in sys.path:
    sys.path.insert(0, project_root)
if tg_bot_dir not in sys.path:
    sys.path.insert(0, tg_bot_dir)

import requests
import feedparser
import bs4
try:
    import trafilatura
except ImportError:
    trafilatura = None

from database import is_processed, mark_processed, init_db
from processor import analyze_youtube_transcript, analyze_github_repo, analyze_reddit_post, analyze_blog_post
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.formatters import TextFormatter

# 知识库落地路径：优先落库到 Obsidian 的 Auto_Clippings
VAULT_PATH = os.getenv("VAULT_PATH", "/opt/obsidian-brain-data/Auto_Clippings" if os.path.exists("/opt/obsidian-brain-data") else str(Path.home() / "dev/nas-gatekeeper/SecondBrain-Quartz/content/notes/Auto_Clippings"))

PROXIES = {
    "http": "http://192.168.2.3:7890",
    "https": "http://192.168.2.3:7890"
}
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
}

def load_feeds():
    """从 feeds.json 动态载入订阅源"""
    feeds_file = Path(__file__).parent / "feeds.json"
    if feeds_file.exists():
        try:
            with open(feeds_file, "r", encoding="utf-8") as f:
                items = json.load(f)
                result = []
                for it in items:
                    u = it.get("url")
                    urls = [u] if isinstance(u, str) else it.get("urls", [])
                    result.append({
                        "name": it["name"],
                        "urls": urls,
                        "type": it.get("type", "substack"),
                        "needs_proxy": it.get("needs_proxy", False)
                    })
                print(f"📋 成功从 feeds.json 载入 {len(result)} 个订阅源")
                return result
        except Exception as e:
            print(f"⚠️ 加载 feeds.json 异常: {e}")
    return []

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

def fetch_full_article_content(url: str, min_chars: int = 300) -> str:
    """访问目标原文网页，深度抓取并提取清洗后的正文主体"""
    if not url or not url.startswith("http"):
        return ""
        
    try:
        # 优先走代理抓取
        resp = requests.get(url, headers=DEFAULT_HEADERS, proxies=PROXIES, timeout=15)
        if resp.status_code != 200:
            # 降级直连重试
            resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=10)
            
        if resp.status_code == 200 and resp.text:
            # 1. 优先使用 trafilatura 专业文章提取引擎
            if trafilatura:
                extracted = trafilatura.extract(resp.text, include_comments=False, include_tables=True)
                if extracted and len(extracted.strip()) >= min_chars:
                    return extracted.strip()
            
            # 2. 降级使用 BeautifulSoup 解析
            soup = bs4.BeautifulSoup(resp.text, 'html.parser')
            # 移除常见噪音标签
            for tag in soup(['script', 'style', 'nav', 'header', 'footer', 'aside', 'noscript']):
                tag.decompose()
            article_elem = soup.find('article') or soup.find('main') or soup.find('div', class_=re.compile(r'(content|post|article|entry)', re.I))
            if article_elem:
                text = article_elem.get_text(separator='\n\n', strip=True)
            else:
                text = soup.get_text(separator='\n\n', strip=True)
                
            if len(text.strip()) >= min_chars:
                return text.strip()
    except Exception as e:
        print(f"⚠️ 抓取原文网页异常 ({url}): {e}")
        
    return ""

def is_substantive_content(title: str, text: str, min_chars: int = 200) -> bool:
    """判断抓取的内容是否具备实质性的知识/分析价值，坚决过滤纯点赞、纯跟帖、空内容与仅含链接的元数据"""
    if not text or not text.strip():
        return False
    
    clean_text = clean_reddit_content(text)
    
    # 过滤纯点赞/单字无营养回复
    for pat in LOW_VALUE_PATTERNS:
        if re.match(pat, clean_text, re.IGNORECASE) or re.match(pat, title, re.IGNORECASE):
            return False
            
    # 如果正文只有 Hacker News 的元数据链接行，判定为无实质正文
    if "Article URL:" in clean_text and "Comments URL:" in clean_text and len(clean_text) < 400:
        return False
        
    # 如果有效正文字符不足 min_chars，判定为无实质营养内容
    if len(clean_text) < min_chars:
        return False
        
    return True

def enhance_with_rag_and_dual_links(title: str, content: str, filename: str) -> tuple:
    """生成 Embedding 向量，并根据 Turso 相似度自动生成双向链接"""
    try:
        from services.rag import get_embedding, search_similar_notes, init_db
        import asyncio
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        async def _do_rag():
            await init_db()
            embedding = await get_embedding(content)
            similar_notes = []
            if embedding:
                similar_notes = await search_similar_notes(embedding, limit=3)
            return embedding, similar_notes
            
        embedding, similar_notes = loop.run_until_complete(_do_rag())
        loop.close()
        
        if similar_notes:
            valid_similars = [n for n in similar_notes if n.get("id") != filename and n.get("title") != title and n.get("doc_id") != filename]
            if valid_similars:
                content += "\n\n## 🔗 知识库双向关联\n"
                for n in valid_similars:
                    doc_id = n.get("doc_id") or n.get("id") or ""
                    clean_target_title = re.sub(r'\[.*?\]', '', n.get("title", "")).strip(' _-')
                    target_stem = Path(doc_id).stem if doc_id else ""
                    if target_stem:
                        content += f"- [[{target_stem}|{clean_target_title}]]\n"
                    else:
                        content += f"- [[{clean_target_title}]]\n"
                    
        return content, embedding
    except Exception as e:
        return content, []

def save_to_vault(filename: str, content: str, title: str = ""):
    """保存笔记至 Obsidian Auto_Clippings 并实时同步到云端与 Turso RAG 数据库"""
    body_lines = [
        l.strip() for l in content.splitlines() 
        if l.strip() and not l.startswith("---") and not l.startswith("title:") and not l.startswith("tags:") and not l.startswith("date:") and not l.startswith("rag_processed:")
    ]
    if len("\n".join(body_lines).strip()) < 100:
        print(f"⚠️ 拦截空内容/无效元数据文件落库: {filename}")
        return

    # 1. 向量化与双向链接生成
    enhanced_content, embedding = enhance_with_rag_and_dual_links(title or filename, content, filename)

    os.makedirs(VAULT_PATH, exist_ok=True)
    file_path = os.path.join(VAULT_PATH, filename)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(enhanced_content)
    print(f"✅ 已保存至 Obsidian: {file_path}")
    
    # 2. Turso 向量库入库
    if embedding:
        try:
            from services.rag import upsert_note
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(upsert_note(filename, title or filename, str(file_path), enhanced_content, embedding))
            loop.close()
        except Exception as e:
            pass

def get_youtube_transcript(video_id: str) -> str:
    """优先使用 YouTube 官方字幕接口获取中/英文字幕"""
    try:
        # YouTubeTranscriptApi 必须通过代理访问
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id, proxies=PROXIES)
        formatter = TextFormatter()
        try:
            transcript = transcript_list.find_transcript(['zh-Hans', 'zh-Hant', 'zh-CN', 'zh', 'en', 'en-US', 'en-GB']).fetch()
            return formatter.format_transcript(transcript)
        except Exception:
            pass
        
        # 降级：尝试翻译为中文，或者抓取首个可用字幕
        for t in transcript_list:
            if t.is_translatable:
                try:
                    translated = t.translate('zh-Hans').fetch()
                    return formatter.format_transcript(translated)
                except Exception:
                    pass
            try:
                fetched = t.fetch()
                return formatter.format_transcript(fetched)
            except Exception:
                pass
    except Exception as e:
        print(f"⚠️ 无法直接获取官方字幕 {video_id}: {e}")
    return ""

def get_youtube_transcript_via_audio(video_url: str) -> str:
    """降级备选方案：当 YouTube 无字幕时，调用 yt-dlp 提取音轨并使用阿里云 SenseVoice-V1 进行语音转文字"""
    print(f"🎙️ 正在调用 yt-dlp + SenseVoice-V1 提取并转录音频: {video_url}")
    try:
        from services.downloader import download_audio_from_url
        from services.ai import transcribe_audio_sensevoice
        
        audio_path, _ = download_audio_from_url(video_url)
        if audio_path and audio_path.exists():
            text = transcribe_audio_sensevoice(audio_path)
            try:
                audio_path.unlink()
            except Exception:
                pass
            return text
    except Exception as e:
        print(f"⚠️ 音频转录降级失败: {e}")
    return ""

def process_youtube_entry(feed_name: str, entry):
    """处理 YouTube 视频 RSS 条目"""
    video_id = getattr(entry, "yt_videoid", None)
    if not video_id:
        if "v=" in entry.link:
            video_id = entry.link.split("v=")[1].split("&")[0]
        elif "youtu.be/" in entry.link:
            video_id = entry.link.split("youtu.be/")[1].split("?")[0]
        else:
            video_id = entry.id
            
    video_url = entry.link
    title = entry.title
    
    if is_processed(video_id):
        return
        
    print(f"\n🎬 [YouTube] 发现新视频: 《{title}》 ({feed_name})")
    
    # 1. 尝试获取字幕
    transcript = get_youtube_transcript(video_id)
    
    # 2. 如果无字幕，自动降级为 SenseVoice-V1 音频识别转录
    if not transcript or len(transcript.strip()) < 100:
        transcript = get_youtube_transcript_via_audio(video_url)
        
    if not transcript or len(transcript.strip()) < 100:
        print(f"⏭️ 忽略无有效音频/字幕视频: 《{title}》")
        mark_processed(video_id, "youtube")
        return
        
    print(f"🧠 正在使用火山方舟 DeepSeek 提炼《{title}》视频精华与逐字稿...")
    translated_text, analysis = analyze_youtube_transcript(title, feed_name, video_url, transcript)
    
    safe_title = re.sub(r'[\\/*?:"<>|?#%&+=？!！()]', "", title).strip(' .')[:60].strip(' .')
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # 1. 保存原文/逐字稿
    raw_md = f"---\ntitle: \"{safe_title}_逐字稿\"\ndate: {date_str}\nurl: \"{video_url}\"\nsource: \"{feed_name}\"\ntags: [YT_逐字稿, 财经解读, {feed_name.replace(' ', '_')}]\n---\n\n{translated_text}"
    save_to_vault(f"Raw_逐字稿_{safe_title}.md", raw_md, title=f"{safe_title}_逐字稿")
    
    # 2. 保存深度分析简报
    final_md = f"---\ntitle: \"{safe_title}_深度简报\"\ndate: {date_str}\nurl: \"{video_url}\"\nsource: \"{feed_name}\"\ntags: [YT_财经解读, 智能简报, {feed_name.replace(' ', '_')}]\n---\n\n{analysis}"
    save_to_vault(f"Auto_简报_{safe_title}.md", final_md, title=f"{safe_title}_深度简报")
    
    mark_processed(video_id, "youtube")

def process_reddit_entry(feed_name: str, entry):
    """处理 Reddit 社区热帖"""
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

    print(f"\n🔥 [Reddit] 发现高价值热门: 《{title}》 ({feed_name})")
    print(f"🧠 正在深度提炼 {feed_name} 帖子...")
    translated_text, analysis = analyze_reddit_post(title, feed_name, url, f"【帖子标题】：{title}\n\n【帖子正文】：\n{clean_text}")
    
    safe_title = re.sub(r'[\\/*?:"<>|?#%&+=？!！()]', "", title).strip(' .')[:60].strip(' .')
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    raw_md = f"---\ntitle: \"{safe_title}_全翻译\"\ndate: {date_str}\nurl: \"{url}\"\nsource: \"{feed_name}\"\ntags: [Reddit_全文翻译, {feed_name.replace('/', '_')}]\n---\n\n{translated_text}"
    save_to_vault(f"Raw_翻译_{safe_title}.md", raw_md, title=f"{safe_title}_全翻译")
    
    final_md = f"---\ntitle: \"{safe_title}_简报\"\ndate: {date_str}\nurl: \"{url}\"\nsource: \"{feed_name}\"\ntags: [Reddit_热榜, {feed_name.replace('/', '_')}]\n---\n\n{analysis}"
    save_to_vault(f"Auto_简报_{safe_title}.md", final_md, title=f"{safe_title}_简报")
    
    mark_processed(video_id, "reddit")

def extract_target_url_from_entry(entry) -> str:
    """从 RSS 条目中智能提取真实目标文章的 URL"""
    url = getattr(entry, "link", "")
    # 如果是 hnrss 等链接聚合源，从 description 或 content 寻找目标 Article URL
    raw_html = entry.content[0].value if 'content' in entry else getattr(entry, 'summary', '')
    if raw_html:
        m = re.search(r'Article URL:\s*<a href="([^"]+)"', raw_html, re.I)
        if m:
            return m.group(1).strip()
    return url

def process_article_entry(feed_name: str, entry, is_link_aggregator: bool = False):
    """处理专栏文章或聚合链接条目（严格保证必须抓取到真实原文全文）"""
    video_id = entry.id if 'id' in entry else entry.link
    title = entry.title
    target_url = extract_target_url_from_entry(entry)
    
    if is_processed(video_id):
        return

    # 1. 尝试从 RSS 提取正文
    raw_html = entry.content[0].value if 'content' in entry else getattr(entry, 'summary', '')
    soup = bs4.BeautifulSoup(raw_html, 'html.parser')
    text_content = soup.get_text(separator='\n\n', strip=True)
    
    # 2. 如果是链接聚合源 (如 Hacker News) 或 RSS 提取的正文过短 (只有链接/摘要)，自动深度抓取原文
    if is_link_aggregator or not is_substantive_content(title, text_content, min_chars=350):
        print(f"🌐 正在从原文链接深度抓取正文主体: {target_url}")
        full_text = fetch_full_article_content(target_url, min_chars=300)
        if full_text:
            text_content = full_text
            
    # 3. 严格校验实质内容：如果抓取失败、遇到付费墙(Paywall)或依然没有有效正文，坚决拦截丢弃！
    if not is_substantive_content(title, text_content, min_chars=300):
        print(f"⏭️ 拦截无实质正文或付费墙文章: 《{title}》 (无法提取真实有效正文，跳过生成)")
        mark_processed(video_id, "article_skipped")
        return

    print(f"\n📰 [大咖专栏] 成功提取全文 ({len(text_content)} 字符): 《{title}》 ({feed_name})")
    print(f"🧠 正在深度提炼 {feed_name} 文章...")
    translated_text, analysis = analyze_blog_post(title, feed_name, target_url, f"【文章标题】：{title}\n\n【文章正文】：\n{text_content}")
    
    safe_title = re.sub(r'[\\/*?:"<>|?#%&+=？!！()]', "", title).strip(' .')[:60].strip(' .')
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    raw_md = f"---\ntitle: \"{safe_title}_全翻译\"\ndate: {date_str}\nurl: \"{target_url}\"\nsource: \"{feed_name}\"\ntags: [大咖视点_全文翻译, {feed_name.replace(' ', '_')}]\n---\n\n{translated_text}"
    save_to_vault(f"Raw_翻译_{safe_title}.md", raw_md, title=f"{safe_title}_全翻译")
    
    final_md = f"---\ntitle: \"{safe_title}_简报\"\ndate: {date_str}\nurl: \"{target_url}\"\nsource: \"{feed_name}\"\ntags: [大咖视点_深度解读, {feed_name.replace(' ', '_')}]\n---\n\n{analysis}"
    save_to_vault(f"Auto_简报_{safe_title}.md", final_md, title=f"{safe_title}_简报")
    
    mark_processed(video_id, "article")

def process_github_trending():
    """扫描 Github 每日趋势热榜 (Top 5)"""
    print("\n💻 开始扫描 Github 每日趋势热榜 (Top 5)...")
    trending_url = "https://github.com/trending"
    try:
        req = urllib.request.Request(trending_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=30) as response:
            html = response.read().decode('utf-8')
        soup = bs4.BeautifulSoup(html, 'html.parser')
        
        repo_elements = soup.select('article.Box-row h2.h3 a')[:5]
        if not repo_elements:
            print("⏭️ 未在页面找到仓库链接。")
            return
            
        for repo_element in repo_elements:
            repo_path = repo_element.get('href').strip()
            repo_id = f"github_trending{repo_path}"
            
            if is_processed(repo_id):
                continue
                
            repo_full_url = f"https://github{repo_path}"
            print(f"🔥 发现新的 Github 榜单项目: {repo_path}")
            
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
            
            print("🧠 正在使用 DeepSeek-V4 提炼 Github README...")
            translated_text, analysis = analyze_github_repo(repo_full_url, readme_content)
            
            safe_title = repo_path.replace("/", "_")
            date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            raw_md = f"---\ntitle: \"{safe_title}_全翻译\"\ndate: {date_str}\nurl: \"{repo_full_url}\"\ntags: [Github_Trending, 全文翻译]\n---\n\n{translated_text}"
            save_to_vault(f"Raw_翻译_Github_{safe_title}.md", raw_md, title=f"Github_{safe_title}_全翻译")
            
            final_md = f"---\ntitle: \"{safe_title}_简报\"\ndate: {date_str}\nurl: \"{repo_full_url}\"\ntags: [Github_Trending, 深度解读]\n---\n\n{analysis}"
            save_to_vault(f"Auto_简报_Github_{safe_title}.md", final_md, title=f"Github_{safe_title}_简报")
            
            mark_processed(repo_id, "github")
    except Exception as e:
        print(f"⚠️ Github 榜单获取失败: {e}")

def fetch_and_parse_feed(url: str, needs_proxy: bool = False):
    """使用 requests 配合代理和真实浏览器 UA 拉取 RSS 内容"""
    proxies = PROXIES if needs_proxy else None
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/rss+xml, application/xml, text/xml, application/atom+xml, text/html;q=0.9, */*;q=0.8"
    }
    try:
        # 如果声明需要代理，直接使用代理
        r = requests.get(url, headers=headers, proxies=proxies, timeout=15)
        if r.status_code == 200:
            return feedparser.parse(r.text)
        else:
            print(f"⚠️ RSS 请求返回 HTTP {r.status_code}: {url}")
            return feedparser.parse(r.text)
    except Exception as e:
        try:
            # 自动切换代理/直连重试
            alt_proxies = None if needs_proxy else PROXIES
            r = requests.get(url, headers=headers, proxies=alt_proxies, timeout=15)
            return feedparser.parse(r.text)
        except Exception:
            return feedparser.parse(url, agent=DEFAULT_HEADERS["User-Agent"])

def run_rss_fetcher():
    print("🚀 Gatekeeper 全球顶级财经与科技多源 RSS 自动提炼引擎启动 (强化全文抓取模式)！")
    try:
        init_db()
    except Exception as e:
        print(f"⚠️ 数据库初始化警告: {e}")
    
    feeds = load_feeds()
    
    # 1. 抓取 RSS 源
    for feed in feeds:
        for url in feed["urls"]:
            print(f"\n📡 正在拉取: {feed['name']} ({url})")
            try:
                parsed_feed = fetch_and_parse_feed(url, needs_proxy=feed.get("needs_proxy", False))
                count = 0
                limit = 1 if "top/.rss" in url else (3 if feed["type"] == "youtube" else 3)
                
                if not parsed_feed.entries:
                    print(f"⏭️ {feed['name']} 暂无新条目或解析为空")
                    continue

                for entry in parsed_feed.entries:
                    try:
                        if feed["type"] == "youtube":
                            process_youtube_entry(feed["name"], entry)
                            count += 1
                        elif feed["type"] == "reddit":
                            process_reddit_entry(feed["name"], entry)
                            count += 1
                            time.sleep(2.0)  # 防 Reddit 429 频控
                        elif feed["type"] == "link_aggregator":
                            process_article_entry(feed["name"], entry, is_link_aggregator=True)
                            count += 1
                        else:  # substack, blog
                            process_article_entry(feed["name"], entry, is_link_aggregator=False)
                            count += 1
                    except Exception as entry_err:
                        print(f"⚠️ 处理单个条目异常 《{getattr(entry, 'title', '未知')}》: {entry_err}")
                        
                    if count >= limit:
                        break 
            except Exception as e:
                print(f"⚠️ 拉取 {feed['name']} 失败: {e}")
            
    # 2. 抓取 Github 趋势 (获取前 5 名)
    try:
        process_github_trending()
    except Exception as e:
        print(f"⚠️ GitHub 趋势抓取异常: {e}")

if __name__ == "__main__":
    run_rss_fetcher()

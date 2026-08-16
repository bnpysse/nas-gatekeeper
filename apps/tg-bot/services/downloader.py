#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
音视频提取模块：使用 yt-dlp 原生提取器极速下载音轨并由 ffmpeg 转换 m4a (AAC)
"""

import re
import sys
import json
import uuid
import shutil
import logging
import subprocess
import urllib.parse
from pathlib import Path

import requests

parent_dir = str(Path(__file__).resolve().parent.parent)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from config import Config

logger = logging.getLogger(__name__)

DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

VIDEO_URL_PATTERN = re.compile(
    r'https?://(?:[a-zA-Z0-9\-]+\.)?'
    r'(?:toutiao|ixigua|xigua|douyin|bilibili|b23|youtube|youtu\.be|v\.qq|163\.com)'
    r'[^\s\u3000-\u9fff]+'
)

SHORT_LINK_DOMAINS = [
    "v.toutiao.com",
    "m.toutiao.com/is/",
    "b23.tv",
    "v.douyin.com",
]

TOUTIAO_DOMAINS = ["toutiao", "ixigua", "xigua"]

# Cookie 文件自动定位
def find_cookies_file() -> Path | None:
    """自动定位 cookies.txt 认证文件"""
    candidates = [
        Path(__file__).parent.parent / "cookies.txt",
        Path("/opt/nas-gatekeeper/apps/tg-bot/cookies.txt"),
        Path("/app/cookies.txt"),
        Path.cwd() / "cookies.txt",
        Path.cwd() / "apps/tg-bot/cookies.txt",
    ]
    for c in candidates:
        if c.exists() and c.stat().st_size > 50:
            return c
    return None

def parse_netscape_cookies(cookies_file: Path, domain_match: str = "toutiao.com") -> dict:
    """解析 Netscape 格式 cookies.txt 为 requests 字典"""
    cookies = {}
    if not cookies_file or not cookies_file.exists():
        return cookies
    try:
        with open(cookies_file, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) >= 7:
                    domain, _, _, _, _, name, value = parts[:7]
                    if domain_match in domain or "bytedance.com" in domain or "douyin.com" in domain:
                        cookies[name] = value
    except Exception as e:
        logger.warning(f"解析 cookies 失败: {e}")
    return cookies

def get_direct_session() -> requests.Session:
    """创建物理隔离代理的直连 Session（访问国内短链）"""
    session = requests.Session()
    session.trust_env = False
    return session

def find_ytdlp() -> str:
    """自动定位 yt-dlp 可执行文件"""
    venv_ytdlp = Path(sys.executable).parent / "yt-dlp"
    if venv_ytdlp.exists():
        return str(venv_ytdlp)

    system_ytdlp = shutil.which("yt-dlp")
    if system_ytdlp:
        return system_ytdlp

    raise FileNotFoundError("未找到 yt-dlp 可执行文件。请运行: pip install yt-dlp")

def find_ffmpeg() -> str | None:
    """自动定位 ffmpeg 可执行文件"""
    mise_ffmpeg = Path.home() / ".local/share/mise/shims/ffmpeg"
    if mise_ffmpeg.exists():
        return str(mise_ffmpeg)

    for fallback in ["/usr/local/bin/ffmpeg", "/usr/bin/ffmpeg"]:
        if Path(fallback).exists():
            return fallback

    system_ffmpeg = shutil.which("ffmpeg")
    return system_ffmpeg

def is_video_url(text: str) -> bool:
    """检查文本是否包含受支持的视频平台链接"""
    return bool(VIDEO_URL_PATTERN.search(text))

def extract_url(text: str) -> str:
    """从消息文本中提取第一个 URL，剔除末尾标点"""
    match = re.search(r'https?://[a-zA-Z0-9.\-_~:/?#\[\]@!$&\'()*+,;=%]+', text)
    if not match:
        return text.strip()
    return match.group(0).rstrip("。，,!？?")

def extract_group_id(text: str) -> str | None:
    """提取头条/西瓜 15-20 位 Group ID"""
    patterns = [
        r'(?:video|group|is)/(\d{15,20})',
        r'group_id=(\d{15,20})',
        r'/(\d{18,20})(?:[/?]|$)',
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            return m.group(1)
    return None

def build_toutiao_url(group_id: str) -> str:
    """构造标准 toutiao.com URL"""
    return f"https://www.toutiao.com/video/{group_id}/"

def resolve_short_link(url: str) -> str:
    """跟随 App 短链 301 重定向获取真实落地地址"""
    session = get_direct_session()
    headers = {"User-Agent": DESKTOP_UA}
    try:
        resp = session.get(url, headers=headers, allow_redirects=True, timeout=10)
        landed = resp.url
        logger.info(f"短链落地解析: {url[:40]}... → {landed[:70]}...")
        return landed
    except Exception as e:
        logger.warning(f"短链跳转失败使用原 URL: {e}")
        return url

def extract_toutiao_audio_direct(target_url: str, output_dir: Path) -> tuple[Path, str] | None:
    """通过 Cookie 注入 + RENDER_DATA 原生直链提取头条高保真音轨流（绕过 yt-dlp 400 限制）"""
    logger.info(f"尝试使用 RENDER_DATA 原生协议直提头条音轨: {target_url}")
    cookies_path = find_cookies_file()
    cookies = parse_netscape_cookies(cookies_path, "toutiao.com") if cookies_path else {}
    
    headers = {
        "User-Agent": DESKTOP_UA,
        "Referer": "https://www.toutiao.com/",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    }
    session = get_direct_session()
    try:
        resp = session.get(target_url, headers=headers, cookies=cookies, timeout=15)
        if resp.status_code != 200:
            logger.warning(f"头条网页请求状态码异常: {resp.status_code}")
            return None

        # 匹配 RENDER_DATA 脚本
        match = re.search(r'<script id="RENDER_DATA"[^>]*>(.*?)</script>', resp.text, re.DOTALL)
        if not match:
            logger.warning("未在头条页面找到 RENDER_DATA 节点")
            return None

        raw_json = urllib.parse.unquote(match.group(1).strip())
        page_data = json.loads(raw_json)
        init_video = page_data.get("data", {}).get("initialVideo", {})
        if not init_video:
            logger.warning("RENDER_DATA 中无 initialVideo 数据")
            return None

        title = init_video.get("title") or "头条精选视频"
        video_play_info = init_video.get("videoPlayInfo", {})
        dynamic_video = video_play_info.get("dynamic_video", {})
        dynamic_audio_list = dynamic_video.get("dynamic_audio_list", [])

        # 收集主节点和备份节点 CDN 链接
        candidate_urls = []
        if dynamic_audio_list:
            for aud in dynamic_audio_list:
                if aud.get("main_url"):
                    candidate_urls.append(aud["main_url"])
                if aud.get("backup_url"):
                    candidate_urls.append(aud["backup_url"])

        # 降级备选视频直链
        vlist = video_play_info.get("video_list", [])
        for v in vlist:
            if v.get("main_url"):
                candidate_urls.append(v["main_url"])
            if v.get("backup_url"):
                candidate_urls.append(v["backup_url"])

        if not candidate_urls:
            logger.warning("未能在 RENDER_DATA 中找到可播放媒体直链")
            return None

        file_id = uuid.uuid4().hex[:8]
        out_file = output_dir / f"audio_{file_id}.m4a"

        # 健壮的多节点、分片重试下载
        stream_headers = {
            "User-Agent": DESKTOP_UA,
            "Referer": "https://www.toutiao.com/",
            "Accept-Encoding": "identity",
        }

        download_success = False
        for cur_url in candidate_urls:
            downloaded = 0
            try:
                for attempt in range(3):
                    req_hdrs = stream_headers.copy()
                    if downloaded > 0:
                        req_hdrs["Range"] = f"bytes={downloaded}-"
                    
                    with session.get(cur_url, headers=req_hdrs, stream=True, timeout=(10, 60)) as stream_resp:
                        if stream_resp.status_code not in (200, 206):
                            break
                        mode = "ab" if downloaded > 0 else "wb"
                        with open(out_file, mode) as f:
                            for chunk in stream_resp.iter_content(chunk_size=131072):
                                if chunk:
                                    f.write(chunk)
                                    downloaded += len(chunk)
                    
                    if out_file.exists() and out_file.stat().st_size > 10240:
                        download_success = True
                        break
                if download_success:
                    break
            except Exception as stream_err:
                logger.warning(f"当前 CDN 节点下载受阻({cur_url[:45]}...): {stream_err}，尝试下一个备用节点")

        if download_success and out_file.exists() and out_file.stat().st_size > 10240:
            logger.info(f"RENDER_DATA 直提音轨成功: 《{title}》 ({out_file.stat().st_size // 1024} KB)")
            return out_file, title

    except Exception as e:
        logger.warning(f"RENDER_DATA 直提音轨发生异常: {e}")
    return None

def download_audio_from_url(
    url: str,
    output_dir: Path = Path("/tmp/secondbrain_bot"),
) -> tuple[Path, str]:
    """提取视频音轨并保存为 m4a (AAC) 文件"""
    output_dir.mkdir(parents=True, exist_ok=True)
    file_id = uuid.uuid4().hex[:8]
    output_template = str(output_dir / f"audio_{file_id}.%(ext)s")

    is_short = any(domain in url for domain in SHORT_LINK_DOMAINS)
    landing_url = resolve_short_link(url) if is_short else url

    target_url = landing_url
    is_toutiao = any(d in landing_url for d in TOUTIAO_DOMAINS)

    if is_toutiao:
        group_id = extract_group_id(landing_url)
        if group_id:
            target_url = build_toutiao_url(group_id)
            logger.info(f"构造干净头条视频 URL: {target_url}")
        else:
            target_url = landing_url.split("?")[0]

        # 【最高优先级】：尝试基于 Cookie + RENDER_DATA 原生直链秒级提取
        direct_res = extract_toutiao_audio_direct(target_url, output_dir)
        if direct_res:
            return direct_res

    ytdlp_bin = find_ytdlp()
    ffmpeg_bin = find_ffmpeg()

    # 头条国内直连，YouTube/Twitter 走代理
    is_foreign = any(d in target_url for d in ["youtube", "youtu.be", "twitter", "x.com"])
    proxy_args = ["--proxy", Config.HTTP_PROXY] if (is_foreign and Config.HTTP_PROXY) else []
    ffmpeg_args = ["--ffmpeg-location", ffmpeg_bin] if ffmpeg_bin else []

    # Cookie 认证（仅头条/西瓜等字节系平台使用专属 cookies.txt，避免污染 YouTube 等海外平台）
    cookies_path = find_cookies_file()
    cookies_args = ["--cookies", str(cookies_path)] if (cookies_path and is_toutiao) else []

    # Step 1: 获取视频标题
    video_title = f"视频_{file_id}"
    try:
        title_cmd = [
            ytdlp_bin,
            "--no-playlist",
            "--user-agent", DESKTOP_UA,
            "--get-title",
            "--no-warnings",
        ] + cookies_args + proxy_args + [target_url]

        title_result = subprocess.run(
            title_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15,
        )
        raw_title = title_result.stdout.strip().splitlines()
        if raw_title and raw_title[0].strip():
            video_title = raw_title[0].strip()
            logger.info(f"视频标题: {video_title}")
    except Exception as e:
        logger.warning(f"获取标题失败使用默认标题: {e}")

    # Step 2: 下载并提取音轨
    dl_cmd = [
        ytdlp_bin,
        "-f", "ba/b",
        "-x",
        "--no-playlist",
        "--user-agent", DESKTOP_UA,
        "--audio-format", "m4a",
        "--audio-quality", "0",
        "--no-cache-dir",
        "--output", output_template,
        "--no-warnings",
    ] + ffmpeg_args + cookies_args + proxy_args + [target_url]

    logger.info(f"yt-dlp 开始提取音轨: {target_url}")
    try:
        result = subprocess.run(
            dl_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )

        possible_files = sorted(output_dir.glob(f"audio_{file_id}.*"))
        if not possible_files:
            raise FileNotFoundError(
                f"yt-dlp 运行完成但未找到输出文件。stderr: {result.stderr[:300]}"
            )

        audio_path = possible_files[0]
        logger.info(f"音频提取成功: {audio_path} ({audio_path.stat().st_size // 1024} KB)")
        return audio_path, video_title

    except subprocess.CalledProcessError as e:
        err_msg = (e.stderr or e.stdout or str(e)).strip()
        logger.warning(f"yt-dlp 执行失败: {err_msg[:200]}")
        if "Unable to extract video data" in err_msg or "400" in err_msg:
            raise RuntimeError("平台动态加密流或防爬限制 (yt-dlp VOD 400)")
        raise RuntimeError(f"音轨提取失败: {err_msg[:120]}")

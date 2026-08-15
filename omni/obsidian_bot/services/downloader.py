#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
视频/音频下载服务

支持平台：今日头条 / 西瓜视频 / 抖音 / B站 / YouTube
核心引擎：yt-dlp 原生 extractor（内置 toutiao / douyin / bilibili 解析）

工作流程：
1. 识别链接来源（App 短链需先 301 跟随重定向到落地地址）
2. 提取 Group ID，构造标准 toutiao.com/video/{id}/ 格式的干净 URL
3. 调用 yt-dlp（通过当前 Python venv 的可执行路径）下载视频
4. 提取 m4a（AAC）音轨——Gemini API 原生支持
5. 返回音频文件路径和视频标题

已知注意事项：
- 头条/西瓜需要通过代理访问（由 config.py 的 HTTP_PROXY 提供）
- 使用 m4a (AAC) 而非 mp3，因为 mise 管理的 ffmpeg 未编译 libmp3lame
- yt-dlp 可执行文件通过同级 venv 自动定位，无需全局安装
"""

import os
import re
import sys
import uuid
import shutil
import logging
import subprocess
from pathlib import Path

import requests

parent_dir = str(Path(__file__).resolve().parent.parent)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from config import Config

logger = logging.getLogger(__name__)

# ─── 常量 ──────────────────────────────────────────────────────────────────────

DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

# 匹配消息文本中视频链接的正则
VIDEO_URL_PATTERN = re.compile(
    r'https?://(?:[a-zA-Z0-9\-]+\.)?'
    r'(?:toutiao|ixigua|xigua|douyin|bilibili|b23|youtube|youtu\.be|v\.qq|163\.com)'
    r'[^\s\u3000-\u9fff]+'
)

# 今日头条 / 西瓜视频 / 抖音 / B站 App 短链域名（需先跟随重定向）
SHORT_LINK_DOMAINS = [
    "v.toutiao.com",
    "m.toutiao.com/is/",
    "b23.tv",
    "v.douyin.com",
]

# 头条/西瓜 CDN 流需要走代理的域名特征
TOUTIAO_DOMAINS = ["toutiao", "ixigua", "xigua"]

# ─── 工具函数 ──────────────────────────────────────────────────────────────────

def get_direct_session() -> requests.Session:
    """创建物理隔离代理的直连 Session（用于访问国内服务）"""
    session = requests.Session()
    session.trust_env = False  # 忽略系统/环境变量代理
    return session


def find_ytdlp() -> str:
    """
    自动定位 yt-dlp 可执行文件。
    优先顺序：
    1. 当前 Python 解释器同 bin 目录（venv 场景）
    2. PATH 中的 yt-dlp
    3. 抛出 FileNotFoundError
    """
    # 与当前 Python 解释器同一 bin 目录（最可靠）
    venv_ytdlp = Path(sys.executable).parent / "yt-dlp"
    if venv_ytdlp.exists():
        return str(venv_ytdlp)

    # 系统 PATH 搜索
    system_ytdlp = shutil.which("yt-dlp")
    if system_ytdlp:
        return system_ytdlp

    raise FileNotFoundError(
        "未找到 yt-dlp 可执行文件。请运行：uv pip install yt-dlp"
    )


def find_ffmpeg() -> str | None:
    """
    自动定位 ffmpeg 可执行文件。
    优先顺序：
    1. mise shims（macOS 常见安装路径）
    2. PATH
    3. 返回 None（yt-dlp 无后处理仍可工作）
    """
    mise_ffmpeg = Path.home() / ".local/share/mise/shims/ffmpeg"
    if mise_ffmpeg.exists():
        return str(mise_ffmpeg)

    system_ffmpeg = shutil.which("ffmpeg")
    return system_ffmpeg


def is_video_url(text: str) -> bool:
    """检查文本是否包含受支持的视频平台链接"""
    return bool(VIDEO_URL_PATTERN.search(text))


def extract_url(text: str) -> str:
    """从 App 分享的混合文本中提取第一个 URL，剔除末尾中文标点"""
    match = re.search(r'https?://[a-zA-Z0-9.\-_~:/?#\[\]@!$&\'()*+,;=%]+', text)
    if not match:
        return text.strip()
    return match.group(0).rstrip("。，,!？?")


def extract_group_id(text: str) -> str | None:
    """
    从头条/西瓜 URL 或文本中提取 15–20 位视频数字 ID（Group ID）。
    适用格式：
    - .../video/7668159453748953644/
    - .../is/7668159453748953644
    - m.toutiao.com/is/7668159453748953644/
    """
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
    """构造标准 PC 版今日头条视频直链（yt-dlp toutiao extractor 专用格式）"""
    return f"https://www.toutiao.com/video/{group_id}/"


def resolve_short_link(url: str) -> str:
    """
    对 App 分享的短链接跟随 301/302 重定向，返回最终落地 URL。
    使用 trust_env=False 的 Session 确保直连（不走系统代理）。
    """
    session = get_direct_session()
    headers = {"User-Agent": DESKTOP_UA}
    try:
        resp = session.get(url, headers=headers, allow_redirects=True, timeout=10)
        landed = resp.url
        logger.info(f"短链落地: {url[:50]} → {landed[:80]}")
        return landed
    except Exception as e:
        logger.warning(f"短链跳转失败，使用原始 URL: {e}")
        return url


# ─── 核心下载函数 ──────────────────────────────────────────────────────────────

def download_audio_from_url(
    url: str,
    output_dir: Path = Path("/tmp/brain_bot"),
) -> tuple[Path, str]:
    """
    从视频链接提取音轨并保存为 m4a (AAC) 文件。

    处理流程：
    1. 短链解析 → 获得落地 URL
    2. 头条/西瓜链接 → 提取 Group ID → 构造干净 toutiao.com URL
    3. yt-dlp 下载并提取音轨（优先 m4a / AAC，ffmpeg 自动定位）
    4. 返回 (音频文件路径, 视频标题)

    Args:
        url: 视频链接（支持 App 分享短链）
        output_dir: 临时输出目录

    Returns:
        (Path: m4a 音频文件路径, str: 视频标题)

    Raises:
        RuntimeError: yt-dlp 下载失败
        FileNotFoundError: yt-dlp 不可用 / 输出文件未生成
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    file_id = uuid.uuid4().hex[:8]
    output_template = str(output_dir / f"audio_{file_id}.%(ext)s")

    # ── Step 1: 短链解析 ────────────────────────────────────────────────────
    is_short = any(domain in url for domain in SHORT_LINK_DOMAINS)
    landing_url = resolve_short_link(url) if is_short else url

    # ── Step 2: 构造干净头条 URL ────────────────────────────────────────────
    target_url = landing_url
    is_toutiao = any(d in landing_url for d in TOUTIAO_DOMAINS)

    if is_toutiao:
        group_id = extract_group_id(landing_url)
        if group_id:
            target_url = build_toutiao_url(group_id)
            logger.info(f"构造干净头条 URL: {target_url}")
        else:
            # 无法提取 ID，直接使用落地 URL 并剔除 App 参数
            target_url = landing_url.split("?")[0]
            logger.warning(f"无法提取 Group ID，使用剔除参数后的 URL: {target_url}")

    # ── Step 3: 定位工具 ─────────────────────────────────────────────────────
    ytdlp_bin = find_ytdlp()
    ffmpeg_bin = find_ffmpeg()
    logger.info(f"yt-dlp: {ytdlp_bin}")
    if ffmpeg_bin:
        logger.info(f"ffmpeg: {ffmpeg_bin}")
    else:
        logger.warning("ffmpeg 未找到，将跳过音轨转换（直接保存原始音频流）")

    # 代理参数（头条/西瓜/YouTube/Twitter 需要走代理）
    needs_proxy = is_toutiao or any(d in target_url for d in ["youtube", "youtu.be", "twitter", "x.com"])
    proxy_args = ["--proxy", Config.HTTP_PROXY] if (needs_proxy and Config.HTTP_PROXY) else []
    if proxy_args:
        logger.info(f"使用代理: {Config.HTTP_PROXY}")

    # ffmpeg 参数
    ffmpeg_args = ["--ffmpeg-location", ffmpeg_bin] if ffmpeg_bin else []

    # ── Step 4a: 获取视频标题（--get-title 只读元数据，不下载）────────────────
    video_title = f"视频_{file_id}"
    try:
        title_cmd = [
            ytdlp_bin,
            "--no-playlist",
            "--user-agent", DESKTOP_UA,
            "--get-title",
            "--no-warnings",
        ] + proxy_args + [target_url]

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
        logger.warning(f"获取标题失败（使用默认标题）: {e}")

    # ── Step 4b: 下载并提取音轨 ──────────────────────────────────────────────
    #
    # 关键注意：--print 与 --extract-audio 同时使用时，yt-dlp 会进入模拟模式
    # 只打印元数据，完全跳过实际下载。因此标题获取必须单独进行（Step 4a），
    # 此处不使用 --print 参数。
    #
    dl_cmd = [
        ytdlp_bin,
        "--no-playlist",
        "--user-agent", DESKTOP_UA,
        "--extract-audio",
        "--audio-format", "m4a",   # AAC/m4a — Gemini File API 原生支持
        "--audio-quality", "0",    # 最佳质量
        "--no-cache-dir",          # 禁用缓存，防止同一视频被跳过不下载
        "--output", output_template,
        "--no-warnings",
    ] + ffmpeg_args + proxy_args + [target_url]

    # ── Step 5: 执行下载 ─────────────────────────────────────────────────────
    logger.info(f"yt-dlp 开始下载音轨: {target_url}")
    try:
        result = subprocess.run(
            dl_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )

        # 查找生成的音频文件（yt-dlp 先写 .mp4，ffmpeg 转为 .m4a 后删除 .mp4）
        possible_files = sorted(output_dir.glob(f"audio_{file_id}.*"))
        if not possible_files:
            raise FileNotFoundError(
                f"yt-dlp 运行完成但未找到输出文件。\n"
                f"stderr: {result.stderr[:400]}"
            )

        audio_path = possible_files[0]
        logger.info(f"音频文件: {audio_path} ({audio_path.stat().st_size // 1024} KB)")
        return audio_path, video_title

    except subprocess.CalledProcessError as e:
        err_msg = (e.stderr or e.stdout or str(e)).strip()
        logger.error(f"yt-dlp 失败:\n{err_msg}")
        raise RuntimeError(f"视频下载失败: {err_msg[:400]}")

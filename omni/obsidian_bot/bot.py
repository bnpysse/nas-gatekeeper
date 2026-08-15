#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Woodman_Brain_Bot 主入口程序：Telegram Bot 异步服务
"""

import sys
import logging
from pathlib import Path

# 确保把当前 obsidian_bot 目录及上级目录加进 sys.path
current_dir = Path(__file__).resolve().parent
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))

from telegram import Update
from telegram.request import HTTPXRequest
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from config import Config
from services.downloader import is_video_url, extract_url, download_audio_from_url
from services.ai import analyze_audio_with_gemini, analyze_web_url
from services.obsidian import save_to_obsidian_inbox
from services.cleaner import auto_prune_inbox

# 配置日志格式
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("Woodman_Brain_Bot")

def check_permission(update: Update) -> bool:
    """严格检查用户 ID 是否匹配 ALLOWED_USER_ID"""
    user_id = update.effective_user.id if update.effective_user else 0
    if user_id != Config.ALLOWED_USER_ID:
        logger.warning(f"拒绝未经授权的用户访问: {user_id}")
        return False
    return True

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_permission(update):
        return
    welcome_text = (
        "🧠 *Woodman Brain Bot 个人知识助理已上线！*\n\n"
        "你可以直接向我发送：\n"
        "1. 🎥 **头条/西瓜/抖音/B站/YouTube 视频链接**：我将提取音轨，并由 Gemini 生成【核心总结 + 中文逐字稿】落库 Obsidian。\n"
        "2. 📰 **知乎/微信公众号/网页链接**：我将抓取正文并由 Gemini 分析提炼。\n"
        "3. 🎙️ **语音/文字闪念**：自动记录并落地到 Obsidian Inbox。\n\n"
        "⚙️ 指令：\n"
        "/status - 查看运行状态\n"
        "/clean - 手动触发 30 天旧草稿清理"
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_permission(update):
        return
    status_text = (
        "🟢 *系统状态正常*\n"
        f"- 允许的 User ID: `{Config.ALLOWED_USER_ID}`\n"
        f"- Obsidian Inbox: `{Config.OBSIDIAN_INBOX_PATH}`\n"
        f"- Inbox 自动清理周期: `{Config.INBOX_AUTO_PRUNE_DAYS}` 天\n"
        f"- 代理连接: `{Config.HTTP_PROXY or '无'}`"
    )
    await update.message.reply_text(status_text, parse_mode="Markdown")

async def clean_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_permission(update):
        return
    await update.message.reply_text("🧹 正在清理 Inbox 超过 30 天未归档草稿...")
    count = auto_prune_inbox()
    await update.message.reply_text(f"✅ 清理完成，共移除了 {count} 份过期临时草稿。")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理用户发送的消息 (链接/文本)"""
    if not check_permission(update):
        return

    text = update.message.text or ""
    url = extract_url(text)

    # 1. 处理视频链接 (今日头条 / 西瓜视频 / B站 / YouTube 等)
    if is_video_url(text) or ("http" in text and any(k in text for k in ["toutiao", "xigua", "douyin", "bilibili", "youtube"])):
        msg = await update.message.reply_text("📥 收到视频链接，正在抓取音轨中，请稍候...")
        try:
            audio_path, video_title = download_audio_from_url(url)
            await msg.edit_text(f"🎧 音频抓取成功！正在调用 Gemini 1.5 进行【中文语音转文字 + 总结分析】...\n《{video_title}》")

            ai_result = analyze_audio_with_gemini(audio_path, video_title)
            
            note_path = save_to_obsidian_inbox(
                title=ai_result["title"],
                url=url,
                content=ai_result["content"],
                source_type="Toutiao_Video"
            )

            try:
                if audio_path.exists():
                    audio_path.unlink()
            except Exception:
                pass

            gdrive_status = ""
            gdrive_path = getattr(Config, "GDRIVE_SYNC_PATH", None)
            if gdrive_path and gdrive_path.exists():
                gdrive_status = f"\n☁️ **Google Drive**: 已同步至 `{gdrive_path.name}`，可在网页端 Gem 中直接 `@` 引用！"

            await msg.edit_text(
                f"✅ *完美归档！*\n\n"
                f"📌 **标题**: {ai_result['title']}\n"
                f"📁 **Obsidian**: `{note_path.name}`"
                f"{gdrive_status}\n\n"
                f"可在 Mac 端阅读与双链整理！",
                parse_mode="Markdown"
            )

        except Exception as e:
            logger.error(f"处理视频链接失败: {e}", exc_info=True)
            await msg.edit_text(f"❌ 处理视频失败: {e}")

    # 2. 处理普通网页链接 (知乎/微信公众号/普通博客)
    elif "http://" in text or "https://" in text:
        msg = await update.message.reply_text("📰 收到网页链接，正在抓取正文并进行 AI 总结...")
        try:
            ai_result = analyze_web_url(url)
            note_path = save_to_obsidian_inbox(
                title=ai_result["title"],
                url=url,
                content=ai_result["content"],
                source_type="Web"
            )
            await msg.edit_text(f"✅ 网页分析完成，已存入 Obsidian: `{note_path.name}`", parse_mode="Markdown")
        except Exception as e:
            logger.error(f"处理网页失败: {e}")
            await msg.edit_text(f"❌ 网页解析失败: {e}")

    # 3. 处理普通纯文本闪念
    else:
        note_path = save_to_obsidian_inbox(
            title="纯文本闪念笔记",
            url="",
            content=text,
            source_type="Memo"
        )
        await update.message.reply_text(f"📝 闪念笔记已保存至: `{note_path.name}`", parse_mode="Markdown")

async def daily_prune_job(context: ContextTypes.DEFAULT_TYPE):
    """定时任务：每天自动扫描清理一次旧草稿"""
    logger.info("执行每日定时清理任务...")
    count = auto_prune_inbox()
    logger.info(f"定时清理完成，移除了 {count} 份过期草稿。")

def main():
    """主函数入口"""
    Config.validate()
    logger.info("启动 Woodman_Brain_Bot...")

    builder = Application.builder().token(Config.TELEGRAM_BOT_TOKEN)

    proxy_url = Config.HTTP_PROXY or Config.HTTPS_PROXY
    if proxy_url:
        if not (proxy_url.startswith("http://") or proxy_url.startswith("https://") or proxy_url.startswith("socks5://")):
            proxy_url = f"http://{proxy_url}"
        logger.info(f"配置 Telegram Bot 代理网络: {proxy_url}")
        
        # 兼容 python-telegram-bot 版本：参数名在某些版本为 proxy，某些为 proxy_url
        try:
            request_client = HTTPXRequest(proxy=proxy_url)
            get_updates_request_client = HTTPXRequest(proxy=proxy_url)
        except TypeError:
            request_client = HTTPXRequest(proxy_url=proxy_url)
            get_updates_request_client = HTTPXRequest(proxy_url=proxy_url)
        
        builder = builder.request(request_client).get_updates_request(get_updates_request_client)

    app = builder.build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("clean", clean_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    if app.job_queue:
        app.job_queue.run_repeating(daily_prune_job, interval=86400, first=10)

    logger.info("Bot 已开始 Polling 监听...")
    app.run_polling()

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
第二大脑·AI 智能图书馆 Telegram 交互式学习机器人 (`telegram_bot.py`)
支持：
  1. /library 或 /books : 查看藏书馆书架与一键操作
  2. /quiz [序号] [主题] : 原生内联做题卡片，点击 A/B/C/D 现场由 DeepSeek 错题复盘与原著溯源
  3. /podcast [序号]     : 随时向手机发送高保真双人对谈听书音频 (.m4a)
  4. /status             : 实时全景 Token 算力大屏与模型消耗统计
"""

import os
import sys
import json
import logging
import asyncio
from pathlib import Path

# 保证能加载 books_pipeline 模块
current_dir = Path(__file__).resolve().parent
parent_dir = current_dir.parent
for p in [str(current_dir), str(parent_dir)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile
)
from telegram.constants import ParseMode
from telegram.request import HTTPXRequest
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters
)

from config import LibraryConfig
from db import get_all_books, get_total_library_usage
from dynamic_quiz import generate_dynamic_quiz, evaluate_and_explain

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("LibraryTGBot")

# 尝试从环境变量或 .env 读取配置
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8728962844:AAHZC5LFGUYiQ7uDP3fPwqao_6OmtoICS3E")
PROXY_URL = os.getenv("HTTP_PROXY") or os.getenv("HTTPS_PROXY") or "http://127.0.0.1:7890"


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """欢迎与主菜单"""
    welcome_text = (
        "📚 *欢迎来到【第二大脑·AI 智能图书馆】*\n\n"
        "这里纳管了您的全套计算机经典精读资产，支持：\n"
        "• 🎲 *RAG 动态无限做题*：现场命题，专属错因深度复盘与原著溯源\n"
        "• 🎧 *双人对谈听书播客*：男女声（睿哥/小林）高保真随身听\n"
        "• 📊 *全景 Token 算力大屏*：实时掌握各大模型用量与台账\n\n"
        "👉 请点击下方按钮或发送指令："
    )
    keyboard = [
        [
            InlineKeyboardButton("📚 浏览藏书馆", callback_data="menu_books"),
            InlineKeyboardButton("🎲 随机盲盒做题", callback_data="menu_random_quiz")
        ],
        [
            InlineKeyboardButton("🎧 听书播客库", callback_data="menu_podcasts"),
            InlineKeyboardButton("💰 Token 算力台账", callback_data="menu_usage")
        ]
    ]
    await update.message.reply_text(
        welcome_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )


async def show_library_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """展示藏书馆书架"""
    books = await get_all_books()
    if not books:
        text = "📭 当前图书馆暂无已入库书籍。"
        keyboard = []
    else:
        text = f"📚 *【AI 智能图书馆藏书架】* (共 {len(books)} 本经典专著)\n\n"
        keyboard = []
        for idx, b in enumerate(books, 1):
            title = b.get('title', '未知书名')
            chunks = b.get('total_chunks', 0)
            fmt = (b.get('format') or 'DOC').upper()
            text += f"*{idx}.* 《{title}》\n   └ 格式: `{fmt}` | 向量切块: `{chunks}` 块\n\n"
            
            # 为每本书提供做题和听书按钮
            keyboard.append([
                InlineKeyboardButton(f"📝 研学抽题: {title[:16]}...", callback_data=f"quiz_book_{b['id']}"),
                InlineKeyboardButton("🎧 听书", callback_data=f"podcast_{b['id']}")
            ])
            
    keyboard.append([InlineKeyboardButton("🔙 返回主菜单", callback_data="menu_main")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)


async def show_usage_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """展示全景算力与 Token 消耗台账"""
    tot = await get_total_library_usage()
    calls = tot.get("total_calls", 0)
    grand_tokens = tot.get("grand_total_tokens", 0)

    text = (
        "💰 *【第二大脑·AI 智能图书馆算力大屏】*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"• 累计模型调用: `{calls}` 次\n"
        f"• 累计 Token 消耗: `{grand_tokens:,}` Tokens\n\n"
        "*各大模型消耗明细：*\n"
    )
    for row in tot.get("breakdown", []):
        provider = row.get("provider", "")
        model = row.get("model_name", "")
        p_tok = row.get("total_prompt_tokens", 0)
        c_tok = row.get("total_completion_tokens", 0)
        t_tok = row.get("grand_total_tokens", 0)
        dur = row.get("total_duration", 0.0)
        cnt = row.get("call_count", 0)
        text += (
            f"• *{provider}* (`{model}`):\n"
            f"   └ 消耗: `{t_tok:,}` Tokens (提示: {p_tok:,}, 生成: {c_tok:,})\n"
            f"   └ 累计耗时: `{dur:.1f}s` | 调用: `{cnt}` 次\n"
        )
    text += "━━━━━━━━━━━━━━━━━━━━\n_数据实时来源于 Turso 边缘数据库台账表_"
    
    keyboard = [[InlineKeyboardButton("🔙 返回主菜单", callback_data="menu_main")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)


async def handle_quiz_generation(update: Update, context: ContextTypes.DEFAULT_TYPE, book_id: str = None, topic: str = None):
    """处理动态 RAG 命题"""
    query = update.callback_query
    if query:
        await query.answer("🧠 正在通过 DeepSeek-V4-Pro 现场命制技术试题，请稍候...", show_alert=False)
        msg = await query.message.reply_text("🎲 *正在基于原著真实切块命制试题...*", parse_mode=ParseMode.MARKDOWN)
    else:
        msg = await update.message.reply_text("🎲 *正在基于原著真实切块命制试题...*", parse_mode=ParseMode.MARKDOWN)

    try:
        if not book_id:
            books = await get_all_books()
            if not books:
                await msg.edit_text("❌ 图书馆暂无书籍。")
                return
            book_id = books[0]["id"]

        quiz = await generate_dynamic_quiz(book_id, topic)
        question = quiz["question"]
        options = quiz.get("options", {})
        chapter = quiz.get("chapter_title", "核心章节")
        quiz_id = quiz["quiz_id"]

        quiz_text = (
            f"📝 *【技术研习测试题】*\n"
            f"📌 出处：《`{quiz.get('book_id', book_id)}`》\n"
            f"📑 章节：_{chapter}_\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{question}\n\n"
        )
        for opt in ["A", "B", "C", "D"]:
            if opt in options:
                quiz_text += f"*{opt}.* {options[opt]}\n"

        quiz_text += "\n━━━━━━━━━━━━━━━━━━━━\n👉 *请点击下方按钮选择你的答案：*"

        # 4 个选项按钮 + 换题按钮
        keyboard = [
            [
                InlineKeyboardButton("🅰️ 选项 A", callback_data=f"ans_{quiz_id}_A"),
                InlineKeyboardButton("🅱️ 选项 B", callback_data=f"ans_{quiz_id}_B"),
            ],
            [
                InlineKeyboardButton("🅲 选项 C", callback_data=f"ans_{quiz_id}_C"),
                InlineKeyboardButton("🅳 选项 D", callback_data=f"ans_{quiz_id}_D"),
            ],
            [
                InlineKeyboardButton("🔄 换一题", callback_data=f"quiz_book_{book_id}"),
                InlineKeyboardButton("📚 回书架", callback_data="menu_books")
            ]
        ]
        await msg.edit_text(quiz_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        logger.error(f"出题失败: {e}", exc_info=True)
        await msg.edit_text(f"❌ 命制试题时出现异常: {e}\n请稍后重试。")


async def handle_quiz_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """用户点击 A/B/C/D 后的智能复盘与原著溯源"""
    query = update.callback_query
    await query.answer("⚡ 正在由导师进行专属思维剖析与原著溯源...", show_alert=False)
    
    data = query.data  # ans_{quiz_id}_{choice}
    parts = data.split("_")
    if len(parts) < 3:
        return
    quiz_id = parts[1]
    user_choice = parts[2]

    # 发送临时提示
    status_msg = await query.message.reply_text(f"🔍 你的选择是 *[{user_choice}]*，正在深度复盘中...", parse_mode=ParseMode.MARKDOWN)

    try:
        eval_res = await evaluate_and_explain(quiz_id, user_choice)
        analysis = eval_res.get("analysis", "")
        
        keyboard = [
            [
                InlineKeyboardButton("🎲 再来一题", callback_data=f"menu_random_quiz"),
                InlineKeyboardButton("📚 查看书架", callback_data="menu_books")
            ]
        ]
        await status_msg.edit_text(
            analysis,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"解析失败: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ 解析生成失败: {e}")


async def handle_podcast_send(update: Update, context: ContextTypes.DEFAULT_TYPE, book_id: str):
    """向用户发送双人对谈听书音频 (.m4a)"""
    query = update.callback_query
    if query:
        await query.answer("🎧 正在准备听书音频文件...", show_alert=False)

    out_dir = Path(__file__).resolve().parent / "output"
    audio_files = list(out_dir.glob(f"*{book_id}*.m4a")) or list(out_dir.glob("*.m4a"))
    
    target_file = None
    for af in audio_files:
        if book_id in af.name or book_id.lower() in af.name.lower():
            target_file = af
            break
            
    if not target_file and audio_files:
        target_file = audio_files[0]

    if not target_file or not target_file.exists():
        msg_text = "📭 未找到该书籍的高清听书音频文件，请先通过 pipeline 生成。"
        if query:
            await query.message.reply_text(msg_text)
        else:
            await update.message.reply_text(msg_text)
        return

    chat_id = update.effective_chat.id
    if query:
        await query.message.reply_text(f"🎧 正在向您发送《{target_file.stem}》听书音频 (男女声双轨对谈)...")
    else:
        await update.message.reply_text(f"🎧 正在向您发送《{target_file.stem}》听书音频 (男女声双轨对谈)...")

    with open(target_file, "rb") as audio:
        await context.bot.send_audio(
            chat_id=chat_id,
            audio=audio,
            title=target_file.stem.replace("[Podcast]", "").replace("_剧本", "").strip(),
            performer="第二大脑·睿哥 & 小林",
            caption=f"🎧 《{target_file.stem}》\n🎙️ 角色：👨 睿哥（深度分析） & 👩 小林（提问推演）\n💡 高保真 AAC 192k 音质"
        )


async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """内联键盘事件总路由"""
    query = update.callback_query
    data = query.data

    if data == "menu_main":
        await start_command(update, context)
    elif data == "menu_books":
        await show_library_menu(update, context)
    elif data == "menu_usage":
        await show_usage_stats(update, context)
    elif data == "menu_random_quiz":
        await handle_quiz_generation(update, context)
    elif data.startswith("quiz_book_"):
        book_id = data.replace("quiz_book_", "")
        await handle_quiz_generation(update, context, book_id=book_id)
    elif data.startswith("ans_"):
        await handle_quiz_answer(update, context)
    elif data.startswith("podcast_"):
        book_id = data.replace("podcast_", "")
        await handle_podcast_send(update, context, book_id=book_id)
    elif data == "menu_podcasts":
        await show_library_menu(update, context)


def main():
    """启动 Telegram 机器人应用"""
    logger.info("🚀 正在启动第二大脑·AI 智能图书馆 Telegram Bot...")
    
    # 网络代理与超时配置
    req_kwargs = {"read_timeout": 60.0, "write_timeout": 60.0, "connect_timeout": 30.0}
    if PROXY_URL:
        logger.info(f"🌐 启用网络代理: {PROXY_URL}")
        req_kwargs["proxy_url"] = PROXY_URL
        
    request = HTTPXRequest(**req_kwargs)
    app = Application.builder().token(BOT_TOKEN).request(request).build()

    # 注册命令
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("library", show_library_menu))
    app.add_handler(CommandHandler("books", show_library_menu))
    app.add_handler(CommandHandler("status", show_usage_stats))
    app.add_handler(CommandHandler("usage", show_usage_stats))
    app.add_handler(CommandHandler("quiz", lambda u, c: handle_quiz_generation(u, c)))
    
    # 注册回调按键路由
    app.add_handler(CallbackQueryHandler(callback_router))

    logger.info("✅ Telegram Bot 就绪，开始轮询监听...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

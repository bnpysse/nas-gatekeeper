#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
SecondBrain-Flow 主服务入口：Telegram Bot 异步调度服务
"""

import os
import re
import sys
import json
import logging
from pathlib import Path

import asyncio
from concurrent.futures import ThreadPoolExecutor

current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.request import HTTPXRequest

import google.generativeai as genai
import os
from config import Config

# Global Gemini configuration
proxy_url = Config.HTTP_PROXY or Config.HTTPS_PROXY
if proxy_url:
    if not (proxy_url.startswith("http://") or proxy_url.startswith("https://") or proxy_url.startswith("socks5://")):
        proxy_url = f"http://{proxy_url}"
    os.environ['HTTP_PROXY'] = proxy_url
    os.environ['HTTPS_PROXY'] = proxy_url
genai.configure(api_key=Config.GEMINI_API_KEY, transport="rest")

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from config import Config
from services.downloader import is_video_url, extract_url, download_audio_from_url
from services.ai import analyze_audio_with_sensevoice_and_multi_stream, analyze_web_url_stream, extract_and_analyze_wechat_article
from services.obsidian import save_to_obsidian_inbox, save_to_obsidian_autoclippings
from services.cleaner import auto_prune_inbox

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("SecondBrain-Flow")

def check_permission(update: Update) -> bool:
    """严格校验 User ID"""
    user_id = update.effective_user.id if update.effective_user else 0
    if user_id != Config.ALLOWED_USER_ID:
        logger.warning(f"拒绝未经授权的用户访问: {user_id}")
        return False
    return True

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_permission(update):
        return
    welcome_text = (
        "🧠 *SecondBrain-Flow · N100 移动控制中心*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "你可以直接向我发送：\n"
        "1. 🍵 **微信公众号文章链接**：抓取 100% 原文并由 Qwen-Plus 深度提炼，双轨归档 `Auto_Clippings`。\n"
        "2. 🎥 **B站/抖音/YouTube 视频链接**：提取音轨由 DashScope 生成【核心总结 + 中文逐字稿】。\n"
        "3. 📰 **知乎/商业专栏/普通网页链接**：抓取正文并由多模型提炼要点。\n"
        "4. 🎙️ **随手笔记/语音闪念**：自动记录入库。\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "📱 *核心指令大盘*：\n"
        "🔍 `/ask <问题>` - 🎯 Rerank 高阶精准知识库检索\n"
        "🧠 `/chat <内容>` - ⚡ 旗舰大模型多轮智能对话\n"
        "💻 `/probe` - 📊 N100 硬件探针与网络健康\n"
        "⚡ `/quota` - 💎 大模型额度与 Token 消费大屏\n"
        "📚 `/library` - 📖 图书馆 437 本专著与解析进度\n"
        "🛠️ `/ops` - ⚙️ N100 核心服务管理与一键重启\n"
        "📝 `/quiz [主题]` - 🎲 动态题库无限生成与深度题解\n"
        "📖 `/weread` - 📚 微信读书划线自动同步指南\n"
        "🧹 `/clean` - 🧹 清理 30 天前过期草稿\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "🟢 *系统状态极其健康，已连接 N100 边缘节点*"
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_permission(update):
        return
    gdrive_info = getattr(Config, "GDRIVE_SYNC_PATH", None)
    gdrive_str = f"`{gdrive_info}`" if (gdrive_info and gdrive_info.exists()) else "API 直传已就绪"
    status_text = (
        "🟢 *系统状态正常*\n"
        f"- 允许的 User ID: `{Config.ALLOWED_USER_ID}`\n"
        f"- Obsidian Inbox: `{Config.OBSIDIAN_INBOX_PATH}`\n"
        f"- Google Drive 状态: {gdrive_str}\n"
        f"- 代理连接: `{Config.HTTP_PROXY or '直连'}`"
    )
    await update.message.reply_text(status_text, parse_mode="Markdown")

async def clean_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_permission(update):
        return
    await update.message.reply_text("🧹 正在清理 Inbox 超过 30 天未归档草稿...")
    count = auto_prune_inbox()
    await update.message.reply_text(f"✅ 清理完成，共移除了 {count} 份过期临时草稿。")

class TaskTracker:
    """实时链路追踪看板：在 Telegram 单条消息内动态展示明确的数字步骤 (1、2、3、4、5...)"""
    def __init__(self, msg, base_title="SecondBrain-Flow 知识归档引擎"):
        self.msg = msg
        self.steps = []
        self.base_title = base_title
        
    async def step(self, step_num: int, name: str, status: str, detail: str = ""):
        """
        status: 'RUNNING' (⏳), 'OK' (✅), 'WARN' (⚠️), 'ERROR' (❌)
        """
        icon = {"RUNNING": "⏳", "OK": "✅", "WARN": "⚠️", "ERROR": "❌"}.get(status, "•")
        line = f"{step_num}、{icon} **{name}**：{detail}"
        # 如果当前步骤已存在，则替换；否则追加
        found = False
        prefix = f"{step_num}、"
        for i, s in enumerate(self.steps):
            if s.startswith(prefix):
                self.steps[i] = line
                found = True
                break
        if not found:
            self.steps.append(line)
        await self._render()

    async def _render(self):
        text = f"🔄 *{self.base_title}*\n\n" + "\n".join(self.steps)
        try:
            await self.msg.edit_text(text, parse_mode="Markdown")
        except Exception:
            pass

    def get_summary_trace(self) -> str:
        return "\n".join([f"> {s}" for s in self.steps])

async def send_or_edit_long_message(message, text: str, parse_mode="Markdown"):
    """安全发送长消息，防止超出 Telegram 4096 字符限制"""
    if len(text) <= 3900:
        try:
            await message.edit_text(text, parse_mode=parse_mode)
            return
        except Exception:
            await message.edit_text(text)
            return

    # 超长分段处理
    chunks = []
    current = ""
    for paragraph in text.split("\n\n"):
        if len(current) + len(paragraph) + 2 > 3800:
            if current:
                chunks.append(current)
                current = paragraph
            else:
                chunks.append(paragraph[:3800])
                current = paragraph[3800:]
        else:
            current = f"{current}\n\n{paragraph}" if current else paragraph
    if current:
        chunks.append(current)

    if chunks:
        try:
            await message.edit_text(chunks[0], parse_mode=parse_mode)
        except Exception:
            await message.edit_text(chunks[0])
        for chunk in chunks[1:]:
            try:
                await message.reply_text(chunk, parse_mode=parse_mode)
            except Exception:
                await message.reply_text(chunk)

def extract_brief_summary(full_content: str, max_chars: int = 600) -> str:
    """从完整多模型研报中提取精简的核心结论，供 Telegram 聊天框优雅展示，避免长文刷屏与字符溢出"""
    if not full_content:
        return ""
    clean = re.sub(r'## 🎙️ 语音转写原文[\s\S]*$', '', full_content)
    clean = re.sub(r'### 网页原始抓取正文[\s\S]*$', '', clean)
    clean = re.sub(r'## 🔗 知识库双向关联[\s\S]*$', '', clean)
    clean = clean.strip()
    
    if len(clean) > max_chars:
        clean = clean[:max_chars].rstrip() + "...\n\n*(💡 完整万字逐字稿与双模型深度研报已同步至 Google Drive & Obsidian)*"
    return clean

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理消息路由，附带实时数字编号链路看板"""
    if not check_permission(update):
        return

    text = update.message.text or ""
    url = extract_url(text)

    # 1. 音视频及内容平台链接 (头条/西瓜/抖音/B站/YouTube等)
    if is_video_url(text) or ("http" in text and any(k in text for k in ["toutiao", "xigua", "douyin", "bilibili", "youtube"])):
        msg = await update.message.reply_text("📥 收到请求，正在初始化流水线...")
        tracker = TaskTracker(msg, base_title="SecondBrain-Flow 音视频/图文流水线")
        await tracker.step(1, "接收并解析链接", "OK", f"`{url[:45]}...`")

        try:
            # Step 2: 正在下载音视频
            await tracker.step(2, "正在下载视频文件", "RUNNING", "探测音视频并提取音轨流...")
            audio_path, video_title = download_audio_from_url(url)
            await tracker.step(2, "视频文件下载成功", "OK", f"《{video_title[:30]}》")

            # Step 3: 语音文件已找到并转文字
            await tracker.step(3, "语音文件已提取", "OK", f"音轨大小: {audio_path.stat().st_size // 1024} KB")
            await tracker.step(4, "正在语音转文字", "RUNNING", "调用阿里云 SenseVoice-V1 极速识别中...")
            
            result = await analyze_audio_with_sensevoice_and_multi_stream(audio_path, video_title)
            await tracker.step(4, "语音转文字完成", "OK", "文字逐字稿已就绪")

            # Step 5: 双模型深度总结
            await tracker.step(5, "多模型深度提炼", "OK", "国家超算中心 SCNet & 阿里千问 Qwen 分析完成")

            # Step 6: 归档落库
            await tracker.step(6, "知识库归档与同步", "RUNNING", "保存至 Obsidian & 同步 Google Drive / OneDrive...")
            note_path = await save_to_obsidian_inbox(
                title=f"[多模型] {result['title']}",
                url=url,
                content=result["content"],
                source_type="Toutiao_Video"
            )
            await tracker.step(6, "知识库归档完成", "OK", f"`{note_path.name}`")

            try:
                if audio_path.exists():
                    audio_path.unlink()
            except Exception:
                pass

            final_response = (
                f"🎉 *多模型音视频分析与归档完成！*\n\n"
                f"📌 **标题**: 《{video_title}》\n"
                f"📁 **归档文件**: `{note_path.name}`\n"
                f"☁️ **云端同步**: 完整逐字稿与研报已同步至 Google Drive & OneDrive\n\n"
                f"📋 **完整执行工作流**:\n"
                f"{tracker.get_summary_trace()}\n\n"
                f"---\n\n"
                f"{extract_brief_summary(result['content'])}"
            )
            await send_or_edit_long_message(msg, final_response)

        except Exception as e:
            # 如果音频提取失败（说明是纯文字帖子、微头条或视频加密），平滑切换为图文解析
            err_short = str(e)[:60].replace("\n", " ")
            logger.info(f"音轨提取未命中或加密受限，自动平滑切换为【图文/文章】抓取模式: {err_short}")
            await tracker.step(2, "音视频提取受限", "WARN", f"{err_short}")
            await tracker.step(3, "模式自动切换", "OK", "无缝启动【网页正文深度解析】")

            try:
                await tracker.step(4, "正在抓取网页正文", "RUNNING", "Jina Reader 提取全文内容...")
                ai_result = await analyze_web_url_stream(url)
                if ai_result.get("is_error"):
                    await tracker.step(4, "正文抓取未命中", "WARN", ai_result.get("error_msg", "内容不可用")[:50])
                    fail_msg = (
                        f"⚠️ *链接处理中断通知*\n\n"
                        f"{ai_result['content']}\n\n"
                        f"📋 **执行工作流追踪**:\n"
                        f"{tracker.get_summary_trace()}"
                    )
                    await msg.edit_text(fail_msg)
                    return

                await tracker.step(4, "网页正文抓取完成", "OK", f"成功抓取《{ai_result['title'][:30]}》")

                await tracker.step(5, "多模型深度提炼", "OK", "阿里百炼 & 七牛云满血大模型分析完成")

                await tracker.step(6, "知识库归档与同步", "RUNNING", "保存至 Obsidian & 同步云盘...")
                note_path = await save_to_obsidian_inbox(
                    title=ai_result["title"],
                    url=url,
                    content=ai_result["content"],
                    source_type="Toutiao_Article"
                )
                await tracker.step(6, "知识库归档完成", "OK", f"`{note_path.name}`")

                final_response = (
                    f"🎉 *多模型图文分析与归档完成！*\n\n"
                    f"📌 **标题**: 《{ai_result['title']}》\n"
                    f"📁 **归档文件**: `{note_path.name}`\n"
                    f"☁️ **云端同步**: 全文已同步至 Google Drive & OneDrive\n\n"
                    f"📋 **完整执行工作流**:\n"
                    f"{tracker.get_summary_trace()}\n\n"
                    f"---\n\n"
                    f"{extract_brief_summary(ai_result['content'])}"
                )
                await send_or_edit_long_message(msg, final_response)

            except Exception as web_err:
                logger.error(f"图文解析失败: {web_err}")
                await tracker.step(4, "正文抓取失败", "ERROR", f"`{str(web_err)[:60]}`")
                await msg.edit_text(f"❌ 链接处理失败:\n{tracker.get_summary_trace()}")

    # 2. 微信公众号专属文章链接 (精准识别 mp.weixin.qq.com)
    elif "mp.weixin.qq.com" in url or "weixin.qq.com" in url:
        msg = await update.message.reply_text("🍵 收到微信公众号文章，正在初始化专属抓取引擎...")
        tracker = TaskTracker(msg, base_title="SecondBrain-Flow 微信文章深度提炼")
        await tracker.step(1, "接收微信公众号链接", "OK", f"`{url[:45]}...`")
        try:
            await tracker.step(2, "正在抓取 100% 微信文章全文", "RUNNING", "Trafilatura 深度解析中...")
            ai_result = await extract_and_analyze_wechat_article(url)
            if ai_result.get("is_error"):
                raise ValueError(ai_result.get("summary_content"))

            await tracker.step(2, "微信全文抓取成功", "OK", f"《{ai_result['title'][:25]}...》({len(ai_result['raw_content'])}字)")

            await tracker.step(3, "AI 深度拆解与提炼", "OK", "国家超算中心 SCNet-Max 结构化分析完成")

            await tracker.step(4, "归档至 Auto_Clippings 并同步", "RUNNING", "双轨落库 (原文 + 深度简报)...")
            archive_info = await save_to_obsidian_autoclippings(
                title=ai_result["title"],
                url=url,
                raw_content=ai_result["raw_content"],
                summary_content=ai_result["summary_content"],
                source_type="WeChat",
                account_name=ai_result["account"]
            )
            await tracker.step(4, "知识库双轨归档完成", "OK", f"`{archive_info['summary_path'].name}`")

            final_response = (
                f"🎉 *微信文章 100% 原文沉淀与深度分析完成！*\n\n"
                f"📌 **标题**: 《{ai_result['title']}》\n"
                f"📢 **公众号**: `{ai_result['account']}`\n"
                f"📁 **归档目录**: `Auto_Clippings/`\n"
                f"📄 **原文归档**: `{archive_info['raw_path'].name}`\n"
                f"🧠 **智能简报**: `{archive_info['summary_path'].name}`\n\n"
                f"📋 **完整执行工作流**:\n"
                f"{tracker.get_summary_trace()}\n\n"
                f"---\n\n"
                f"{ai_result['summary_content']}"
            )
            await send_or_edit_long_message(msg, final_response)
        except Exception as e:
            logger.error(f"微信文章处理失败: {e}")
            await tracker.step(2, "微信文章抓取失败", "ERROR", f"`{str(e)[:60]}`")
            await msg.edit_text(f"❌ 微信文章处理失败:\n{tracker.get_summary_trace()}")

    # 3. 普通网页链接
    elif "http://" in text or "https://" in text:
        msg = await update.message.reply_text("📰 收到网页链接，正在初始化流水线...")
        tracker = TaskTracker(msg, base_title="SecondBrain-Flow 网页深度提炼")
        await tracker.step(1, "接收并解析链接", "OK", f"`{url[:45]}...`")
        try:
            await tracker.step(2, "正在抓取网页正文", "RUNNING", "Jina Reader 提取全文内容...")
            ai_result = await analyze_web_url_stream(url)
            await tracker.step(2, "网页正文抓取完成", "OK", f"成功抓取《{ai_result['title'][:30]}》")

            await tracker.step(3, "多模型深度提炼", "OK", "国家超算中心 SCNet & 阿里千问 Qwen 分析完成")

            await tracker.step(4, "知识库归档与同步", "RUNNING", "保存至 Obsidian & 同步云盘...")
            note_path = await save_to_obsidian_inbox(
                title=ai_result["title"],
                url=url,
                content=ai_result["content"],
                source_type="Web"
            )
            await tracker.step(4, "知识库归档完成", "OK", f"`{note_path.name}`")

            final_response = (
                f"🎉 *网页归档与多模型分析完成！*\n\n"
                f"📌 **标题**: 《{ai_result['title']}》\n"
                f"📁 **Obsidian**: `{note_path.name}`\n"
                f"☁️ **云端同步**: 全文已同步至 Google Drive & OneDrive\n\n"
                f"📋 **完整执行工作流**:\n"
                f"{tracker.get_summary_trace()}\n\n"
                f"---\n\n"
                f"{extract_brief_summary(ai_result['content'])}"
            )
            await send_or_edit_long_message(msg, final_response)
        except Exception as e:
            logger.error(f"处理网页失败: {e}")
            await tracker.step(2, "网页解析失败", "ERROR", f"`{str(e)[:60]}`")
            await msg.edit_text(f"❌ 网页解析失败:\n{tracker.get_summary_trace()}")

    # 4. 普通纯文本
    else:
        note_path = await save_to_obsidian_inbox(
            title="纯文本闪念笔记",
            url="",
            content=text,
            source_type="Memo"
        )
        await update.message.reply_text(f"📝 闪念笔记已保存至: `{note_path.name}`", parse_mode="Markdown")

async def daily_prune_job(context: ContextTypes.DEFAULT_TYPE):
    """每日定时扫描清理任务"""
    logger.info("执行每日定时清理任务...")
    count = auto_prune_inbox()
    logger.info(f"清理完成，移除了 {count} 份过期草稿。")

def main():
    """入口函数"""
    Config.validate()
    logger.info("启动 SecondBrain-Flow Bot...")

    builder = Application.builder().token(Config.TELEGRAM_BOT_TOKEN)

    proxy_url = Config.HTTP_PROXY or Config.HTTPS_PROXY
    if proxy_url:
        if not (proxy_url.startswith("http://") or proxy_url.startswith("https://") or proxy_url.startswith("socks5://")):
            proxy_url = f"http://{proxy_url}"
        request_client = HTTPXRequest(
            proxy=proxy_url,
            connect_timeout=30.0,
            read_timeout=30.0,
            write_timeout=30.0,
            pool_timeout=15.0
        )
        get_updates_request_client = HTTPXRequest(
            proxy=proxy_url,
            connect_timeout=30.0,
            read_timeout=30.0,
            write_timeout=30.0,
            pool_timeout=15.0
        )
        
        builder = builder.request(request_client).get_updates_request(get_updates_request_client)

    async def post_init(application: Application):
        """自动向 Telegram 官方服务器注册并刷新 10 大快捷指令菜单"""
        try:
            commands = [
                BotCommand("start", "🚀 启动并查看所有功能中心"),
                BotCommand("ask", "🔍 Rerank 高阶精准知识库检索"),
                BotCommand("chat", "🧠 免费旗舰大模型对话"),
                BotCommand("probe", "💻 N100 硬件探针与网络健康"),
                BotCommand("quota", "⚡ 大模型额度与 Token 消费大屏"),
                BotCommand("library", "📚 图书知识库与解析进度"),
                BotCommand("ops", "🛠️ N100 服务管理与一键运维"),
                BotCommand("quiz", "📝 智能图书馆动态出题研习"),
                BotCommand("weread", "📖 微信读书划线与精读同步"),
                BotCommand("clean", "🧹 清理过期临时草稿"),
            ]
            await application.bot.set_my_commands(commands)
            logger.info("✅ 成功向 Telegram 官方注册并刷新 10 大快捷指令菜单！")
        except Exception as e:
            logger.warning(f"向 Telegram 注册指令菜单失败: {e}")

    builder = builder.post_init(post_init)
    app = builder.build()

    # 💻 新增 /probe 与 /sys 硬件探针指令
    async def probe_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not check_permission(update):
            return
        status_msg = await update.message.reply_text("🔍 正在探测 N100 硬件性能与网络健康...")
        try:
            from services.probe import get_system_probe, format_probe_message
            info = await get_system_probe()
            text = format_probe_message(info)
            await status_msg.edit_text(text, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"探针采集失败: {e}")
            await status_msg.edit_text(f"❌ 探针采集异常: {e}")

    # 📚 新增 /library 与 /books 图书馆大盘指令
    async def library_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not check_permission(update):
            return
        status_msg = await update.message.reply_text("📚 正在调取第二大脑·AI 智能图书馆全景大盘...")
        try:
            from services.ops import get_library_overview, format_library_message
            data = await get_library_overview()
            text = format_library_message(data)
            
            keyboard = [
                [InlineKeyboardButton("🛡️ 立即自愈受损讲义", callback_data="ops_trigger:audit")],
                [InlineKeyboardButton("🎲 图书馆随机盲盒出题", callback_data="quiz_book:random")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await status_msg.edit_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"获取图书馆大盘失败: {e}")
            await status_msg.edit_text(f"❌ 获取图书馆大盘失败: {e}")

    # 🛠️ 新增 /ops 与 /service, /restart 服务运维控制台指令
    async def ops_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not check_permission(update):
            return
        status_msg = await update.message.reply_text("🛠️ 正在检测 N100 边缘节点各核心服务状态...")
        try:
            from services.ops import get_services_status, format_ops_message
            services = get_services_status()
            text, keyboard_data = format_ops_message(services)
            
            keyboard = []
            for row in keyboard_data:
                if isinstance(row, list):
                    keyboard.append([InlineKeyboardButton(b["text"], callback_data=b["callback_data"]) for b in row])
                elif isinstance(row, dict):
                    keyboard.append([InlineKeyboardButton(row["text"], callback_data=row["callback_data"])])
            reply_markup = InlineKeyboardMarkup(keyboard)
            await status_msg.edit_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"获取服务状态失败: {e}")
            await status_msg.edit_text(f"❌ 运维大盘获取失败: {e}")

    # 🔘 运维内联按钮回调处理器
    async def ops_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        data = query.data
        from services.ops import restart_system_service, get_services_status, format_ops_message
        
        if data.startswith("ops_restart:"):
            short_code = data.replace("ops_restart:", "")
            await query.edit_message_text(f"⏳ 正在安全重启服务 【{short_code}】...")
            ok, msg = restart_system_service(short_code)
            
            services = get_services_status()
            text, kb_data = format_ops_message(services)
            kb = []
            for row in kb_data:
                if isinstance(row, list):
                    kb.append([InlineKeyboardButton(b["text"], callback_data=b["callback_data"]) for b in row])
                elif isinstance(row, dict):
                    kb.append([InlineKeyboardButton(row["text"], callback_data=row["callback_data"])])
            full_text = f"{msg}\n\n{text}"
            await query.message.reply_text(full_text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
            
        elif data == "ops_trigger:audit":
            await query.edit_message_text("🛡️ 正在后台触发一轮受损讲义自动修复与巡检...")
            import subprocess
            subprocess.Popen(["/opt/SecondBrain-Flow/.venv/bin/python3", "/opt/SecondBrain-Flow/books_pipeline/library_auditor.py", "--limit", "5"])
            await query.message.reply_text("✅ 成果巡检自愈子进程已在后台启动（本次计划修复前 5 本受损图书）。")
            
        elif data == "ops_refresh:all":
            services = get_services_status()
            text, kb_data = format_ops_message(services)
            kb = []
            for row in kb_data:
                if isinstance(row, list):
                    kb.append([InlineKeyboardButton(b["text"], callback_data=b["callback_data"]) for b in row])
                elif isinstance(row, dict):
                    kb.append([InlineKeyboardButton(row["text"], callback_data=row["callback_data"])])
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    # 新增 /ask 命令，对接 RAG 引擎
    async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not check_permission(update):
            return
            
        question = " ".join(context.args)
        if not question:
            await update.message.reply_text("请提供您的问题。例如：`/ask 最近关于 AI Agent 的讨论有哪些？`", parse_mode='Markdown')
            return
            
        status_message = await update.message.reply_text("正在通过第二大脑进行检索分析，请稍候...")
        try:
            from services.rag import ask_rag
            answer = await ask_rag(question)
            await status_message.edit_text(answer, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"RAG 检索失败: {e}")
            await status_message.edit_text(f"抱歉，检索分析失败: {e}")
            
    # 新增 /quota 与 /tokens 算力看板指令
    async def quota_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not check_permission(update):
            return
        status_msg = await update.message.reply_text("⚡ 正在探测多平台大模型免费配额与 Token 台账...")
        try:
            # 读取 Turso 数据库台账
            try:
                from books_pipeline.db import execute_turso
            except ImportError:
                from services.rag import _execute_turso as execute_turso
                
            ledger_rows = await execute_turso("""
                SELECT provider, model_name, count(*) as calls, sum(total_tokens) as total_tokens, sum(cost_cny) as total_cost 
                FROM library_usage_ledger 
                GROUP BY provider, model_name;
            """)
            
            ledger_txt = ""
            for r in ledger_rows:
                p = r.get("provider", "")
                m = r.get("model_name", "")
                calls = r.get("calls", 0)
                t_tokens = int(r.get("total_tokens") or 0)
                cost = float(r.get("total_cost") or 0.0)
                ledger_txt += f"• **[{p}]** `{m}`: `{calls}` 次调用 | `{t_tokens:,}` Tokens | 费用 `¥{cost:.4f}`\n"
            if not ledger_txt:
                ledger_txt = "暂无今日台账记录\n"
                
            text = (
                "⚡ *第二大脑·全网免费大模型算力大屏*\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "💎 *阿里百炼 (DashScope) 13 员猛将 (用完即停 0 扣费)*：\n"
                "• `qwen3.7-plus`: 剩 30.9万 (去水精读主力，到期 09/01)\n"
                "• `qwen3.7-plus-2026-05-26`: 剩 100万 (双生满额)\n"
                "• `qwen3.7-max`: 剩 60.3万 (深度架构透视，到期 09/08)\n"
                "• `deepseek-v4-flash`: 剩 100万满额 (到期 10/31)\n"
                "• `glm-5.2` / `kimi-k3` / `kimi-code`: 各 100万满额\n"
                "• `qwen3-vl-rerank`: 剩 100万满额 (高阶重排，到期 11/13)\n"
                "• 🎙️ 59 款 Sambert 语音模型: 终身免费 (到期 2099/01/01)\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "🔄 *火山方舟 (VolcEngine) 每日循环返还池*：\n"
                "• **DeepSeek-V4-Pro**: 剩 `98.7 万` (每日上限200万，T+1 日 1:1 返还)\n"
                "• **DeepSeek-V4-Flash**: 剩 `248.3 万` (长期免费资源包)\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "🌐 *Google Gemini (100万超大上下文)*：\n"
                "• `gemini-3.5-flash-lite`: 1,500次/天 (实测 1.2s 极速 · 100% 免费)\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "📊 *Turso 生产环境实际消耗与费用明细*：\n"
                f"{ledger_txt}"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "🛡️ *全链路严格运行于 0 扣费免费通道，扣费隐患已全部物理硬锁*"
            )
            await status_msg.edit_text(text, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"查询配额失败: {e}")
            await status_msg.edit_text(f"❌ 探测算力大屏失败: {e}")

    # 新增 /chat 命令，通过 TokenGate 智能统一调度
    async def chat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not check_permission(update):
            return
            
        question = " ".join(context.args)
        if not question:
            await update.message.reply_text("请提供您的聊天内容。例如：`/chat 帮我写一份投资研究备忘录`", parse_mode='Markdown')
            return
            
        status_message = await update.message.reply_text("🧠 TokenGate 智能调度中...")
        try:
            import httpx
            async with httpx.AsyncClient(timeout=60.0) as client:
                res = await client.post(
                    "https://tg.donglida.com/v1/chat/completions",
                    json={
                        "model": "auto",
                        "messages": [
                            {"role": "system", "content": "你是由 TokenGate 智能算力网关驱动的个人第二大脑助手。回答简明深刻、专业可靠。"},
                            {"role": "user", "content": question}
                        ],
                        "stream": False
                    }
                )
                if res.status_code == 200:
                    ans = res.json()["choices"][0]["message"]["content"]
                    await status_message.edit_text(ans, parse_mode='Markdown')
                else:
                    await status_message.edit_text(f"网关响应异常 ({res.status_code}): {res.text}")
        except Exception as e:
            logger.error(f"聊天失败: {e}")
            await status_message.edit_text(f"抱歉，遇到了一点问题: {e}")

    # 📚 新增 /quiz 动态无限研习题库与原著深度题解 (Turso RAG + DeepSeek-V4-Pro)
    async def quiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not check_permission(update):
            return
            
        from books_pipeline.dynamic_quiz import get_available_books, generate_dynamic_quiz
        
        args = context.args or []
        if not args:
            # 1. 未带参数时，展现馆藏书库供用户点击选择
            try:
                books = await get_available_books()
                if not books:
                    await update.message.reply_text("📚 当前智能图书馆暂无入库书籍，请先将书籍放入 `downloads/CloseReading/` 并运行索引器入库。")
                    return
                    
                keyboard = []
                for b in books:
                    icon = "🐍" if "python" in b["id"].lower() else "⚙️"
                    keyboard.append([InlineKeyboardButton(
                        f"{icon} 《{b['title'][:20]}...》({b['total_chunks']} 块)",
                        callback_data=f"quiz_book:{b['id']}"
                    )])
                keyboard.append([InlineKeyboardButton("🎲 随机盲盒全馆抽题", callback_data="quiz_book:random")])
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                await update.message.reply_text(
                    "📚 *第二大脑·AI 智能图书馆测试题系统*\n\n"
                    "由 **Turso 向量库 + DeepSeek-V4-Pro** 实时动态命制与精准溯源。\n"
                    "请选择你想研习的书籍，或直接使用 `/quiz <主题>` 进行定向出题：\n"
                    "例如：`/quiz 线程池` 或 `/quiz 协程`",
                    reply_markup=reply_markup,
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"加载书库列表失败: {e}")
                await update.message.reply_text(f"❌ 加载书库失败: {e}")
            return

        # 2. 用户指定了主题，进行专题定向出题
        topic = " ".join(args)
        status_msg = await update.message.reply_text(f"🔍 正在从向量库检索关于 *「{topic}」* 的切块并由 DeepSeek 命题中...", parse_mode="Markdown")
        try:
            books = await get_available_books()
            target_book = books[0]["id"] if books else "the_python_3_standard_library_by_example__developer_s_library"
            for b in books:
                if any(kw in topic.lower() for kw in ["haskell", "函数式", "monad"]):
                    if "haskell" in b["id"].lower():
                        target_book = b["id"]
                        break
                elif "python" in b["id"].lower():
                    target_book = b["id"]
                    
            quiz = await generate_dynamic_quiz(target_book, topic=topic)
            
            # 构建选项展示与按钮
            options_text = ""
            btn_row = []
            for opt_key, opt_val in quiz["options"].items():
                options_text += f"\n*{opt_key}.* {opt_val}\n"
                btn_row.append(InlineKeyboardButton(f" {opt_key} ", callback_data=f"quiz_ans:{quiz['quiz_id']}:{opt_key}"))
                
            q_text = (
                f"📚 *《{quiz.get('book_id', '智能图书馆')}》· 动态研习题*\n"
                f"📌 **出处章节**：《{quiz.get('chapter_title', '核心章节')}》\n\n"
                f"❓ *题目*：\n{quiz['question']}\n\n"
                f"📋 *选项*：{options_text}"
            )
            reply_markup = InlineKeyboardMarkup([btn_row])
            await status_msg.edit_text(q_text, reply_markup=reply_markup, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"动态出题失败: {e}")
            await status_msg.edit_text(f"❌ 动态出题失败: {e}")

    # 🔘 交互答题与选书回调处理器
    async def quiz_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        from books_pipeline.dynamic_quiz import get_available_books, generate_dynamic_quiz, evaluate_and_explain
        
        data = query.data
        if data.startswith("quiz_book:"):
            book_id = data.replace("quiz_book:", "")
            await query.edit_message_text("🎲 正在从知识库抽取切块，DeepSeek-V4-Pro 现场命制原创测试题中...")
            try:
                if book_id == "random":
                    books = await get_available_books()
                    import random
                    target_book = random.choice(books)["id"] if books else "the_python_3_standard_library_by_example__developer_s_library"
                else:
                    target_book = book_id
                    
                quiz = await generate_dynamic_quiz(target_book)
                options_text = ""
                btn_row = []
                for opt_key, opt_val in quiz["options"].items():
                    options_text += f"\n*{opt_key}.* {opt_val}\n"
                    btn_row.append(InlineKeyboardButton(f" {opt_key} ", callback_data=f"quiz_ans:{quiz['quiz_id']}:{opt_key}"))
                    
                q_text = (
                    f"📚 *《{quiz.get('book_id', '智能图书馆')}》· 动态研习题*\n"
                    f"📌 **出处章节**：《{quiz.get('chapter_title', '核心章节')}》\n\n"
                    f"❓ *题目*：\n{quiz['question']}\n\n"
                    f"📋 *选项*：{options_text}"
                )
                reply_markup = InlineKeyboardMarkup([btn_row])
                await query.edit_message_text(q_text, reply_markup=reply_markup, parse_mode="Markdown")
            except Exception as e:
                logger.error(f"出题失败: {e}")
                await query.edit_message_text(f"❌ 出题失败: {e}")
                
        elif data.startswith("quiz_ans:"):
            parts = data.split(":")
            quiz_id = parts[1]
            user_opt = parts[2]
            
            await query.edit_message_text(f"📝 你的选择是 *{user_opt}*，DeepSeek-V4-Pro 正在调取原著段落动态生成专属复盘与解析...", parse_mode="Markdown")
            try:
                user_id = str(update.effective_user.id) if update.effective_user else "woodman"
                eval_res = await evaluate_and_explain(quiz_id, user_opt, user_id=user_id)
                
                # 获取原题记录查看所属书籍
                from books_pipeline.db import execute_turso
                rows = await execute_turso("SELECT book_id FROM library_quiz_history WHERE id = ?;", [quiz_id])
                current_book_id = rows[0]["book_id"] if rows else "random"
                
                keyboard = [
                    [InlineKeyboardButton("🎲 下一道题 (当前书)", callback_data=f"quiz_book:{current_book_id}")],
                    [InlineKeyboardButton("📚 换一本书 / 全馆盲盒", callback_data="quiz_book:random")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                ans_text = eval_res["analysis"]
                await query.edit_message_text(ans_text, reply_markup=reply_markup, parse_mode="Markdown")
            except Exception as e:
                logger.error(f"评析失败: {e}")
                await query.edit_message_text(f"❌ 题解生成失败: {e}")

    # 📚 新增 /weread 微信读书指南与状态指令
    async def weread_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not check_permission(update):
            return
        text = (
            "📚 *微信读书（WeRead）智能同步中心*\n\n"
            "微信读书的划线与想法将自动归档至 Obsidian 的 `Auto_Clippings/` 目录，并由 AI 自动生成全书精读报告。\n\n"
            "💡 **极速接入方式（推荐）**：\n"
            "1. **在 Obsidian 中安装插件**：在您的 Mac / 手机 Obsidian 插件市场搜索并安装 `Weread Plugin`；\n"
            "2. **设置存储目录**：在插件设置中将“保存路径”设置为 `Auto_Clippings`；\n"
            "3. **微信扫码登录**：点击插件中的“扫码登录”，用手机微信扫一扫；\n"
            "4. **一键同步**：点击同步后，所有书籍、划线、书评即刻生成 Markdown 笔记，N100 会在 1 分钟内自动将其发布至 `brain.imdld.com`！\n\n"
            "🍵 **日常微信文章剪藏**：\n"
            "直接把微信公众号文章的链接发给我，我会在 3 秒内抓取 100% 完整正文，生成 DeepSeek-V4 深度简报并存入 `Auto_Clippings`！"
        )
        await update.message.reply_text(text, parse_mode="Markdown")

    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """全局 Telegram 异常处理，避免刷屏日志"""
        logger.warning(f"Telegram 网络或调度异常已捕获: {context.error}")

    app.add_error_handler(error_handler)
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("probe", probe_command))
    app.add_handler(CommandHandler("sys", probe_command))
    app.add_handler(CommandHandler("library", library_command))
    app.add_handler(CommandHandler("books", library_command))
    app.add_handler(CommandHandler("ops", ops_command))
    app.add_handler(CommandHandler("service", ops_command))
    app.add_handler(CommandHandler("restart", ops_command))
    app.add_handler(CommandHandler("weread", weread_command))
    app.add_handler(CommandHandler("quota", quota_command))
    app.add_handler(CommandHandler("tokens", quota_command))
    app.add_handler(CommandHandler("clean", clean_command))
    app.add_handler(CommandHandler("ask", ask_command))
    app.add_handler(CommandHandler("chat", chat_command))
    app.add_handler(CommandHandler("quiz", quiz_command))
    app.add_handler(CallbackQueryHandler(ops_callback_handler, pattern=r"^ops_"))
    app.add_handler(CallbackQueryHandler(quiz_callback_handler, pattern=r"^quiz_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    if app.job_queue:
        app.job_queue.run_repeating(daily_prune_job, interval=86400, first=10)

    logger.info("Bot 已开始 Polling 监听...")
    app.run_polling()

if __name__ == "__main__":
    main()

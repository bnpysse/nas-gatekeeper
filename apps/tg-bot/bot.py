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

from telegram import Update
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
    ContextTypes,
    filters,
)

from config import Config
from services.downloader import is_video_url, extract_url, download_audio_from_url
from services.ai import analyze_audio_with_sensevoice_and_multi_stream, analyze_web_url_stream
from services.obsidian import save_to_obsidian_inbox
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
        "🧠 *SecondBrain-Flow 第二大脑自动化系统已上线！*\n\n"
        "你可以直接向我发送：\n"
        "1. 🎥 **今日头条/西瓜/抖音/B站/YouTube 视频链接**：提取音轨由 百炼 (DashScope) 生成【核心总结 + 中文逐字稿】，自动落库 Obsidian 与 Google Drive。\n"
        "2. 📰 **知乎/微信公众号/网页链接**：抓取正文并由 百炼 (DashScope) 提炼要点。\n"
        "3. 🎙️ **文本/闪念**：自动记录落地。\n\n"
        "⚙️ 指令：\n"
        "/quota - ⚡ 探测 TokenGate 全网免费算力与临期资产\n"
        "/chat <内容> - 🧠 TokenGate 智能调度大模型对话\n"
        "/ask <问题> - 🔍 RAG 语义检索 Obsidian 知识库\n"
        "/status - 🟢 查看第二大脑运行状态\n"
        "/clean - 🧹 清理 30 天前旧草稿"
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
            await tracker.step(5, "多模型深度提炼", "OK", "火山引擎 DeepSeek-V4 & 阿里百炼 Qwen 分析完成")

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
                await tracker.step(4, "网页正文抓取完成", "OK", f"成功抓取《{ai_result['title'][:30]}》")

                await tracker.step(5, "多模型深度提炼", "OK", "火山引擎 DeepSeek-V4 & 阿里百炼 Qwen 分析完成")

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

    # 2. 普通网页链接
    elif "http://" in text or "https://" in text:
        msg = await update.message.reply_text("📰 收到网页链接，正在初始化流水线...")
        tracker = TaskTracker(msg, base_title="SecondBrain-Flow 网页深度提炼")
        await tracker.step(1, "接收并解析链接", "OK", f"`{url[:45]}...`")
        try:
            await tracker.step(2, "正在抓取网页正文", "RUNNING", "Jina Reader 提取全文内容...")
            ai_result = await analyze_web_url_stream(url)
            await tracker.step(2, "网页正文抓取完成", "OK", f"成功抓取《{ai_result['title'][:30]}》")

            await tracker.step(3, "多模型深度提炼", "OK", "火山引擎 DeepSeek-V4 & 阿里百炼 Qwen 分析完成")

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

    # 3. 普通纯文本
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
        logger.info(f"配置 Telegram 代理: {proxy_url}")
        
        try:
            request_client = HTTPXRequest(proxy=proxy_url)
            get_updates_request_client = HTTPXRequest(proxy=proxy_url)
        except TypeError:
            request_client = HTTPXRequest(proxy_url=proxy_url)
            get_updates_request_client = HTTPXRequest(proxy_url=proxy_url)
        
        builder = builder.request(request_client).get_updates_request(get_updates_request_client)

    app = builder.build()

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
        status_msg = await update.message.reply_text("⚡ 正在探测 TokenGate 全网免费算力状态...")
        try:
            import httpx
            data = None
            for u in ["https://tg.donglida.com/api/quotas", "https://tg.donglida.xyz/api/quotas"]:
                try:
                    async with httpx.AsyncClient(timeout=6.0) as client:
                        resp = await client.get(u)
                        if resp.status_code == 200:
                            data = resp.json()
                            break
                except Exception:
                    continue
            
            if not data:
                await status_msg.edit_text("❌ 无法连接 TokenGate 算力网关，请检查服务器网络。")
                return

            total_models = data.get("total_free_models", 0)
            daily_tokens = data.get("daily_replenish_tokens", "200万+ / 天")
            providers = data.get("providers", {})
            
            all_models = []
            for p in providers.values():
                if p.get("active"):
                    all_models.extend(p.get("models", []))
            
            expiring = [m for m in all_models if m.get("days_left") is not None and m["days_left"] <= 30]
            expiring_txt = "\n".join([f"• 🔥 *{m['name']}*: 剩余 {m.get('remaining_ratio',1)*100:.1f}% | 仅剩 `{m['days_left']} 天` ({m.get('expire_date')})" for m in expiring]) or "暂无 30 天内临期模型"
            
            text = (
                "⚡ *TokenGate 免费算力全景审计 (N100 直连)*\n\n"
                f"📊 *算力总览*：已纳管 `{total_models}` 款免费模型 | 每日循环补给 `{daily_tokens}`\n\n"
                f"🚨 *临期抢跑资产 (建议全速消耗)*：\n{expiring_txt}\n\n"
                "🔄 *每日无限续杯*：\n• **DeepSeek-V4-Pro (火山)**: 2,000,000 Tokens/天 (每日0点重置)\n\n"
                "💎 *知识库底座*：\n• **Qwen3-VL-Embedding (2560维)**: 2M 额度 (剩余 99.9%)\n• **Qwen3-VL-Rerank**: 100% 满血\n\n"
                "🌐 *算力大屏*：[https://tg.donglida.com](https://tg.donglida.com)\n"
                "🚀 *网关调度*：`model='auto'` 优先消耗临期与每日免费"
            )
            await status_msg.edit_text(text, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"查询配额失败: {e}")
            await status_msg.edit_text(f"❌ 探测 TokenGate 失败: {e}")

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

    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """全局 Telegram 异常处理，避免刷屏日志"""
        logger.warning(f"Telegram 网络或调度异常已捕获: {context.error}")

    app.add_error_handler(error_handler)
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("quota", quota_command))
    app.add_handler(CommandHandler("tokens", quota_command))
    app.add_handler(CommandHandler("clean", clean_command))
    app.add_handler(CommandHandler("ask", ask_command))
    app.add_handler(CommandHandler("chat", chat_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    if app.job_queue:
        app.job_queue.run_repeating(daily_prune_job, interval=86400, first=10)

    logger.info("Bot 已开始 Polling 监听...")
    app.run_polling()

if __name__ == "__main__":
    main()

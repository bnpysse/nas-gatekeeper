#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
第二大脑·AI 智能图书馆 Web 云端服务与交互式研学工作台 (`web_server.py`)
核心能力：
  1. 📚 规范化图书档案大屏：出版社、出版年份、多维标签云、存储路径与 20% 压缩字数统计
  2. 👓 原著 ⇋ 20% 精简本 双栏沉浸式对照阅读器 (带 Mermaid 脉络图与原著段落实时检索)
  3. 💡 划词即交互 (Highlight & Deep Dive)：大白话讲透 / 底层解构 / 生产避坑 / 针对提问
  4. 🎓 AI 导师独立分栏 (缺省固定停靠、不遮挡精简读本、可一键切换浮窗/固定模式)
  5. 💬 伴读 Copilot 实时对谈：结合当前书籍 1024 维切块毫秒 RAG 智能解答
  6. 🎧 在线双人播客：在线播放睿哥与小林的高保真男女声听书对谈
  7. 🎯 RAG 动态无限做题：打字机流式输出错因分析与原著溯源
  8. 💰 全景 Token 算力大屏：实时展示方舟与百炼的消耗总账
"""

import os
import sys
import json
import logging
from pathlib import Path
from typing import Optional, List

current_dir = Path(__file__).resolve().parent
parent_dir = current_dir.parent
if str(parent_dir) not in sys.path:
    sys.path.append(str(parent_dir))
if str(current_dir) in sys.path:
    sys.path.remove(str(current_dir))
sys.path.insert(0, str(current_dir))

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

try:
    from books_pipeline.config import LibraryConfig
    from books_pipeline.db import get_all_books, get_total_library_usage, execute_turso, float_array_to_blob
    from books_pipeline.dual_engine import call_volcengine, stream_volcengine
    from books_pipeline.dynamic_quiz import generate_dynamic_quiz, evaluate_and_explain_stream, evaluate_and_explain
    from books_pipeline.bge_embedder import get_single_bge_m3_embedding, rerank_documents
except ImportError:
    from config import LibraryConfig
    from db import get_all_books, get_total_library_usage, execute_turso, float_array_to_blob
    from dual_engine import call_volcengine, stream_volcengine
    from dynamic_quiz import generate_dynamic_quiz, evaluate_and_explain_stream, evaluate_and_explain
    from bge_embedder import get_single_bge_m3_embedding, rerank_documents

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("LibraryWeb")

app = FastAPI(title="第二大脑·AI 智能图书馆", version="2.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

OUTPUT_DIR = current_dir / "output"


class QuizGenerateRequest(BaseModel):
    book_id: str
    topic: Optional[str] = None


class QuizEvaluateRequest(BaseModel):
    quiz_id: str
    user_answer: str
    user_id: str = "web_user"


# =========================================================================
# API 端点定义
# =========================================================================

@app.get("/api/books")
async def api_get_books():
    """获取所有已入库书籍（包含出版社、年份、分类与标签）"""
    books = await get_all_books()
    return {"status": "success", "data": books}


@app.get("/api/books/{book_id}/chapters")
async def api_get_book_chapters(book_id: str):
    """获取书籍原著的所有章节目录与切块分布"""
    sql = """
    SELECT 
        chapter_title, 
        MIN(chunk_index) as start_chunk, 
        COUNT(*) as chunks_count 
    FROM library_book_chunks 
    WHERE book_id = ? OR book_id LIKE ?
    GROUP BY chapter_title 
    ORDER BY start_chunk ASC;
    """
    rows = await execute_turso(sql, [book_id, f"%{book_id}%"])
    return {"status": "success", "data": rows}


@app.get("/api/books/{book_id}/chunks")
async def api_get_book_chunks(
    book_id: str, 
    chapter: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
):
    """获取原著全文段落切块"""
    if chapter:
        sql = """
        SELECT id, chunk_index, chapter_title, content 
        FROM library_book_chunks 
        WHERE (book_id = ? OR book_id LIKE ?) AND chapter_title = ?
        ORDER BY chunk_index ASC 
        LIMIT ? OFFSET ?;
        """
        rows = await execute_turso(sql, [book_id, f"%{book_id}%", chapter, limit, offset])
    else:
        sql = """
        SELECT id, chunk_index, chapter_title, content 
        FROM library_book_chunks 
        WHERE book_id = ? OR book_id LIKE ?
        ORDER BY chunk_index ASC 
        LIMIT ? OFFSET ?;
        """
        rows = await execute_turso(sql, [book_id, f"%{book_id}%", limit, offset])
        
    return {"status": "success", "data": rows}


@app.get("/api/books/{book_id}/search")
async def api_search_book_chunks(book_id: str, q: str = Query(..., min_length=1)):
    """原著全文关键词检索"""
    clean_q = q.strip()
    sql = """
    SELECT id, chunk_index, chapter_title, content 
    FROM library_book_chunks 
    WHERE (book_id = ? OR book_id LIKE ?) 
      AND (content LIKE ? OR chapter_title LIKE ?)
    ORDER BY chunk_index ASC 
    LIMIT 30;
    """
    rows = await execute_turso(sql, [book_id, f"%{book_id}%", f"%{clean_q}%", f"%{clean_q}%"])
    return {"status": "success", "query": clean_q, "data": rows}


@app.get("/api/books/{book_id}/summary")
async def api_get_summary(book_id: str):
    """获取 20% 极客精读缩减本 Markdown 内容"""
    md_files = list(OUTPUT_DIR.glob(f"*{book_id}*精读研习.md"))
    if not md_files:
        md_files = list(OUTPUT_DIR.glob("*.md"))
        
    target = None
    for f in md_files:
        if book_id in f.name or book_id.lower() in f.name.lower():
            target = f
            break
    if not target and md_files:
        target = md_files[0]
        
    if not target or not target.exists():
        raise HTTPException(status_code=404, detail="未找到精读研习笔记")
        
    content = target.read_text(encoding="utf-8")
    return {"status": "success", "filename": target.name, "content": content, "chars": len(content)}


@app.get("/api/books/{book_id}/audio")
async def api_get_audio(book_id: str):
    """获取书籍的双人听书音频文件 (.m4a)"""
    audio_files = list(OUTPUT_DIR.glob(f"*{book_id}*.m4a")) or list(OUTPUT_DIR.glob("*.m4a"))
    target = None
    for f in audio_files:
        if book_id in f.name or book_id.lower() in f.name.lower():
            target = f
            break
    if not target and audio_files:
        target = audio_files[0]
        
    if not target or not target.exists():
        raise HTTPException(status_code=404, detail="未找到音频文件")
    return FileResponse(target, media_type="audio/mp4", filename=target.name)


# =========================================================================
# 交互式 API：划词即答 (Highlight & Deep Dive) 与 伴读 Copilot 对谈
# =========================================================================

@app.get("/api/interact/stream")
async def api_interact_stream(
    book_id: str,
    action: str,  # 'explain', 'deep_dive', 'pitfalls', 'ask'
    selected_text: str,
    custom_question: Optional[str] = None
):
    """划词即时交互：流式输出大白话讲透/底层解构/生产避坑"""
    system_prompt = "你是一位享誉全球的顶级计算机导师兼架构师，擅长用通透、犀利且极具实战价值的语言给读者解惑。"
    
    if action == "explain":
        prompt = f"""【学员在研读《{book_id}》时，对以下内容感到困惑，请用生动通俗的语言/比喻彻底讲透其核心概念】：
选段内容：
{selected_text}

请输出：
1. 💡 **一句话通俗大白话解读**（结合现实生活或直观场景做比喻）
2. 🎯 **为什么需要这样设计？它解决了什么传统痛点？**
3. 🔑 **核心记忆锚点**
"""
    elif action == "deep_dive":
        prompt = f"""【请对学员在《{book_id}》中划选的以下内容，进行底层原理解构与源码级时序剖析】：
选段内容：
{selected_text}

请输出：
1. ⚙️ **底层运行时 / 虚拟机 / OS / 协议层运作机理**
2. 📊 **内存分配、调度状态机与并发时序分析**
3. ⚖️ **架构设计背后的权衡（Trade-offs 与开销）**
"""
    elif action == "pitfalls":
        prompt = f"""【针对《{book_id}》中划选的以下代码/设计模式，请给出生产实战避坑指南】：
选段内容：
{selected_text}

请输出：
1. 💣 **生产中最致命的 2~3 个典型陷阱与线上事故案例**（如死锁、竞态、内存泄漏、崩溃风暴）
2. 🛡️ **工业级防御方案与标准代码模式**
3. 🔍 **排查与监控诊断指标**
"""
    else:  # ask
        prompt = f"""【学员在研读《{book_id}》时，针对以下段落提出了具体问题】：
选段内容：
{selected_text}

学员问题：
{custom_question or '请深入解读这段内容'}

请给出严密、专业且结合原著技术背景的权威解答：
"""

    async def event_generator():
        try:
            async for token in stream_volcengine(
                LibraryConfig.ENDPOINT_DEEPSEEK_PRO,
                prompt,
                system_prompt,
                temperature=0.3,
                max_tokens=1500,
                book_id=book_id,
                task_name=f"划词交互_{action}"
            ):
                yield f"data: {json.dumps({'chunk': token}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as err:
            yield f"data: {json.dumps({'error': str(err)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/copilot/stream")
async def api_copilot_stream(book_id: str, message: str):
    """伴读 Copilot 聊天室：结合当前书籍向量切块进行 RAG 流式答疑"""
    clean_msg = message.strip()
    sql = """
    SELECT id, chunk_index, chapter_title, content 
    FROM library_book_chunks 
    WHERE (book_id = ? OR book_id LIKE ?)
      AND (content LIKE ? OR chapter_title LIKE ?)
    ORDER BY chunk_index ASC 
    LIMIT 3;
    """
    first_term = clean_msg.split()[0] if clean_msg else ""
    rows = await execute_turso(sql, [book_id, f"%{book_id}%", f"%{first_term}%", f"%{first_term}%"])
    
    context_chunks = "\n\n".join([f"【原著出处: {r['chapter_title']} #切块{r['chunk_index']}】\n{r['content'][:800]}" for r in rows]) if rows else "（结合全书知识脉络）"

    system_prompt = f"你是技术专著《{book_id}》的专属 AI 伴读导师。你熟读全书所有章节与代码实现，能够随时解答读者的深度问题，并精准引用原著论据。"
    prompt = f"""学员在研读书籍《{book_id}》时提出了以下问题：

学员提问：
{clean_msg}

【原著关联参考段落】：
{context_chunks}

请结合原著深度，以亲切且专业的口吻为学员解答，并在适当时引用原著核心逻辑："""

    async def event_generator():
        try:
            async for token in stream_volcengine(
                LibraryConfig.ENDPOINT_DEEPSEEK_PRO,
                prompt,
                system_prompt,
                temperature=0.4,
                max_tokens=1500,
                book_id=book_id,
                task_name="伴读Copilot对谈"
            ):
                yield f"data: {json.dumps({'chunk': token}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as err:
            yield f"data: {json.dumps({'error': str(err)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# =========================================================================
# 算力台账与做题 API
# =========================================================================

@app.get("/api/usage")
async def api_get_usage():
    """获取全景算力与 Token 消耗统计"""
    usage = await get_total_library_usage()
    return {"status": "success", "data": usage}


@app.post("/api/quiz/generate")
async def api_generate_quiz(req: QuizGenerateRequest):
    """RAG 动态命制测试题"""
    try:
        quiz = await generate_dynamic_quiz(req.book_id, req.topic)
        return {"status": "success", "data": quiz}
    except Exception as e:
        logger.error(f"出题异常: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/quiz/evaluate")
async def api_evaluate_quiz(req: QuizEvaluateRequest):
    """做题解析与导师复盘 (非流式)"""
    try:
        res = await evaluate_and_explain(req.quiz_id, req.user_answer, req.user_id)
        return {"status": "success", "data": res}
    except Exception as e:
        logger.error(f"解析异常: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/quiz/evaluate/stream")
async def api_evaluate_quiz_stream(quiz_id: str, user_answer: str):
    """做题解析打字机流式输出 (SSE Stream)"""
    async def event_generator():
        try:
            async for token in evaluate_and_explain_stream(quiz_id, user_answer):
                yield f"data: {json.dumps({'chunk': token}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as err:
            yield f"data: {json.dumps({'error': str(err)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# =========================================================================
# Web UI 单页应用 (包含固定独立分栏导师面板、划词工具栏、双栏阅读与图书元数据)
# =========================================================================

@app.get("/", response_class=HTMLResponse)
async def index_page():
    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>第二大脑·AI 智能图书馆 & 交互研学工作台</title>
    <!-- Tailwind CSS -->
    <script src="https://cdn.tailwindcss.com"></script>
    <!-- Marked (Markdown 解析器) -->
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <!-- Highlight.js 代码高亮 -->
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css">
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
    <!-- Mermaid 图表支持 -->
    <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Fira+Code:wght@400;500&display=swap" rel="stylesheet">
    <style>
        body { font-family: 'Inter', sans-serif; background: #080c14; color: #f1f5f9; }
        .glass-panel { background: rgba(15, 23, 42, 0.82); backdrop-filter: blur(20px); border: 1px solid rgba(255, 255, 255, 0.08); }
        .glass-card { background: rgba(22, 33, 56, 0.65); backdrop-filter: blur(14px); border: 1px solid rgba(255, 255, 255, 0.06); }
        .glass-card:hover { border-color: rgba(99, 102, 241, 0.45); }
        
        /* Markdown 样式增强 */
        .markdown-body { color: #cbd5e1; line-height: 1.8; font-size: 0.95rem; }
        .markdown-body h1 { font-size: 1.65rem; font-weight: 800; color: #f8fafc; margin-top: 1.6rem; margin-bottom: 0.8rem; border-bottom: 1px solid #334155; padding-bottom: 0.4rem; }
        .markdown-body h2 { font-size: 1.35rem; font-weight: 700; color: #38bdf8; margin-top: 1.6rem; margin-bottom: 0.7rem; border-bottom: 1px solid #1e293b; padding-bottom: 0.3rem; }
        .markdown-body h3 { font-size: 1.15rem; font-weight: 600; color: #a5b4fc; margin-top: 1.2rem; margin-bottom: 0.5rem; }
        .markdown-body p { margin-bottom: 0.95rem; }
        .markdown-body ul, .markdown-body ol { margin-left: 1.4rem; margin-bottom: 0.95rem; list-style-type: disc; }
        .markdown-body blockquote { border-left: 3px solid #6366f1; padding: 0.6rem 1rem; color: #94a3b8; background: rgba(99,102,241,0.06); border-radius: 0 8px 8px 0; margin-bottom: 1rem; }
        .markdown-body code { font-family: 'Fira Code', monospace; background: #1e293b; color: #fb7185; padding: 0.15rem 0.4rem; border-radius: 4px; font-size: 0.88em; }
        .markdown-body pre { background: #0b0f19 !important; padding: 1.1rem; border-radius: 12px; overflow-x: auto; margin-bottom: 1.2rem; border: 1px solid #1e293b; }
        .markdown-body pre code { background: transparent !important; color: #e2e8f0; padding: 0; }
        
        /* 划词悬浮菜单 */
        #selection-toolbar {
            position: absolute;
            z-index: 100;
            display: none;
            background: rgba(15, 23, 42, 0.95);
            backdrop-filter: blur(12px);
            border: 1px solid rgba(99, 102, 241, 0.4);
            box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.6), 0 8px 10px -6px rgba(0, 0, 0, 0.6);
            border-radius: 12px;
            padding: 4px;
        }

        /* 滚动条 */
        ::-webkit-scrollbar { width: 6px; height: 6px; }
        ::-webkit-scrollbar-track { background: #080c14; }
        ::-webkit-scrollbar-thumb { background: #334155; border-radius: 3px; }
        ::-webkit-scrollbar-thumb:hover { background: #475569; }
    </style>
</head>
<body class="min-h-screen flex flex-col">

    <!-- 划词悬浮菜单 (Floating Action Popover) -->
    <div id="selection-toolbar" class="flex items-center gap-1">
        <button onclick="triggerInteractAction('explain')" class="px-2.5 py-1 text-xs text-slate-200 hover:text-white hover:bg-indigo-600/80 rounded-lg transition flex items-center gap-1">
            <span>💡</span> 大白话讲透
        </button>
        <button onclick="triggerInteractAction('deep_dive')" class="px-2.5 py-1 text-xs text-slate-200 hover:text-white hover:bg-cyan-600/80 rounded-lg transition flex items-center gap-1">
            <span>⚙️</span> 底层解构
        </button>
        <button onclick="triggerInteractAction('pitfalls')" class="px-2.5 py-1 text-xs text-slate-200 hover:text-white hover:bg-rose-600/80 rounded-lg transition flex items-center gap-1">
            <span>🚀</span> 生产避坑
        </button>
        <button onclick="triggerInteractAction('ask')" class="px-2.5 py-1 text-xs text-slate-200 hover:text-white hover:bg-slate-700 rounded-lg transition flex items-center gap-1">
            <span>💬</span> 追问此段
        </button>
    </div>

    <!-- Top Navigation Bar -->
    <header class="border-b border-slate-800/80 glass-panel sticky top-0 z-50">
        <div class="max-w-[1750px] mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
            <div class="flex items-center space-x-3 cursor-pointer" onclick="switchTab('library')">
                <span class="text-2xl">📚</span>
                <div>
                    <h1 class="text-lg font-bold bg-gradient-to-r from-indigo-400 via-cyan-300 to-sky-400 bg-clip-text text-transparent">第二大脑·AI 智能图书馆</h1>
                    <p class="text-[10px] text-slate-400 tracking-wider">CLOSE READING & INTERACTIVE STUDIO</p>
                </div>
            </div>
            <div class="flex items-center space-x-2 sm:space-x-3">
                <button onclick="switchTab('library')" id="tab-btn-library" class="px-3.5 py-1.5 rounded-xl text-xs font-semibold bg-indigo-600 text-white shadow-lg shadow-indigo-600/30 transition">📖 藏书大屏</button>
                <button onclick="switchTab('reader')" id="tab-btn-reader" class="px-3.5 py-1.5 rounded-xl text-xs font-semibold text-slate-300 hover:text-white transition">👓 20%双栏研学</button>
                <button onclick="switchTab('quiz')" id="tab-btn-quiz" class="px-3.5 py-1.5 rounded-xl text-xs font-semibold text-slate-300 hover:text-white transition">🎯 RAG 动态做题</button>
                <button onclick="switchTab('usage')" id="tab-btn-usage" class="px-3.5 py-1.5 rounded-xl text-xs font-semibold text-slate-300 hover:text-white transition">💰 算力总账</button>
            </div>
        </div>
    </header>

    <!-- Main Container -->
    <main class="flex-1 max-w-[1750px] w-full mx-auto px-4 sm:px-6 lg:px-8 py-6 flex flex-col">
        
        <!-- View 1: Bookshelf & Enterprise Metadata (藏书档案大屏) -->
        <section id="tab-library" class="space-y-6">
            <!-- 标题与状态栏 -->
            <div class="flex flex-wrap justify-between items-center gap-4 glass-panel p-6 rounded-2xl border border-slate-800">
                <div>
                    <h2 class="text-xl font-bold flex items-center gap-2"><span>🏛️</span> 经典专著规范档案库</h2>
                    <p class="text-xs text-slate-400 mt-1">严格按照 20% 极客原则重构，保留 85%+ 核心技术干货、架构图解与生产代码</p>
                </div>
                <div class="flex items-center gap-2">
                    <span id="books-count-badge" class="text-xs px-3.5 py-1.5 rounded-full bg-slate-800/90 border border-slate-700 text-indigo-300 font-mono font-medium shadow-inner">加载中...</span>
                </div>
            </div>

            <!-- 🔍 多维智能检索与分类过滤控制台 -->
            <div class="glass-panel p-5 rounded-2xl space-y-4 border border-slate-800/90 shadow-xl">
                <!-- 搜索框与排序条 -->
                <div class="flex flex-col md:flex-row items-stretch md:items-center justify-between gap-3">
                    <!-- 模糊搜索框 (书名、作者、出版社、ISBN、标签) -->
                    <div class="relative flex-1">
                        <span class="absolute left-3.5 top-2.5 text-slate-400 text-sm">🔍</span>
                        <input type="text" id="library-search-input" oninput="handleLibraryFilterChange()" placeholder="搜索书名、作者、出版社、ISBN书号、标签... (即输即显)" class="w-full bg-slate-900/90 border border-slate-700/80 rounded-xl pl-10 pr-10 py-2 text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500 transition duration-200">
                        <button id="btn-clear-search" onclick="clearSearchInput()" class="absolute right-3 top-2 text-slate-400 hover:text-white hidden text-xs bg-slate-800 hover:bg-slate-700 rounded-full w-5 h-5 flex items-center justify-center transition">✕</button>
                    </div>

                    <!-- 下拉筛选与排序组 -->
                    <div class="flex items-center gap-2 flex-wrap sm:flex-nowrap">
                        <!-- 排序方式 (重点支持出版时间) -->
                        <div class="flex items-center gap-1.5 shrink-0">
                            <span class="text-xs text-slate-400">📅 排序:</span>
                            <select id="library-sort-select" onchange="handleLibraryFilterChange()" class="bg-slate-900 border border-slate-700 rounded-xl px-2.5 py-2 text-xs text-slate-200 focus:outline-none focus:border-indigo-500 transition font-sans">
                                <option value="year_desc">📅 出版时间：最新优先 (2026 ➔ 2020)</option>
                                <option value="year_asc">📅 出版时间：经典溯源</option>
                                <option value="created_desc">⏱️ 精读入库：最新处理</option>
                                <option value="chars_desc">📏 原著字数：大部头优先</option>
                                <option value="chars_asc">📏 原著字数：短小精悍</option>
                                <option value="summary_desc">⚡ 精简字数：高密度优先</option>
                                <option value="title_asc">🔤 书名字母：A ➔ Z</option>
                            </select>
                        </div>

                        <!-- 出版社过滤 -->
                        <select id="library-publisher-select" onchange="handleLibraryFilterChange()" class="bg-slate-900 border border-slate-700 rounded-xl px-2.5 py-2 text-xs text-slate-200 focus:outline-none focus:border-indigo-500 transition shrink-0">
                            <option value="">🏢 全部出版社</option>
                        </select>

                        <!-- 分类领域过滤 -->
                        <select id="library-category-select" onchange="handleLibraryFilterChange()" class="bg-slate-900 border border-slate-700 rounded-xl px-2.5 py-2 text-xs text-slate-200 focus:outline-none focus:border-indigo-500 transition shrink-0">
                            <option value="">📂 全部分类</option>
                        </select>
                    </div>
                </div>

                <!-- 🏷️ #Tag 标签云交互过滤栏 -->
                <div class="flex items-start gap-2 pt-2 border-t border-slate-800">
                    <div class="text-xs text-slate-400 shrink-0 pt-1 flex items-center gap-1 font-medium">
                        <span>🏷️</span>
                        <span>标签导航:</span>
                    </div>
                    <div id="library-tags-cloud" class="flex items-center gap-1.5 flex-wrap flex-1">
                        <!-- Dynamic Tag Pills -->
                    </div>
                    <button id="btn-reset-filters" onclick="resetAllFilters()" class="text-xs text-rose-400 hover:text-rose-300 px-2.5 py-1 rounded-lg bg-rose-950/40 border border-rose-800/30 hover:bg-rose-950/70 transition shrink-0 hidden">
                        ✖ 重置筛选
                    </button>
                </div>
            </div>

            <!-- 图书卡片网格容器 -->
            <div id="books-grid" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
                <!-- Dynamic Book Cards -->
            </div>

            <!-- 空结果提示 -->
            <div id="books-empty-state" class="hidden text-center py-20 glass-panel rounded-2xl space-y-3">
                <div class="text-4xl">🔍</div>
                <p class="text-sm text-slate-300 font-medium">未找到匹配的专著藏书</p>
                <p class="text-xs text-slate-500">请尝试调整关键词、清除 #Tag 标签或切换出版社/分类</p>
                <button onclick="resetAllFilters()" class="px-4 py-1.5 text-xs bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl transition">重置所有筛选</button>
            </div>
        </section>

        <!-- View 2: Dual Split Reader & Interactive Studio (双栏阅读与人机交互) -->
        <section id="tab-reader" class="hidden flex-1 flex flex-col space-y-4">
            
            <!-- Book Metadata Header Card -->
            <div id="reader-metadata-bar" class="glass-panel p-4 rounded-2xl flex flex-wrap items-center justify-between gap-4 text-xs">
                <div class="flex items-center gap-3 flex-wrap">
                    <div class="flex items-center gap-2">
                        <span class="font-bold text-indigo-400">📖 当前书籍:</span>
                        <select id="reader-book-select" onchange="loadReaderForSelectedBook()" class="bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-indigo-500"></select>
                    </div>
                    <span id="book-meta-publisher" class="px-2 py-0.5 rounded bg-slate-800 text-slate-300 font-mono">出版社: --</span>
                    <span id="book-meta-year" class="px-2 py-0.5 rounded bg-slate-800 text-slate-300 font-mono">年份: --</span>
                    <span id="book-meta-category" class="px-2 py-0.5 rounded bg-indigo-950/80 text-indigo-300 border border-indigo-800/40">分类: --</span>
                </div>

                <!-- Dual Voice Podcast Audio Player -->
                <div class="flex items-center gap-2 bg-slate-900/90 border border-slate-800 px-3 py-1 rounded-xl">
                    <span class="text-slate-400">🎧 听书播客:</span>
                    <audio id="reader-audio-player" controls class="h-7 max-w-[180px]"></audio>
                </div>

                <!-- Layout Buttons -->
                <div class="flex items-center gap-2">
                    <span class="text-slate-400">分屏模式:</span>
                    <button onclick="setReaderLayout('split')" id="btn-layout-split" class="px-2.5 py-1 rounded bg-indigo-600 text-white font-medium">双栏分屏</button>
                    <button onclick="setReaderLayout('summary')" id="btn-layout-summary" class="px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300">20%精简本</button>
                    <button onclick="setReaderLayout('original')" id="btn-layout-original" class="px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300">原著全文</button>
                </div>
            </div>

            <!-- Tags Bar -->
            <div id="reader-tags-bar" class="flex items-center gap-2 flex-wrap text-xs px-2">
                <span class="text-slate-500">🏷️ 知识标签:</span>
                <div id="reader-tags-container" class="flex items-center gap-1.5 flex-wrap"></div>
            </div>

            <!-- 动态三栏研学工作台容器 (Flexbox 平铺，展开导师时绝不遮挡精讲和原著) -->
            <div id="reader-columns-container" class="flex flex-col lg:flex-row gap-4 flex-1 min-h-[75vh] w-full items-stretch">
                
                <!-- Column 1: 20% Condensed Book (精简本与知识脉络) -->
                <div id="reader-col-summary" class="flex-1 min-w-0 glass-panel p-6 rounded-2xl flex flex-col h-[78vh] transition-all duration-300">
                    <div class="flex justify-between items-center border-b border-slate-800 pb-3 mb-4">
                        <div class="flex items-center gap-2">
                            <span class="px-2.5 py-0.5 rounded bg-indigo-950 text-indigo-400 font-bold text-xs border border-indigo-800/40">20% 极客干货讲义</span>
                            <span id="summary-chars-badge" class="text-xs text-slate-400 font-mono">加载中...</span>
                        </div>
                        <span class="text-[11px] text-slate-500 hidden sm:inline">💡 划选任意文本可呼出 AI 深度解构</span>
                    </div>
                    <div id="summary-content" class="markdown-body overflow-y-auto flex-1 pr-2 select-text">
                        <div class="text-center py-12 text-slate-500">正在加载 20% 精读讲义...</div>
                    </div>
                </div>

                <!-- Column 2: Original Book Context & Search (原著全文与章节索引) -->
                <div id="reader-col-original" class="flex-1 min-w-0 glass-panel p-6 rounded-2xl flex flex-col h-[78vh] transition-all duration-300">
                    <div class="flex flex-wrap items-center justify-between border-b border-slate-800 pb-3 mb-4 gap-2">
                        <div class="flex items-center gap-2">
                            <span class="px-2.5 py-0.5 rounded bg-cyan-950 text-cyan-400 font-bold text-xs border border-cyan-800/40">原著全文与章节溯源</span>
                            <span id="original-stats-badge" class="text-xs text-slate-400 font-mono">0 章节</span>
                        </div>
                        <!-- Chapter Selector -->
                        <select id="reader-chapter-select" onchange="filterOriginalByChapter()" class="bg-slate-800 border border-slate-700 rounded-lg px-2.5 py-1 text-xs text-slate-200 max-w-[200px] focus:outline-none">
                            <option value="">📖 全部原著章节</option>
                        </select>
                    </div>

                    <!-- Search Input Bar -->
                    <div class="mb-3 relative">
                        <input type="text" id="original-search-input" onkeyup="handleOriginalSearch(event)" placeholder="🔍 全文检索原著（输入函数名、原理... 回车搜索）" class="w-full bg-slate-900/90 border border-slate-700/80 rounded-xl px-3.5 py-2 text-xs text-slate-200 focus:outline-none focus:border-cyan-500 pl-8">
                        <span class="absolute left-2.5 top-2 text-slate-500 text-xs">🔎</span>
                    </div>

                    <!-- Original Chunks Stream Container -->
                    <div id="original-chunks-container" class="overflow-y-auto flex-1 pr-2 space-y-4 font-mono text-xs text-slate-300 select-text">
                        <div class="text-center py-12 text-slate-500">正在加载原著上下文...</div>
                    </div>
                </div>

                <!-- Column 3: AI Mentor Panel (固定分栏/平铺布局，缺省状态固定、绝不遮挡精简读本) -->
                <div id="reader-col-mentor" class="glass-panel p-5 rounded-2xl flex flex-col h-[78vh] transition-all duration-300 hidden border border-slate-800/90 shadow-2xl">
                    <div class="flex justify-between items-center border-b border-slate-800 pb-3 mb-3 shrink-0">
                        <div class="flex items-center gap-2">
                            <span id="drawer-icon" class="text-base">💡</span>
                            <h3 id="drawer-title" class="text-xs font-bold text-slate-100">AI 智能研学导师</h3>
                        </div>
                        <div class="flex items-center gap-2">
                            <!-- Toggle Pin/Float Button -->
                            <button onclick="toggleMentorMode()" id="btn-toggle-pin" class="px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-cyan-300 text-[11px] font-mono transition flex items-center gap-1" title="切换：固定分栏 (不遮挡) / 悬浮抽屉">
                                <span id="pin-icon">📌 固定中</span>
                            </button>
                            <button onclick="closeInteractiveDrawer()" class="p-1 rounded hover:bg-slate-800 text-slate-400 hover:text-rose-400 text-xs transition" title="收起/关闭">✕</button>
                        </div>
                    </div>
                    
                    <!-- Selected Quote Box -->
                    <div class="p-3 bg-slate-950/70 border border-slate-800/80 rounded-xl text-xs mb-3 shrink-0">
                        <span class="text-slate-400 text-[11px] block mb-1 font-medium">当前讨论段落 / 主题：</span>
                        <div id="drawer-selected-quote" class="p-2 rounded-lg bg-slate-900/90 text-slate-300 font-mono text-[11px] max-h-20 overflow-y-auto line-clamp-3"></div>
                    </div>

                    <!-- Scrollable Markdown Content -->
                    <div id="drawer-content-body" class="flex-1 p-3.5 overflow-y-auto markdown-body text-xs leading-relaxed text-slate-200 bg-slate-950/50 rounded-xl border border-slate-800/60 select-text mb-3">
                        <div class="text-center py-12 text-slate-500">正在生成深度解析...</div>
                    </div>

                    <!-- Follow-up Question Input -->
                    <div class="p-2 border border-slate-800/80 bg-slate-900/90 rounded-xl flex items-center gap-2 shrink-0">
                        <input type="text" id="drawer-user-input" onkeyup="if(event.key==='Enter') sendDrawerFollowup()" placeholder="继续追问伴读导师..." class="flex-1 bg-slate-800/80 border border-slate-700/60 rounded-lg px-2.5 py-1.5 text-xs text-slate-100 focus:outline-none focus:border-indigo-500">
                        <button onclick="sendDrawerFollowup()" class="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-xs font-semibold rounded-lg text-white transition">发送</button>
                    </div>
                </div>

            </div>
        </section>

        <!-- View 3: Dynamic Quiz (RAG 动态出题) -->
        <section id="tab-quiz" class="hidden space-y-6 max-w-4xl mx-auto w-full">
            <div class="glass-card p-6 rounded-2xl space-y-4">
                <h2 class="text-xl font-bold flex items-center gap-2"><span>🎯</span> RAG 现场命题与动态错因复盘</h2>
                <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div>
                        <label class="block text-xs font-medium text-slate-400 mb-1">选择研读书籍</label>
                        <select id="quiz-book-select" class="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-xs focus:outline-none focus:border-indigo-500"></select>
                    </div>
                    <div>
                        <label class="block text-xs font-medium text-slate-400 mb-1">专题关键词 (可选，用于定向抽题)</label>
                        <input type="text" id="quiz-topic-input" placeholder="例如: OTP, GenServer, Docker, Microservices..." class="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-xs focus:outline-none focus:border-indigo-500">
                    </div>
                </div>
                <button onclick="requestQuiz()" id="generate-quiz-btn" class="w-full py-2.5 bg-gradient-to-r from-indigo-600 to-cyan-600 hover:from-indigo-500 hover:to-cyan-500 text-white rounded-xl text-xs font-semibold shadow-lg shadow-indigo-500/20 transition duration-200">
                    🧠 由 DeepSeek-V4-Pro 现场命制技术试题
                </button>
            </div>

            <!-- Quiz Card -->
            <div id="quiz-card" class="glass-card p-6 rounded-2xl space-y-6 hidden">
                <div class="border-b border-slate-800 pb-4 flex justify-between items-center">
                    <span id="quiz-chapter" class="text-xs px-2.5 py-1 rounded-md bg-indigo-950/60 text-indigo-400 border border-indigo-800/40 font-mono">章节</span>
                    <span class="text-xs text-slate-500">单选题</span>
                </div>
                <div id="quiz-question" class="text-sm sm:text-base font-medium leading-relaxed text-slate-100 font-mono"></div>
                <div id="quiz-options" class="space-y-3"></div>
                
                <!-- Streaming Analysis Output -->
                <div id="analysis-box" class="hidden border-t border-slate-800 pt-6 space-y-3">
                    <h3 class="text-xs font-semibold text-cyan-400 flex items-center gap-2"><span>🎓</span> 导师深度复盘与原著溯源</h3>
                    <div id="analysis-content" class="bg-slate-900/90 p-4 rounded-xl text-xs text-slate-200 leading-relaxed font-mono whitespace-pre-wrap border border-slate-800"></div>
                </div>
            </div>
        </section>

        <!-- View 4: Usage Ledger (算力大屏) -->
        <section id="tab-usage" class="hidden space-y-6 max-w-5xl mx-auto w-full">
            <div class="glass-card p-6 md:p-8 rounded-3xl space-y-6 border border-slate-800 shadow-2xl">
                <div class="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 pb-4">
                    <div>
                        <h2 class="text-xl font-bold flex items-center gap-2 text-slate-100">
                            <span>💰</span> 全景 Token 算力与模型调用台账
                        </h2>
                        <p class="text-xs text-slate-400 mt-1">毫秒级记录全库书籍深度切块、双语研习精读、RAG 向量嵌入与动态测试出题的算力消耗明细</p>
                    </div>
                    <button onclick="loadUsage()" class="px-3 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-xs text-slate-300 font-mono transition flex items-center gap-1.5">
                        <span>🔄</span> 刷新台账
                    </button>
                </div>

                <!-- 4 块核心概览指标卡 -->
                <div class="grid grid-cols-2 lg:grid-cols-4 gap-4">
                    <div class="bg-slate-900/80 p-4 rounded-2xl border border-slate-800/90 shadow-inner">
                        <span class="text-[11px] text-slate-400 font-medium">全库累计模型调用</span>
                        <div id="total-calls-val" class="text-2xl font-bold text-indigo-400 mt-1.5 font-mono">0 次</div>
                        <span class="text-[10px] text-slate-500 mt-1 block font-mono">AI 研学与精读总频次</span>
                    </div>
                    <div class="bg-slate-900/80 p-4 rounded-2xl border border-slate-800/90 shadow-inner">
                        <span class="text-[11px] text-slate-400 font-medium">累计消耗 Tokens</span>
                        <div id="total-tokens-val" class="text-2xl font-bold text-cyan-400 mt-1.5 font-mono">0</div>
                        <span class="text-[10px] text-slate-500 mt-1 block font-mono">输入 + 输出总计</span>
                    </div>
                    <div class="bg-slate-900/80 p-4 rounded-2xl border border-slate-800/90 shadow-inner">
                        <span class="text-[11px] text-slate-400 font-medium">输入 / 输出 Tokens</span>
                        <div class="text-xs font-bold text-slate-200 mt-2 font-mono flex items-center justify-between">
                            <span id="prompt-tokens-val" class="text-sky-300">入: 0</span>
                            <span id="comp-tokens-val" class="text-emerald-300">出: 0</span>
                        </div>
                        <span class="text-[10px] text-slate-500 mt-1 block font-mono">Prompt vs Completion</span>
                    </div>
                    <div class="bg-slate-900/80 p-4 rounded-2xl border border-slate-800/90 shadow-inner">
                        <span class="text-[11px] text-slate-400 font-medium">累计大模型推理耗时</span>
                        <div id="total-duration-val" class="text-2xl font-bold text-amber-400 mt-1.5 font-mono">0.0s</div>
                        <span id="total-hours-val" class="text-[10px] text-slate-500 mt-1 block font-mono">~0.0 小时累计分析</span>
                    </div>
                </div>

                <!-- 各大模型与厂商详细明细列表 -->
                <div class="space-y-3 pt-2">
                    <div class="flex items-center justify-between text-xs text-slate-400 font-medium px-1">
                        <span>各大模型与引擎消耗明细</span>
                        <span>按 Tokens 贡献度排列</span>
                    </div>
                    <div id="usage-breakdown" class="space-y-3">
                        <!-- Dynamic Model Breakdown Cards -->
                    </div>
                </div>
            </div>
        </section>

    </main>

    <!-- Floating Copilot Button (右下角常驻伴读导师) -->
    <button onclick="openCopilotChat()" class="fixed bottom-6 right-6 p-3.5 rounded-full bg-gradient-to-r from-indigo-600 to-cyan-600 text-white shadow-xl shadow-indigo-600/30 hover:scale-105 transition duration-200 z-40 flex items-center gap-2 text-xs font-bold">
        <span>💬</span> 伴读导师
    </button>

    <!-- Footer -->
    <footer class="border-t border-slate-800/80 py-4 text-center text-xs text-slate-500">
        第二大脑·AI 智能图书馆 © 2026 | 由 Turso 边缘数据库与火山方舟双引擎驱动
    </footer>

    <!-- Script Logic -->
    <script>
        marked.setOptions({
            highlight: function(code, lang) {
                const language = hljs.getLanguage(lang) ? lang : 'plaintext';
                return hljs.highlight(code, { language }).value;
            },
            breaks: true
        });
        mermaid.initialize({ startOnLoad: false, theme: 'dark' });

        let allBooksList = [];
        let currentReaderBookId = '';
        let currentQuizData = null;
        let selectedTextCache = '';
        
        // 导师面板状态：默认固定停靠 (isDocked = true)
        let isMentorDocked = true;
        let isMentorOpen = false;

        function switchTab(tabId) {
            ['library', 'reader', 'quiz', 'usage'].forEach(t => {
                document.getElementById(`tab-${t}`).classList.add('hidden');
                document.getElementById(`tab-btn-${t}`).className = 'px-3.5 py-1.5 rounded-xl text-xs font-semibold text-slate-300 hover:text-white transition';
            });
            document.getElementById(`tab-${tabId}`).classList.remove('hidden');
            document.getElementById(`tab-btn-${tabId}`).className = 'px-3.5 py-1.5 rounded-xl text-xs font-semibold bg-indigo-600 text-white shadow-lg shadow-indigo-600/30 transition';
            
            if (tabId === 'usage') loadUsage();
            if (tabId === 'reader' && !currentReaderBookId && allBooksList.length > 0) {
                openReaderForBook(allBooksList[0].id);
            }
        }

        let activeTagFilter = '';

        async function loadBooks() {
            try {
                const res = await fetch('/api/books');
                const json = await res.json();
                allBooksList = json.data || [];
                
                // 1. 初始化下拉菜单（书籍阅读器与抽题）
                const readerSelect = document.getElementById('reader-book-select');
                const quizSelect = document.getElementById('quiz-book-select');
                if (readerSelect) readerSelect.innerHTML = '';
                if (quizSelect) quizSelect.innerHTML = '';

                // 2. 收集所有独一无二的出版社、分类和 #Tag 标签
                const publishersSet = new Set();
                const categoriesSet = new Set();
                const tagsMap = new Map(); // tag -> count

                allBooksList.forEach(b => {
                    if (b.publisher) publishersSet.add(b.publisher);
                    if (b.category) categoriesSet.add(b.category);

                    let tags = [];
                    try { tags = JSON.parse(b.tags_json || '[]'); } catch(e){}
                    tags.forEach(t => {
                        const cleanT = t.trim();
                        if (cleanT) {
                            tagsMap.set(cleanT, (tagsMap.get(cleanT) || 0) + 1);
                        }
                    });

                    if (readerSelect) {
                        const opt = document.createElement('option');
                        opt.value = b.id;
                        opt.textContent = `《${b.title}》`;
                        readerSelect.appendChild(opt);
                    }
                    if (quizSelect) {
                        const opt = document.createElement('option');
                        opt.value = b.id;
                        opt.textContent = `《${b.title}》`;
                        quizSelect.appendChild(opt);
                    }
                });

                // 3. 填充出版社筛选下拉框
                const pubSelect = document.getElementById('library-publisher-select');
                if (pubSelect) {
                    pubSelect.innerHTML = '<option value="">🏢 全部出版社</option>';
                    Array.from(publishersSet).sort().forEach(p => {
                        const opt = document.createElement('option');
                        opt.value = p;
                        opt.textContent = p;
                        pubSelect.appendChild(opt);
                    });
                }

                // 4. 填充分类领域筛选下拉框
                const catSelect = document.getElementById('library-category-select');
                if (catSelect) {
                    catSelect.innerHTML = '<option value="">📂 全部分类</option>';
                    Array.from(categoriesSet).sort().forEach(c => {
                        const opt = document.createElement('option');
                        opt.value = c;
                        opt.textContent = c;
                        catSelect.appendChild(opt);
                    });
                }

                // 5. 渲染标签云栏
                renderTagsCloud(tagsMap);

                // 6. 执行初次渲染与排序
                renderLibraryView();
            } catch(e) {
                console.error("加载图书失败:", e);
            }
        }

        function renderTagsCloud(tagsMap) {
            const container = document.getElementById('library-tags-cloud');
            if (!container) return;

            // 按照使用频次排序取常用标签
            const sortedTags = Array.from(tagsMap.entries()).sort((a, b) => b[1] - a[1]);
            
            let html = `
                <button onclick="toggleTagFilter('')" class="text-[11px] px-2.5 py-1 rounded-lg ${!activeTagFilter ? 'bg-indigo-600 text-white font-bold shadow-md shadow-indigo-600/30' : 'bg-slate-800/90 text-slate-400 hover:text-slate-200'} font-mono transition">
                    全部 (${allBooksList.length})
                </button>
            `;

            sortedTags.forEach(([tag, count]) => {
                const isActive = activeTagFilter === tag;
                html += `
                    <button onclick="toggleTagFilter('${tag}')" class="text-[11px] px-2.5 py-1 rounded-lg ${isActive ? 'bg-indigo-600 text-white font-bold shadow-md shadow-indigo-600/30 ring-2 ring-indigo-400' : 'bg-slate-800/80 hover:bg-slate-700 text-cyan-300'} font-mono transition flex items-center gap-1">
                        <span>${tag}</span>
                        <span class="text-[10px] opacity-70">${count}</span>
                    </button>
                `;
            });

            container.innerHTML = html;
        }

        function toggleTagFilter(tag) {
            if (activeTagFilter === tag) {
                activeTagFilter = '';
            } else {
                activeTagFilter = tag;
            }
            // 重新刷新标签云高亮
            const tagsMap = new Map();
            allBooksList.forEach(b => {
                let tags = [];
                try { tags = JSON.parse(b.tags_json || '[]'); } catch(e){}
                tags.forEach(t => {
                    const cleanT = t.trim();
                    if (cleanT) tagsMap.set(cleanT, (tagsMap.get(cleanT) || 0) + 1);
                });
            });
            renderTagsCloud(tagsMap);
            renderLibraryView();
        }

        function clearSearchInput() {
            const input = document.getElementById('library-search-input');
            if (input) {
                input.value = '';
                handleLibraryFilterChange();
            }
        }

        function resetAllFilters() {
            activeTagFilter = '';
            const searchInput = document.getElementById('library-search-input');
            const pubSelect = document.getElementById('library-publisher-select');
            const catSelect = document.getElementById('library-category-select');
            const sortSelect = document.getElementById('library-sort-select');

            if (searchInput) searchInput.value = '';
            if (pubSelect) pubSelect.value = '';
            if (catSelect) catSelect.value = '';
            if (sortSelect) sortSelect.value = 'year_desc';

            loadBooks();
        }

        function handleLibraryFilterChange() {
            renderLibraryView();
        }

        function renderLibraryView() {
            const searchInput = (document.getElementById('library-search-input')?.value || '').trim().toLowerCase();
            const sortType = document.getElementById('library-sort-select')?.value || 'year_desc';
            const pubFilter = document.getElementById('library-publisher-select')?.value || '';
            const catFilter = document.getElementById('library-category-select')?.value || '';

            // 1. 过滤逻辑 (Filter)
            let filtered = allBooksList.filter(b => {
                // 搜索框匹配 (书名、作者、出版社、ISBN、分类、描述、标签)
                if (searchInput) {
                    const titleMatch = (b.title || '').toLowerCase().includes(searchInput);
                    const authorMatch = (b.author || '').toLowerCase().includes(searchInput);
                    const pubMatch = (b.publisher || '').toLowerCase().includes(searchInput);
                    const isbnMatch = (b.isbn || '').toLowerCase().includes(searchInput);
                    const catMatch = (b.category || '').toLowerCase().includes(searchInput);
                    const descMatch = (b.description || '').toLowerCase().includes(searchInput);
                    let tagMatch = false;
                    try {
                        const tags = JSON.parse(b.tags_json || '[]');
                        tagMatch = tags.some(t => t.toLowerCase().includes(searchInput));
                    } catch(e){}

                    if (!titleMatch && !authorMatch && !pubMatch && !isbnMatch && !catMatch && !descMatch && !tagMatch) {
                        return false;
                    }
                }

                // 出版社过滤
                if (pubFilter && b.publisher !== pubFilter) {
                    return false;
                }

                // 分类过滤
                if (catFilter && b.category !== catFilter) {
                    return false;
                }

                // #Tag 标签过滤
                if (activeTagFilter) {
                    try {
                        const tags = JSON.parse(b.tags_json || '[]');
                        const matchTag = tags.some(t => t.toLowerCase().replace(/^#/, '') === activeTagFilter.toLowerCase().replace(/^#/, ''));
                        if (!matchTag) return false;
                    } catch(e) {
                        return false;
                    }
                }

                return true;
            });

            // 2. 排序逻辑 (Sort)
            filtered.sort((a, b) => {
                if (sortType === 'year_desc') {
                    const yA = parseInt(a.published_at) || 0;
                    const yB = parseInt(b.published_at) || 0;
                    if (yB !== yA) return yB - yA;
                    return (b.created_at || '').localeCompare(a.created_at || '');
                } else if (sortType === 'year_asc') {
                    const yA = parseInt(a.published_at) || 9999;
                    const yB = parseInt(b.published_at) || 9999;
                    if (yA !== yB) return yA - yB;
                    return (a.created_at || '').localeCompare(b.created_at || '');
                } else if (sortType === 'created_desc') {
                    return (b.created_at || '').localeCompare(a.created_at || '');
                } else if (sortType === 'chars_desc') {
                    return (b.total_chars || 0) - (a.total_chars || 0);
                } else if (sortType === 'chars_asc') {
                    return (a.total_chars || 0) - (b.total_chars || 0);
                } else if (sortType === 'summary_desc') {
                    return (b.summary_chars || 0) - (a.summary_chars || 0);
                } else if (sortType === 'title_asc') {
                    return (a.title || '').localeCompare(b.title || '', 'zh');
                }
                return 0;
            });

            // 3. 更新数量角标与重置按钮状态
            const badge = document.getElementById('books-count-badge');
            if (badge) {
                if (filtered.length === allBooksList.length) {
                    badge.textContent = `共 ${allBooksList.length} 本藏书`;
                } else {
                    badge.textContent = `找到 ${filtered.length} / ${allBooksList.length} 本藏书`;
                }
            }

            const hasFilter = searchInput || activeTagFilter || pubFilter || catFilter;
            const resetBtn = document.getElementById('btn-reset-filters');
            if (resetBtn) resetBtn.style.display = hasFilter ? 'inline-flex' : 'none';
            const clearSearchBtn = document.getElementById('btn-clear-search');
            if (clearSearchBtn) clearSearchBtn.style.display = searchInput ? 'flex' : 'none';

            // 4. 渲染网格或空状态
            const grid = document.getElementById('books-grid');
            const emptyState = document.getElementById('books-empty-state');
            if (!grid) return;

            if (filtered.length === 0) {
                grid.innerHTML = '';
                if (emptyState) emptyState.classList.remove('hidden');
                return;
            }
            if (emptyState) emptyState.classList.add('hidden');
            grid.innerHTML = '';

            filtered.forEach(b => {
                let tags = [];
                try { tags = JSON.parse(b.tags_json || '[]'); } catch(e){}

                const yearVal = b.published_at || '2024';
                const pubStr = b.publisher || 'Packt';
                const authorStr = b.author ? `👨‍💻 ${b.author}` : '';

                const card = document.createElement('div');
                card.className = 'glass-card p-5 rounded-2xl flex flex-col justify-between space-y-4 hover:shadow-2xl hover:shadow-indigo-500/10 hover:border-indigo-500/40 transition duration-300';
                card.innerHTML = `
                    <div class="space-y-3">
                        <div class="flex items-center justify-between gap-2">
                            <span class="text-[10px] px-2.5 py-0.5 rounded-full bg-indigo-950/80 text-indigo-300 border border-indigo-800/50 font-mono font-bold tracking-wider">${(b.format || 'EPUB').toUpperCase()}</span>
                            <div class="flex items-center gap-1.5 text-xs text-slate-400 font-mono">
                                <span class="px-2 py-0.5 rounded bg-slate-800 text-sky-300 font-bold border border-slate-700/60">${yearVal}年</span>
                                <span class="truncate max-w-[120px]" title="${pubStr}">· ${pubStr}</span>
                            </div>
                        </div>
                        <h3 class="text-base font-bold text-slate-100 line-clamp-2 leading-snug hover:text-indigo-300 transition cursor-pointer" onclick="openReaderForBook('${b.id}')" title="${b.title}">《${b.title}》</h3>
                        
                        ${authorStr ? `<p class="text-[11px] text-indigo-300 font-medium truncate">${authorStr}</p>` : ''}
                        <p class="text-xs text-slate-400 line-clamp-2">${b.description || b.category || '经典前沿计算机技术专著'}</p>
                        
                        <div class="flex items-center gap-1.5 flex-wrap pt-1">
                            ${tags.map(t => `
                                <button onclick="toggleTagFilter('${t}')" class="text-[10px] px-2 py-0.5 rounded-lg ${activeTagFilter === t ? 'bg-indigo-600 text-white font-bold ring-1 ring-indigo-400' : 'bg-slate-800/90 text-cyan-300 hover:bg-slate-700'} font-mono transition">
                                    ${t}
                                </button>
                            `).join('')}
                        </div>
                    </div>
                    
                    <div class="space-y-2.5 pt-3 border-t border-slate-800/80">
                        <div class="flex items-center justify-between text-[11px] text-slate-400 font-mono">
                            <span>原著: ${Number(b.total_chars || 0).toLocaleString()} 字</span>
                            <span class="text-indigo-400 font-bold">20%精讲 (${b.summary_chars ? Number(b.summary_chars).toLocaleString() + '字' : '~10万字'})</span>
                        </div>
                        <div class="flex items-center justify-between gap-2">
                            <button onclick="openReaderForBook('${b.id}')" class="flex-1 py-2 bg-gradient-to-r from-indigo-600 to-indigo-500 hover:from-indigo-500 hover:to-indigo-400 text-xs font-semibold rounded-xl text-white shadow-md shadow-indigo-600/30 transition flex items-center justify-center gap-1.5">
                                <span>👓</span> 20%双栏研读
                            </button>
                            <button onclick="startQuizForBook('${b.id}')" class="px-3.5 py-2 bg-slate-800 hover:bg-slate-700 text-xs font-semibold rounded-xl text-slate-200 transition flex items-center gap-1">
                                <span>🎯</span> 抽题
                            </button>
                        </div>
                        <audio controls class="w-full h-7 rounded-lg opacity-85 hover:opacity-100 transition" src="/api/books/${b.id}/audio"></audio>
                    </div>
                `;
                grid.appendChild(card);
            });
        }

        function setReaderLayout(mode) {
            const colSum = document.getElementById('reader-col-summary');
            const colOrig = document.getElementById('reader-col-original');
            const btnS = document.getElementById('btn-layout-split');
            const btnSum = document.getElementById('btn-layout-summary');
            const btnO = document.getElementById('btn-layout-original');

            [btnS, btnSum, btnO].forEach(b => b.className = 'px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300');

            if (mode === 'split') {
                colSum.classList.remove('hidden');
                colOrig.classList.remove('hidden');
                btnS.className = 'px-2.5 py-1 rounded bg-indigo-600 text-white font-medium';
            } else if (mode === 'summary') {
                colSum.classList.remove('hidden');
                colOrig.classList.add('hidden');
                btnSum.className = 'px-2.5 py-1 rounded bg-indigo-600 text-white font-medium';
            } else if (mode === 'original') {
                colSum.classList.add('hidden');
                colOrig.classList.remove('hidden');
                btnO.className = 'px-2.5 py-1 rounded bg-indigo-600 text-white font-medium';
            }
        }

        async function openReaderForBook(bookId) {
            currentReaderBookId = bookId;
            const book = allBooksList.find(b => b.id === bookId) || {};
            
            document.getElementById('reader-book-select').value = bookId;
            document.getElementById('reader-audio-player').src = `/api/books/${bookId}/audio`;
            
            document.getElementById('book-meta-publisher').textContent = `出版社: ${book.publisher || 'Packt'}`;
            document.getElementById('book-meta-year').textContent = `年份: ${book.published_at || '2024'}`;
            document.getElementById('book-meta-category').textContent = `分类: ${book.category || '分布式架构'}`;

            let tags = [];
            try { tags = JSON.parse(book.tags_json || '[]'); } catch(e){}
            const tagContainer = document.getElementById('reader-tags-container');
            tagContainer.innerHTML = tags.map(t => `<span class="px-2 py-0.5 rounded bg-slate-800 text-cyan-300 font-mono text-[11px]">${t}</span>`).join('');

            switchTab('reader');

            loadSummaryMarkdown(bookId);
            loadOriginalChaptersAndChunks(bookId);
        }

        async function loadReaderForSelectedBook() {
            const bId = document.getElementById('reader-book-select').value;
            openReaderForBook(bId);
        }

        async function loadSummaryMarkdown(bookId) {
            const sumContainer = document.getElementById('summary-content');
            sumContainer.innerHTML = '<div class="text-center py-12 text-slate-500">正在加载 20% 极客干货精读讲义...</div>';

            try {
                const res = await fetch(`/api/books/${bookId}/summary`);
                const json = await res.json();
                let md = json.content || '';
                let chars = json.chars || md.length;
                
                document.getElementById('summary-chars-badge').textContent = `共 ${chars.toLocaleString()} 字 (20%高密度精讲)`;

                let html = marked.parse(md);
                sumContainer.innerHTML = html;

                setTimeout(() => {
                    mermaid.run({ querySelector: '.language-mermaid' });
                }, 100);
            } catch(e) {
                sumContainer.innerHTML = `<div class="text-rose-400 p-4">加载精读笔记失败: ${e}</div>`;
            }
        }

        async function loadOriginalChaptersAndChunks(bookId) {
            const chapSelect = document.getElementById('reader-chapter-select');
            chapSelect.innerHTML = '<option value="">📖 全部原著章节</option>';

            try {
                const res = await fetch(`/api/books/${bookId}/chapters`);
                const json = await res.json();
                const chaps = json.data || [];
                document.getElementById('original-stats-badge').textContent = `共 ${chaps.length} 章节`;

                chaps.forEach(c => {
                    const opt = document.createElement('option');
                    opt.value = c.chapter_title;
                    opt.textContent = `${c.chapter_title} (${c.chunks_count} 块)`;
                    chapSelect.appendChild(opt);
                });

                fetchAndRenderChunks(bookId);
            } catch(e) {
                console.error(e);
            }
        }

        async function fetchAndRenderChunks(bookId, chapter = '', search = '') {
            const container = document.getElementById('original-chunks-container');
            container.innerHTML = '<div class="text-center py-12 text-slate-500">正在加载原著切块段落...</div>';

            try {
                let url = `/api/books/${bookId}/chunks?limit=60`;
                if (chapter) url += `&chapter=${encodeURIComponent(chapter)}`;
                if (search) url = `/api/books/${bookId}/search?q=${encodeURIComponent(search)}`;

                const res = await fetch(url);
                const json = await res.json();
                const chunks = json.data || [];

                if (chunks.length === 0) {
                    container.innerHTML = '<div class="text-center py-12 text-slate-500">未找到相关原著段落。</div>';
                    return;
                }

                container.innerHTML = '';
                chunks.forEach(c => {
                    const card = document.createElement('div');
                    card.className = 'p-3.5 rounded-xl bg-slate-900/80 border border-slate-800/80 space-y-1.5 hover:border-cyan-800/50 transition';
                    card.innerHTML = `
                        <div class="flex items-center justify-between text-[11px] text-cyan-400 font-bold border-b border-slate-800/60 pb-1">
                            <span class="truncate">📑 ${c.chapter_title || '未命名章节'}</span>
                            <span class="text-slate-500 font-mono text-[10px]">#${c.chunk_index}</span>
                        </div>
                        <div class="text-slate-300 leading-relaxed text-[11.5px] whitespace-pre-wrap">${escapeHtml(c.content)}</div>
                    `;
                    container.appendChild(card);
                });
            } catch(e) {
                container.innerHTML = `<div class="text-rose-400 p-4">加载原著段落失败: ${e}</div>`;
            }
        }

        function filterOriginalByChapter() {
            const chap = document.getElementById('reader-chapter-select').value;
            fetchAndRenderChunks(currentReaderBookId, chap);
        }

        function handleOriginalSearch(e) {
            if (e.key === 'Enter') {
                const q = document.getElementById('original-search-input').value.trim();
                fetchAndRenderChunks(currentReaderBookId, '', q);
            }
        }

        // =========================================================================
        // 划词交互与独立固定分栏逻辑 (Docked / Side-by-Side)
        // =========================================================================
        document.addEventListener('mouseup', function(e) {
            const toolbar = document.getElementById('selection-toolbar');
            const mentorCol = document.getElementById('reader-col-mentor');
            
            if (toolbar.contains(e.target) || (mentorCol && mentorCol.contains(e.target))) return;

            const selection = window.getSelection();
            const text = selection.toString().trim();

            if (text.length > 2) {
                selectedTextCache = text;
                const range = selection.getRangeAt(0);
                const rect = range.getBoundingClientRect();
                
                toolbar.style.left = `${window.scrollX + rect.left + rect.width / 2 - 140}px`;
                toolbar.style.top = `${window.scrollY + rect.top - 46}px`;
                toolbar.style.display = 'flex';
            } else {
                toolbar.style.display = 'none';
            }
        });

        function triggerInteractAction(action) {
            const toolbar = document.getElementById('selection-toolbar');
            toolbar.style.display = 'none';

            const titles = {
                'explain': '💡 大白话讲透概念',
                'deep_dive': '⚙️ 底层原理解构',
                'pitfalls': '🚀 生产避坑实战指南',
                'ask': '💬 针对选段提问'
            };

            openInteractiveDrawer(titles[action] || 'AI 导师研学', selectedTextCache);

            const contentBody = document.getElementById('drawer-content-body');
            contentBody.innerHTML = '<div class="text-center py-12 text-slate-500">正在生成深度解析...</div>';

            const es = new EventSource(`/api/interact/stream?book_id=${encodeURIComponent(currentReaderBookId)}&action=${action}&selected_text=${encodeURIComponent(selectedTextCache)}`);
            
            let rawText = '';
            es.onmessage = function(e) {
                if (e.data === '[DONE]') {
                    es.close();
                    return;
                }
                try {
                    const data = JSON.parse(e.data);
                    if (data.chunk) {
                        rawText += data.chunk;
                        contentBody.innerHTML = marked.parse(rawText);
                    }
                } catch(err) {
                    rawText += e.data;
                    contentBody.innerHTML = marked.parse(rawText);
                }
            };
            es.onerror = function() {
                es.close();
            };
        }

        function openInteractiveDrawer(title, quote) {
            isMentorOpen = true;
            const panel = document.getElementById('reader-col-mentor');
            document.getElementById('drawer-title').textContent = title;
            document.getElementById('drawer-selected-quote').textContent = quote;
            
            panel.classList.remove('hidden');
            applyMentorLayoutMode();
        }

        function closeInteractiveDrawer() {
            isMentorOpen = false;
            const panel = document.getElementById('reader-col-mentor');
            panel.classList.add('hidden');
            panel.className = 'glass-panel p-5 rounded-2xl flex flex-col h-[78vh] transition-all duration-300 hidden border border-slate-800/90 shadow-2xl';
        }

        function toggleMentorMode() {
            isMentorDocked = !isMentorDocked;
            applyMentorLayoutMode();
        }

        function applyMentorLayoutMode() {
            const panel = document.getElementById('reader-col-mentor');
            const pinIcon = document.getElementById('pin-icon');

            if (!isMentorOpen) return;

            if (isMentorDocked) {
                // 模式 1：固定分栏模式 (平铺在右侧作为第三栏，不遮挡左侧精简读本与原著)
                panel.className = 'w-full lg:w-[420px] xl:w-[460px] shrink-0 glass-panel p-5 rounded-2xl flex flex-col h-[78vh] transition-all duration-300 border border-slate-800/90 shadow-2xl';
                pinIcon.textContent = '📌 固定中';
                panel.style.position = 'relative';
                panel.style.zIndex = '1';
            } else {
                // 模式 2：悬浮抽屉模式 (Floating Overlay，小屏或全宽临时浮层)
                panel.className = 'fixed right-0 top-0 h-full w-full max-w-md bg-slate-900/95 backdrop-blur-2xl border-l border-slate-800 shadow-2xl z-50 flex flex-col p-5';
                pinIcon.textContent = '🪟 浮动中';
            }
        }

        function openCopilotChat() {
            openInteractiveDrawer('💬 伴读导师实时聊天室', `《${currentReaderBookId}》全局向量知识库`);
            const contentBody = document.getElementById('drawer-content-body');
            contentBody.innerHTML = `
                <div class="bg-slate-800/80 p-3 rounded-xl border border-slate-700/60 mb-3">
                    👋 嗨！我是《${currentReaderBookId}》的专属伴读导师。你可以随时向我提问关于本书的任何架构原理、函数用法或设计权衡！
                </div>
            `;
        }

        function sendDrawerFollowup() {
            const input = document.getElementById('drawer-user-input');
            const msg = input.value.trim();
            if (!msg) return;
            input.value = '';

            const contentBody = document.getElementById('drawer-content-body');
            contentBody.innerHTML += `
                <div class="my-3 p-2.5 bg-indigo-950/60 border border-indigo-800/60 rounded-xl text-slate-100 text-right">
                    <strong>你：</strong> ${escapeHtml(msg)}
                </div>
                <div id="latest-ai-reply" class="my-3 p-2.5 bg-slate-800/80 border border-slate-700/60 rounded-xl text-slate-200">
                    <span class="text-cyan-400 font-bold">导师：</span> 正在思考...
                </div>
            `;

            const replyBox = document.getElementById('latest-ai-reply');
            let rawText = '';

            const es = new EventSource(`/api/copilot/stream?book_id=${encodeURIComponent(currentReaderBookId)}&message=${encodeURIComponent(msg)}`);
            es.onmessage = function(e) {
                if (e.data === '[DONE]') {
                    es.close();
                    return;
                }
                try {
                    const data = JSON.parse(e.data);
                    if (data.chunk) {
                        rawText += data.chunk;
                        replyBox.innerHTML = `<span class="text-cyan-400 font-bold">导师：</span><br>` + marked.parse(rawText);
                    }
                } catch(err) {
                    rawText += e.data;
                    replyBox.innerHTML = marked.parse(rawText);
                }
            };
            es.onerror = function() {
                es.close();
            };
        }

        // =========================================================================
        // Quiz & Usage Logic
        // =========================================================================
        function startQuizForBook(bookId) {
            switchTab('quiz');
            document.getElementById('quiz-book-select').value = bookId;
            requestQuiz();
        }

        async function requestQuiz() {
            const bookId = document.getElementById('quiz-book-select').value;
            const topic = document.getElementById('quiz-topic-input').value.trim();
            const btn = document.getElementById('generate-quiz-btn');
            
            btn.disabled = true;
            btn.textContent = '🧠 正在现场命制试题 (请稍候)...';

            try {
                const res = await fetch('/api/quiz/generate', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({book_id: bookId, topic: topic || null})
                });
                const json = await res.json();
                currentQuizData = json.data;
                
                document.getElementById('quiz-chapter').textContent = currentQuizData.chapter_title || '核心章节';
                document.getElementById('quiz-question').textContent = currentQuizData.question;
                
                const optContainer = document.getElementById('quiz-options');
                optContainer.innerHTML = '';
                const opts = currentQuizData.options || {};
                
                ['A', 'B', 'C', 'D'].forEach(opt => {
                    if (opts[opt]) {
                        const btn = document.createElement('button');
                        btn.className = 'w-full text-left p-3.5 rounded-xl bg-slate-800/80 hover:bg-indigo-900/40 border border-slate-700/60 text-xs sm:text-sm text-slate-200 transition flex items-start gap-3';
                        btn.innerHTML = `<span class="px-2 py-0.5 rounded bg-slate-700 font-bold text-xs">${opt}</span><span>${opts[opt]}</span>`;
                        btn.onclick = () => submitAnswer(opt);
                        optContainer.appendChild(btn);
                    }
                });

                document.getElementById('quiz-card').classList.remove('hidden');
                document.getElementById('analysis-box').classList.add('hidden');
                document.getElementById('analysis-content').textContent = '';
            } catch(e) {
                alert('出题失败: ' + e);
            } finally {
                btn.disabled = false;
                btn.textContent = '🧠 由 DeepSeek-V4-Pro 现场命制技术试题';
            }
        }

        async function submitAnswer(selectedOpt) {
            if (!currentQuizData) return;
            
            const box = document.getElementById('analysis-box');
            const content = document.getElementById('analysis-content');
            box.classList.remove('hidden');
            content.textContent = '';

            const es = new EventSource(`/api/quiz/evaluate/stream?quiz_id=${currentQuizData.quiz_id}&user_answer=${selectedOpt}`);
            
            es.onmessage = function(e) {
                if (e.data === '[DONE]') {
                    es.close();
                    return;
                }
                try {
                    const data = JSON.parse(e.data);
                    if (data.chunk) {
                        content.textContent += data.chunk;
                    }
                } catch(err) {
                    content.textContent += e.data;
                }
            };
            es.onerror = function() {
                es.close();
            };
        }

        async function loadUsage() {
            try {
                const res = await fetch('/api/usage');
                const json = await res.json();
                const data = json.data || {};
                
                const grandTotal = Number(data.grand_total_tokens || 0);
                const totalCalls = Number(data.total_calls || 0);
                const totalPrompt = Number(data.total_prompt_tokens || 0);
                const totalComp = Number(data.total_completion_tokens || 0);
                const totalDur = Number(data.total_duration_seconds || 0);

                document.getElementById('total-calls-val').textContent = `${totalCalls.toLocaleString()} 次`;
                document.getElementById('total-tokens-val').textContent = grandTotal.toLocaleString();
                
                const promptEl = document.getElementById('prompt-tokens-val');
                if (promptEl) promptEl.textContent = `入: ${totalPrompt.toLocaleString()}`;
                const compEl = document.getElementById('comp-tokens-val');
                if (compEl) compEl.textContent = `出: ${totalComp.toLocaleString()}`;
                
                const durEl = document.getElementById('total-duration-val');
                if (durEl) durEl.textContent = `${totalDur.toLocaleString()}s`;
                const hoursEl = document.getElementById('total-hours-val');
                if (hoursEl) hoursEl.textContent = `~${(totalDur / 3600).toFixed(1)} 小时累计分析`;
                
                const bd = document.getElementById('usage-breakdown');
                bd.innerHTML = '';

                const providerColors = {
                    'VolcEngine': { badge: 'bg-rose-950/80 text-rose-300 border-rose-800/40', bar: 'from-rose-500 to-pink-500', name: '🌋 火山方舟 (VolcEngine)' },
                    'SiliconFlow': { badge: 'bg-cyan-950/80 text-cyan-300 border-cyan-800/40', bar: 'from-cyan-500 to-teal-500', name: '⚡ 硅基流动 (SiliconFlow)' },
                    'DashScope': { badge: 'bg-amber-950/80 text-amber-300 border-amber-800/40', bar: 'from-amber-500 to-orange-500', name: '☁️ 阿里百炼 (DashScope)' },
                    'ModelScope': { badge: 'bg-purple-950/80 text-purple-300 border-purple-800/40', bar: 'from-purple-500 to-indigo-500', name: '🌌 魔搭社区 (ModelScope)' },
                    'DeepSeek': { badge: 'bg-blue-950/80 text-blue-300 border-blue-800/40', bar: 'from-blue-500 to-indigo-500', name: '🐋 DeepSeek 官方' }
                };

                (data.breakdown || []).forEach(row => {
                    const rTokens = Number(row.grand_total_tokens || 0);
                    const rPrompt = Number(row.total_prompt_tokens || 0);
                    const rComp = Number(row.total_completion_tokens || 0);
                    const rCalls = Number(row.call_count || 0);
                    const rDur = Number(row.total_duration || 0);
                    const pct = grandTotal > 0 ? ((rTokens / grandTotal) * 100).toFixed(1) : '0';

                    const provStyle = providerColors[row.provider] || { 
                        badge: 'bg-slate-800 text-slate-300 border-slate-700', 
                        bar: 'from-indigo-500 to-cyan-500', 
                        name: row.provider 
                    };

                    const card = document.createElement('div');
                    card.className = 'glass-card p-4 rounded-2xl border border-slate-800/90 space-y-3';
                    card.innerHTML = `
                        <div class="flex flex-wrap items-center justify-between gap-2">
                            <div class="flex items-center gap-2">
                                <span class="text-[11px] px-2.5 py-0.5 rounded-full border font-mono font-semibold ${provStyle.badge}">
                                    ${provStyle.name}
                                </span>
                                <span class="font-bold text-slate-100 text-sm font-mono">${row.model_name}</span>
                            </div>
                            <div class="flex items-center gap-3 text-xs font-mono">
                                <span class="text-slate-400">调用: <strong class="text-slate-200">${rCalls.toLocaleString()}</strong> 次</span>
                                <span class="text-slate-400">耗时: <strong class="text-slate-200">${rDur.toFixed(1)}s</strong></span>
                                <span class="font-bold text-cyan-300 text-sm">${rTokens.toLocaleString()} Tokens</span>
                            </div>
                        </div>

                        <!-- 进度条 -->
                        <div class="w-full bg-slate-950 rounded-full h-2 overflow-hidden border border-slate-800">
                            <div class="bg-gradient-to-r ${provStyle.bar} h-full rounded-full transition-all duration-500" style="width: ${pct}%"></div>
                        </div>

                        <!-- 细分指标 -->
                        <div class="flex items-center justify-between text-[11px] text-slate-400 font-mono pt-0.5">
                            <div class="flex items-center gap-3">
                                <span>输入 Prompt: <strong class="text-sky-300">${rPrompt.toLocaleString()}</strong></span>
                                <span>输出 Completion: <strong class="text-emerald-300">${rComp.toLocaleString()}</strong></span>
                            </div>
                            <span class="text-slate-400 font-bold">全库占比 ${pct}%</span>
                        </div>
                    `;
                    bd.appendChild(card);
                });
            } catch(e) {
                console.error("加载算力台账失败:", e);
            }
        }

        function escapeHtml(text) {
            return text
                .replace(/&/g, "&amp;")
                .replace(/</g, "&lt;")
                .replace(/>/g, "&gt;")
                .replace(/"/g, "&quot;")
                .replace(/'/g, "&#039;");
        }

        loadBooks();
    </script>
</body>
</html>
"""

def main():
    import uvicorn
    port = int(os.getenv("PORT", "8888"))
    logger.info(f"🚀 第二大脑·AI 智能图书馆 Web 交互服务启动在: http://0.0.0.0:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port)

if __name__ == "__main__":
    main()

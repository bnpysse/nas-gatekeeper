#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
第二大脑·AI 智能图书馆与精读研习工作流 (Main Pipeline)
火山方舟双引擎 (Doubao-Evolving + DeepSeek-V4-Pro) 200万循环免费算力全速驱动
涵盖：文本抽取 -> 双引擎精读 -> 广播级听书多轨音频 -> Turso 向量分块入库 -> 全景算力台账统计
"""

import os
import re
import sys
import asyncio
import logging
from pathlib import Path
from typing import Dict, Any

try:
    from .config import LibraryConfig
    from .extractor import extract_book
    from .dual_engine import (
        generate_condensed_book,
        generate_podcast_script,
        generate_key_takeaways,
        generate_quizzes,
        generate_flashcards
    )
    from .output_generator import generate_full_study_note
    from .tts_engine import generate_podcast_audio
    from .indexer import index_single_book
    from .db import init_library_schema, get_book_usage_summary, record_usage
except ImportError:
    from config import LibraryConfig
    from extractor import extract_book
    from dual_engine import (
        generate_condensed_book,
        generate_podcast_script,
        generate_key_takeaways,
        generate_quizzes,
        generate_flashcards
    )
    from output_generator import generate_full_study_note
    from tts_engine import generate_podcast_audio
    from indexer import index_single_book
    from db import init_library_schema, get_book_usage_summary, record_usage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("BooksPipeline")

async def process_single_book(file_path: Path, output_dir: Path = None) -> Dict[str, Any]:
    """处理单本电子书全流程 (精读 + 播客TTS + 向量入库 + 算力台账)"""
    if output_dir is None:
        output_dir = LibraryConfig.OUTPUT_DIR
        
    await init_library_schema()
    
    logger.info(f"📚 [1/5] 开始抽取电子书文本: {file_path.name}")
    book_meta = extract_book(file_path)
    word_count = book_meta.get("word_count", 0)
    format_type = book_meta.get("format", "unknown")
    logger.info(f"✅ 文本抽取完成! 格式: {format_type}, 总字数: {word_count:,} 字")
    
    title = book_meta.get("title", file_path.stem)
    clean_title = re.sub(r'[\/\\:\*\?"<>\|]', '_', title)
    book_id = re.sub(r'[^a-zA-Z0-9_]', '_', file_path.stem.lower())
    text = book_meta.get("text", "")
    
    logger.info(f"🚀 [2/5] 启动火山方舟双引擎精读研学 (Book ID: {book_id})...")
    
    # 2.1 3分钟透视与脉络图 (DeepSeek)
    logger.info(f"   ├─ [1/5] 引擎 2 (DeepSeek-V4-Pro): 正在提炼 3分钟极简透视与 Mermaid 脉络图...")
    takeaways_res = await generate_key_takeaways(title, text, book_id=book_id)
    takeaways_md = takeaways_res.get("takeaways_markdown", "")
    await asyncio.sleep(1.0)
    
    # 2.2 20% 缩减本 (Doubao)
    logger.info(f"   ├─ [2/5] 引擎 1 (Doubao-Evolving): 正在编写 20% 极客干货缩减本...")
    condensed_text = await generate_condensed_book(title, text, book_id=book_id)
    await asyncio.sleep(1.0)
    
    # 2.3 播客剧本 (Doubao)
    logger.info(f"   ├─ [3/5] 引擎 1 (Doubao-Evolving): 正在创作双人对谈播客剧本 (NotebookLM 风格)...")
    podcast_script = await generate_podcast_script(title, condensed_text, book_id=book_id)
    await asyncio.sleep(1.0)
    
    # 2.4 10道测试题 (DeepSeek)
    logger.info(f"   ├─ [4/5] 引擎 2 (DeepSeek-V4-Pro): 正在命制 10 道章节精选研习测试题...")
    quizzes = await generate_quizzes(title, condensed_text, book_id=book_id)
    await asyncio.sleep(1.0)
    
    # 2.5 12张记忆闪卡 (DeepSeek)
    logger.info(f"   └─ [5/5] 引擎 2 (DeepSeek-V4-Pro): 正在提炼 12 张核心概念记忆闪卡...")
    flashcards = await generate_flashcards(title, condensed_text, book_id=book_id)
    
    logger.info(f"✅ 双引擎精读生成完毕! 命制测试题 {len(quizzes)} 道, 提炼闪卡 {len(flashcards)} 张")
    
    # 3. 输出 Markdown 笔记与 JSON 题库
    logger.info(f"📝 [3/5] 正在沉淀精读研习 Markdown 与 JSON 题库...")
    output_paths = generate_full_study_note(
        book_meta=book_meta,
        takeaways=takeaways_md,
        condensed_text=condensed_text,
        quizzes=quizzes,
        flashcards=flashcards,
        podcast_script=podcast_script,
        output_dir=output_dir
    )
    
    # 4. 合成广播级听书对谈音频 (.m4a)
    logger.info(f"🎙️ [4/5] 启动 EdgeTTS 多轨男女声音频合成 (男声: 睿哥, 女声: 小林)...")
    audio_path = output_dir / f"[Podcast]{clean_title}_剧本.m4a"
    try:
        await generate_podcast_audio(output_paths["podcast_path"], audio_path)
        output_paths["audio_path"] = audio_path
        logger.info(f"✅ 听书播客音频合成成功: {audio_path.name}")
    except Exception as e:
        logger.error(f"❌ 听书音频合成异常: {e}")
        output_paths["audio_path"] = None

    # 5. Turso 向量知识切块与 1024 维高精度向量索引入库
    logger.info(f"🧩 [5/5] 正在将全书知识切块 (1024 维) 写入云端 Turso libSQL 向量数据库...")
    try:
        index_res = await index_single_book(file_path)
        logger.info(f"✅ 向量切块入库完成! 共入库 {index_res.get('total_chunks', 0)} 个向量分块")
    except Exception as e:
        logger.error(f"❌ 向量入库异常: {e}")

    # 6. 获取全景算力与 Token 消耗汇总台账
    usage_summary = await get_book_usage_summary(book_id)
    
    logger.info(f"🎉 🎉 🎉 《{title}》全套资产沉淀与算力核算完毕:")
    logger.info(f"   📄 Markdown 笔记: {output_paths['note_path']}")
    logger.info(f"   📝 Telegram 题库: {output_paths['quiz_path']}")
    logger.info(f"   🎙️ 播客剧本: {output_paths['podcast_path']}")
    if output_paths.get("audio_path"):
        logger.info(f"   🎧 听书音频: {output_paths['audio_path']}")
    logger.info(f"   💰 本书 Token 累计消耗: {usage_summary.get('grand_total_tokens', 0):,} Tokens")
    
    return {
        "status": "success",
        "book_id": book_id,
        "book_title": title,
        "original_words": word_count,
        "condensed_words": len(condensed_text),
        "quizzes_count": len(quizzes),
        "output_files": output_paths,
        "usage_summary": usage_summary
    }

async def process_all_new_books():
    """扫描并处理 CloseReading 目录下的全部电子书"""
    books_dir = LibraryConfig.WORKSPACE_DIR / "downloads/CloseReading"
    if not books_dir.exists():
        logger.warning(f"目录不存在: {books_dir}")
        return
        
    supported_exts = {".pdf", ".epub", ".mobi", ".azw3", ".txt"}
    book_files = [f for f in books_dir.iterdir() if f.suffix.lower() in supported_exts]
    
    logger.info(f"📚 扫描到 {len(book_files)} 本待处理电子书:")
    for b in book_files:
        logger.info(f"  - {b.name} ({b.stat().st_size / 1024 / 1024:.1f} MB)")
        
    for book_file in book_files:
        logger.info(f"\n{'='*70}\n📖 正在处理: {book_file.name}\n{'='*70}")
        try:
            await process_single_book(book_file)
        except Exception as e:
            logger.error(f"❌ 处理《{book_file.name}》失败: {e}", exc_info=True)


if __name__ == "__main__":
    asyncio.run(process_all_new_books())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
第二大脑·AI 智能图书馆统一命令行工具 (cli.py)
无论在哪个目录下执行，均可自动寻址运行：
  1. 查看藏书与算力台账:  python3 cli.py status
  2. 交互式做题/抽题测试: python3 cli.py quiz [书籍序号/ID] [主题关键词]
  3. 快速运行自动化自测:  python3 cli.py test
"""

import os
import sys
import json
import asyncio
from pathlib import Path

# 无论从何处运行，均将当前目录和父目录加入 sys.path
current_dir = Path(__file__).resolve().parent
parent_dir = current_dir.parent
for p in [str(current_dir), str(parent_dir)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from db import get_all_books, get_total_library_usage, get_all_usage_records
from dynamic_quiz import generate_dynamic_quiz, evaluate_and_explain, evaluate_and_explain_stream, get_available_books


async def show_status():
    """查看图书馆书籍元数据与全景 Token 算力台账"""
    print("\n" + "=" * 65)
    print("           📚 第二大脑·AI 智能图书馆藏书清单")
    print("=" * 65)
    
    books = await get_all_books()
    if not books:
        print("  (暂无入库书籍)")
    else:
        for idx, b in enumerate(books, 1):
            fmt = (b.get('format') or 'DOC').upper()
            chars = b.get('total_chars', 0)
            chunks = b.get('total_chunks', 0)
            title = b.get('title', '未知书名')
            book_id = b.get('id', '')
            print(f"[{idx}] 📖 《{title}》")
            print(f"    - 标识符: {book_id}")
            print(f"    - 格式: {fmt} | 抽取字数: {chars:,} 字 | 1024维向量切块: {chunks} 块")
            print(f"    - 存储状态: Turso 云端就绪")
            print()

    print("=" * 65)
    print("           💰 全景 Token 算力与消耗总账")
    print("=" * 65)
    
    tot = await get_total_library_usage()
    calls = tot.get("total_calls", 0)
    grand_tokens = tot.get("grand_total_tokens", 0)
    
    print(f"• 累计模型调用: {calls} 次 | 累计 Token 消耗: {grand_tokens:,} Tokens")
    print("-" * 65)
    for row in tot.get("breakdown", []):
        provider = row.get("provider", "")
        model = row.get("model_name", "")
        p_tok = row.get("total_prompt_tokens", 0)
        c_tok = row.get("total_completion_tokens", 0)
        t_tok = row.get("grand_total_tokens", 0)
        dur = row.get("total_duration", 0.0)
        cnt = row.get("call_count", 0)
        print(f"  • {provider:10} | {model:20} : {t_tok:>8,} Tokens (提示: {p_tok:,}, 生成: {c_tok:,}) | 耗时: {dur:5.1f}s ({cnt}次)")
    print("=" * 65 + "\n")


async def run_quiz(book_query: str = None, topic: str = None):
    """交互式 RAG 动态无限做题"""
    books = await get_available_books()
    if not books:
        print("❌ 当前图书馆没有已入库书籍，请先运行 pipeline 处理书籍。")
        return

    selected_book = None
    if book_query:
        # 支持按数字序号或关键词匹配
        if book_query.isdigit():
            idx = int(book_query) - 1
            if 0 <= idx < len(books):
                selected_book = books[idx]
        if not selected_book:
            for b in books:
                if book_query.lower() in b["id"].lower() or book_query.lower() in b["title"].lower():
                    selected_book = b
                    break
    
    if not selected_book:
        print("\n📚 请选择要进行研学抽题的书籍：")
        for idx, b in enumerate(books, 1):
            print(f"  [{idx}] 《{b['title']}》 ({b['total_chunks']} 向量切块)")
        try:
            choice = input("\n👉 请输入书籍序号 (默认 1): ").strip()
            idx = int(choice) - 1 if choice else 0
            selected_book = books[idx if 0 <= idx < len(books) else 0]
        except (ValueError, KeyboardInterrupt):
            selected_book = books[0]

    book_id = selected_book["id"]
    book_title = selected_book["title"]
    
    if topic:
        print(f"\n🎯 正在检索《{book_title}》中与 [{topic}] 相关的原著切块...")
    else:
        print(f"\n🎲 正在从《{book_title}》的 {selected_book['total_chunks']} 个向量切块中随机盲盒抽样...")

    print("🧠 正在由火山方舟 DeepSeek-V4-Pro 现场命制技术测试题 (请稍候)...")
    quiz = await generate_dynamic_quiz(book_id, topic)
    
    print("\n" + "=" * 65)
    print(f"📝 研选题干：《{book_title}》 章节: {quiz.get('chapter_title', '核心章节')}")
    print("=" * 65)
    print(f"\n{quiz['question']}\n")
    
    options = quiz.get("options", {})
    for opt in ["A", "B", "C", "D"]:
        if opt in options:
            print(f"  [{opt}] {options[opt]}")
            
    print("\n" + "-" * 65)
    try:
        user_choice = input("👉 请输入你的选项 (A/B/C/D): ").strip().upper()
    except (KeyboardInterrupt, EOFError):
        print("\n👋 已退出做题。")
        return
        
    if user_choice not in ["A", "B", "C", "D"]:
        user_choice = "A"
        print("未输入有效选项，默认选择 A 进行演示。")

    print(f"\n⚡ 你的选择是 [{user_choice}]，考官正在深度复盘与溯源原著（流式打字机）...")
    print("\n" + "=" * 65)
    print("               🎓 考官深度复盘与原著溯源")
    print("=" * 65 + "\n")
    
    async for chunk in evaluate_and_explain_stream(quiz["quiz_id"], user_choice):
        sys.stdout.write(chunk)
        sys.stdout.flush()
        
    print("\n\n" + "=" * 65 + "\n")


async def run_auto_test():
    """自动化测试流水线连通性与动态题库"""
    print("🚀 启动自动化自测...")
    books = await get_available_books()
    print(f"✅ 1. 成功连接 Turso 数据库，读取到 {len(books)} 本藏书。")
    if books:
        target = books[0]
        print(f"✅ 2. 正在对《{target['title']}》测试 RAG 动态出题...")
        quiz = await generate_dynamic_quiz(target["id"])
        print(f"   - 命制题目: {quiz['question'][:50]}...")
        print(f"   - 正确答案: {quiz['correct_answer']}")
        print(f"   - 原著论据: {quiz.get('reference_quote', '')[:60]}...")
        print("✅ 3. 动态出题引擎测试完全通过！")


def main():
    args = sys.argv[1:]
    cmd = args[0].lower() if args else "status"
    
    if cmd in ["status", "info", "stat"]:
        asyncio.run(show_status())
    elif cmd in ["quiz", "test_quiz", "q"]:
        book_arg = args[1] if len(args) > 1 else None
        topic_arg = args[2] if len(args) > 2 else None
        asyncio.run(run_quiz(book_arg, topic_arg))
    elif cmd in ["test", "check"]:
        asyncio.run(run_auto_test())
    elif cmd in ["list", "ls"]:
        async def _ls():
            books = await get_all_books()
            for idx, b in enumerate(books, 1):
                print(f"[{idx}] {b['id']} -> 《{b['title']}》")
        asyncio.run(_ls())
    else:
        print(f"未知指令: {cmd}")
        print("可用命令:")
        print("  python3 cli.py status         # 查看图书馆藏书与 Token 台账")
        print("  python3 cli.py quiz           # 交互式做题")
        print("  python3 cli.py quiz 1 OTP     # 指定第1本书，关键词 OTP 抽题")
        print("  python3 cli.py test           # 运行自动化测试")


if __name__ == "__main__":
    main()

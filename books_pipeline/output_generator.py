#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
精读研习成果生成器
输出 Obsidian / Quartz 5 兼容的精读笔记、Telegram 交互做题 JSON 题库与播客剧本
"""

import json
from pathlib import Path
from typing import Dict, Any, List
from datetime import datetime

def format_quiz_markdown(quizzes: List[Dict[str, Any]]) -> str:
    """将题库格式化为带有交互折叠卡片的 Markdown"""
    lines = []
    type_map = {"single": "单选题", "multiple": "多选题", "case": "实战案例题"}
    
    for i, q in enumerate(quizzes):
        q_type = type_map.get(q.get("type", "single"), "选择题")
        q_text = q.get("question", "")
        options = q.get("options", [])
        ans = q.get("correct_answer", "")
        source = q.get("chapter_source", "原书相关章节")
        analysis = q.get("analysis", "")
        
        lines.append(f"#### 📝 第 {i+1} 题 ({q_type})：{q_text}\n")
        for opt in options:
            lines.append(f"- [ ] {opt}")
        lines.append("")
        
        lines.append("<details>")
        lines.append("<summary><b>👉 点击查看【正确答案与深度解析】</b></summary>\n")
        lines.append(f"> **✅ 正确答案**：`{ans}`  ")
        lines.append(f"> **📍 原著出处**：`{source}`  ")
        lines.append(f">\n> **💡 深度解析**：\n> {analysis}\n")
        lines.append("</details>\n")
        lines.append("---\n")
        
    return "\n".join(lines)

def format_flashcards_markdown(flashcards: List[Dict[str, str]]) -> str:
    """将闪卡格式化为 Anki / 翻转卡片 Markdown"""
    lines = []
    for i, card in enumerate(flashcards):
        front = card.get("front", "")
        back = card.get("back", "")
        tag = card.get("tag", "核心概念")
        lines.append(f"**🃏 卡片 {i+1} [{tag}]**")
        lines.append(f"> **Q（问题）**: {front}  ")
        lines.append(f"> **A（答案）**: {back}\n")
    return "\n".join(lines)

def generate_full_study_note(
    book_meta: Dict[str, Any],
    takeaways: str,
    condensed_text: str,
    quizzes: List[Dict[str, Any]],
    flashcards: List[Dict[str, str]],
    podcast_script: str,
    output_dir: Path
) -> Dict[str, Path]:
    """生成全套精读输出物"""
    output_dir.mkdir(parents=True, exist_ok=True)
    title = book_meta.get("title", "未命名书籍")
    clean_title = title.replace("/", "_").replace("\\", "_")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # 1. 完整 Markdown 精读笔记 (Obsidian & Quartz 5)
    quizzes_md = format_quiz_markdown(quizzes)
    flashcards_md = format_flashcards_markdown(flashcards)
    
    md_content = f"""---
title: "《{title}》极客精读缩减本与研习题库"
date: "{now_str}"
tags:
  - secondbrain/library
  - book/condensed
  - study/quiz
format: {book_meta.get('format', 'unknown')}
original_words: {book_meta.get('word_count', 0)}
condensed_words: {len(condensed_text)}
compression_ratio: "{len(condensed_text) / max(1, book_meta.get('word_count', 1)) * 100:.1f}%"
---

# 📚 《{title}》极客精读缩减本与研习研学

> [!INFO] 书籍元数据
> - **原著总字数**: `{book_meta.get('word_count', 0):,} 字`
> - **干货缩减本**: `{len(condensed_text):,} 字` (压缩率: `{len(condensed_text) / max(1, book_meta.get('word_count', 1)) * 100:.1f}%`)
> - **双引擎算力**: `Doubao-Evolving (结构去水) + DeepSeek-V4-Pro (深度题解)`
> - **生成时间**: `{now_str}`

---

## 🎧 双人对谈听书音频 (Audio Overview)
> 💡 *本期双人播客对谈由火山方舟大模型重构编剧，通勤散步随时听懂整本书！*
> *(音频合成中 / 点击可播放配套音频)*

---

## 🔍 第一部分：3分钟极简透视与知识脉络
{takeaways}

---

## 📖 第二部分：20%~25% 精华干货缩减本 (去水留精)
{condensed_text}

---

## 🎯 第三部分：章节精选研习测试题库 (交互答题)
{quizzes_md}

---

## 🧠 第四部分：核心概念记忆闪卡 (Anki / 艾宾浩斯)
{flashcards_md}

---

## 🎙️ 第五部分：双人对谈听书播客完整剧本
{podcast_script}
"""

    note_path = output_dir / f"[Book]{clean_title}_精读研习.md"
    note_path.write_text(md_content, encoding="utf-8")
    
    # 2. 独立 Telegram 交互题库 JSON
    quiz_path = output_dir / f"[Quiz]{clean_title}_题库.json"
    quiz_payload = {
        "book_title": title,
        "generated_at": now_str,
        "total_quizzes": len(quizzes),
        "quizzes": quizzes
    }
    quiz_path.write_text(json.dumps(quiz_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    
    # 3. 独立播客剧本
    podcast_path = output_dir / f"[Podcast]{clean_title}_剧本.md"
    podcast_path.write_text(podcast_script, encoding="utf-8")
    
    return {
        "note_path": note_path,
        "quiz_path": quiz_path,
        "podcast_path": podcast_path
    }

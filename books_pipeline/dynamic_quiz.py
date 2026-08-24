#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
第二大脑·AI 智能图书馆：RAG 动态无限出题与智能题解引擎 (`dynamic_quiz.py`)
支持：
1. 随机盲盒抽题 (Random Chunk)
2. 专题定向出题 (Vector Similarity via Turso / DashScope)
3. 动态智能排查解析 (DeepSeek-V4-Pro 现场根据用户作答与原书段落生成个性化错因诊断与原著引用)
4. 个人做题记录与错题本沉淀
"""

import os
import re
import sys
import json
import uuid
import math
import struct
import logging
import asyncio
from pathlib import Path
from typing import List, Dict, Any, Optional

import httpx

# 路径加载
current_dir = Path(__file__).resolve().parent
if str(current_dir) in sys.path:
    sys.path.remove(str(current_dir))
sys.path.insert(0, str(current_dir))

try:
    from books_pipeline.config import LibraryConfig
except ImportError:
    from config import LibraryConfig
from db import execute_turso, float_array_to_blob
from dual_engine import call_volcengine, stream_volcengine

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("DynamicQuiz")


def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """计算余弦相似度"""
    dot = sum(x * y for x, y in zip(v1, v2))
    mag1 = math.sqrt(sum(x * x for x in v1))
    mag2 = math.sqrt(sum(y * y for y in v2))
    if mag1 * mag2 == 0:
        return 0.0
    return dot / (mag1 * mag2)


def blob_to_float_array(blob_bytes: bytes) -> List[float]:
    """将二进制 blob 转为 float 列表"""
    num_floats = len(blob_bytes) // 4
    return list(struct.unpack(f'{num_floats}f', blob_bytes))


async def get_query_embedding(query: str) -> List[float]:
    """获取检索词的 1024 维向量"""
    url = "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings"
    headers = {
        "Authorization": f"Bearer {LibraryConfig.DASHSCOPE_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": LibraryConfig.EMBEDDING_MODEL,
        "input": [query.strip()[:2000]],
        "dimensions": LibraryConfig.EMBEDDING_DIM
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        return resp.json()["data"][0]["embedding"]


async def get_available_books() -> List[Dict[str, Any]]:
    """获取当前已入库的所有书籍"""
    sql = "SELECT id, title, author, format, total_chars, total_chunks FROM library_books ORDER BY created_at DESC;"
    return await execute_turso(sql)


async def retrieve_book_chunk(book_id: str, topic: Optional[str] = None) -> Dict[str, Any]:
    """
    检索切块：
    - 若指定 topic：通过向量相似度计算召回最相关切块
    - 若未指定 topic：随机抽取切块
    """
    if topic and topic.strip():
        # 1. 混合多路召回 (关键词预过滤 + 向量精确重排)
        clean_topic = topic.strip()
        query_emb = await get_query_embedding(clean_topic)
        
        # 优先检索包含关键词或相关章节的候选切块
        sql_kw = """
        SELECT id, book_id, chapter_title, chunk_index, content, embedding 
        FROM library_book_chunks 
        WHERE (book_id = ? OR book_id LIKE ?) 
          AND (content LIKE ? OR chapter_title LIKE ?)
        LIMIT 40;
        """
        rows = await execute_turso(sql_kw, [book_id, f"%{book_id}%", f"%{clean_topic}%", f"%{clean_topic}%"])
        
        # 若未命中关键词，抽取随机样本进行语义重排
        if not rows or len(rows) < 3:
            sql_sample = """
            SELECT id, book_id, chapter_title, chunk_index, content, embedding 
            FROM library_book_chunks 
            WHERE book_id = ? OR book_id LIKE ?
            ORDER BY RANDOM() 
            LIMIT 50;
            """
            sample_rows = await execute_turso(sql_sample, [book_id, f"%{book_id}%"])
            rows = (rows or []) + sample_rows
            
        if not rows:
            raise ValueError(f"未在数据库中找到书籍 [{book_id}] 的切块数据")
            
        scored = []
        for r in rows:
            emb_blob = r.get("embedding")
            if emb_blob:
                try:
                    vec = blob_to_float_array(emb_blob) if isinstance(emb_blob, bytes) else emb_blob
                    score = cosine_similarity(query_emb, vec)
                    scored.append((score, r))
                except Exception:
                    continue
                    
        if not scored:
            return rows[0]
            
        scored.sort(key=lambda x: x[0], reverse=True)
        best_chunk = scored[0][1]
        best_chunk["score"] = scored[0][0]
        return best_chunk
    else:
        # 2. 随机盲盒抽样
        sql_random = """
        SELECT id, book_id, chapter_title, chunk_index, content 
        FROM library_book_chunks 
        WHERE book_id = ? OR book_id LIKE ?
        ORDER BY RANDOM() 
        LIMIT 1;
        """
        rows = await execute_turso(sql_random, [book_id, f"%{book_id}%"])
        if not rows:
            raise ValueError(f"未在数据库中找到书籍 [{book_id}] 的切块数据")
        return rows[0]


async def generate_dynamic_quiz(book_id: str, topic: Optional[str] = None) -> Dict[str, Any]:
    """
    基于 RAG 动态无限命制测试题 (单选/多选/实战案例)
    由 DeepSeek-V4-Pro 现场命制，永不重复！
    """
    chunk = await retrieve_book_chunk(book_id, topic)
    chunk_id = chunk["id"]
    chapter_title = chunk.get("chapter_title", "核心章节")
    content = chunk["content"]
    
    prompt = f"""你是一名严谨且善于启发思考的顶级计算机技术考官。
请根据以下来自原著书籍的真实切块内容，命制一道【高质量的技术研习测试题】（单选题或多选题）。

【原著段落参考】：
{content[:1500]}

【命题规范】：
1. 题干设计：聚焦核心机制、底层原理、典型坑点或真实工程场景，避免死记硬背概念，注重逻辑判断与实操选型。
2. 选项设计：提供 A, B, C, D 4个选项。干扰项必须具备迷惑性与针对性（针对常见认知误区），正确选项必须逻辑严密。
3. 必须严格以标准 JSON 格式输出，不要包含任何额外的 markdown 格式标记（如 ```json）。

JSON 输出结构：
{{
    "question": "题干描述（如包含代码片段，使用标准代码格式）",
    "question_type": "single_choice",
    "options": {{
        "A": "选项A描述",
        "B": "选项B描述",
        "C": "选项C描述",
        "D": "选项D描述"
    }},
    "correct_answer": "B",
    "chapter_title": "{chapter_title}",
    "reference_quote": "从上方原著段落中摘录出的核心论据原话（50字以内）"
}}
"""
    system_prompt = "你是一名顶尖的技术考官，擅长基于原著技术切块命制具备深度与启发性的测试题，只输出严格的 JSON。"
    raw_res = await call_volcengine(LibraryConfig.ENDPOINT_DEEPSEEK_PRO, prompt, system_prompt, temperature=0.4)
    
    # 提取 JSON
    match = re.search(r'\{.*\}', raw_res, re.DOTALL)
    if not match:
        raise ValueError(f"DeepSeek 返回内容非有效 JSON: {raw_res[:200]}")
        
    quiz_data = json.loads(match.group(0))
    quiz_id = f"quiz_{uuid.uuid4().hex[:12]}"
    
    # 存入 Turso library_quiz_history
    sql_insert = """
    INSERT INTO library_quiz_history (id, book_id, chunk_id, question, options_json, correct_answer, created_at)
    VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP);
    """
    await execute_turso(sql_insert, [
        quiz_id,
        chunk.get("book_id", book_id),
        chunk_id,
        quiz_data["question"],
        json.dumps(quiz_data["options"], ensure_ascii=False),
        quiz_data["correct_answer"].strip().upper()
    ])
    
    return {
        "quiz_id": quiz_id,
        "book_id": chunk.get("book_id", book_id),
        "chunk_id": chunk_id,
        "chapter_title": chapter_title,
        "question": quiz_data["question"],
        "options": quiz_data["options"],
        "question_type": quiz_data.get("question_type", "single_choice"),
        "correct_answer": quiz_data["correct_answer"].strip().upper(),
        "reference_quote": quiz_data.get("reference_quote", "")
    }


async def evaluate_and_explain(quiz_id: str, user_answer: str, user_id: str = "woodman") -> Dict[str, Any]:
    """
    动态智能解析与错因排查：
    根据用户实际选择的选项，调用 DeepSeek-V4-Pro 动态生成：
    1. 正误判定
    2. 针对用户所选错项的专属思维误区诊断
    3. 原著出处段落实时溯源
    4. 生产环境避坑指南
    """
    # 1. 查询题目信息
    sql = "SELECT id, book_id, chunk_id, question, options_json, correct_answer FROM library_quiz_history WHERE id = ?;"
    rows = await execute_turso(sql, [quiz_id])
    if not rows:
        raise ValueError(f"未找到测试题记录: {quiz_id}")
        
    quiz_record = rows[0]
    correct_answer = quiz_record["correct_answer"].strip().upper()
    user_ans = user_answer.strip().upper()
    is_correct = 1 if user_ans == correct_answer else 0
    
    # 2. 查询原著切块上下文
    chunk_sql = "SELECT chapter_title, content FROM library_book_chunks WHERE id = ?;"
    chunk_rows = await execute_turso(chunk_sql, [quiz_record["chunk_id"]])
    chunk_content = chunk_rows[0]["content"] if chunk_rows else "（原著切块上下文）"
    chapter_title = chunk_rows[0].get("chapter_title", "对应章节") if chunk_rows else "相关章节"
    
    # 3. 由 DeepSeek 动态生成深度解析
    options = json.loads(quiz_record["options_json"])
    prompt = f"""你是一名资深技术架构师兼导师。学员刚刚完成了你在《{quiz_record['book_id']}》中命制的一道研习题。
请根据学员的实际作答情况，生成一份【通透、犀利且极具指导价值的专属解析】。

【题目内容】：
{quiz_record['question']}

【选项列表】：
{json.dumps(options, ensure_ascii=False, indent=2)}

【正确答案】：{correct_answer}
【学员选择】：{user_ans} (判定: {'✅ 完全正确' if is_correct else '❌ 选择错误'})

【原著段落依据】：
{chunk_content[:1500]}

【请按以下 Markdown 结构输出解析】：
### {'🎉 恭喜回答正确！' if is_correct else '💡 错题深度复盘'}

- **🎯 正确答案**：`{correct_answer}` {'（你选对了）' if is_correct else f'（你的选择是 `{user_ans}`）'}
- **🔍 选项深度剖析**：
  - 为什么 `{correct_answer}` 是正确/最优解？请结合底层原理讲透。
  {f"- 为什么 `{user_ans}` 是典型陷阱？请一针见血指出学员可能产生的思维混淆点。" if not is_correct else "- 其他干扰项的典型误区解析。"}
- **📖 原著章节溯源**：
  > 📌 **出处章节**：《{chapter_title}》
  > 💬 **原著论据**：提取原著中最核心的一到两句原话论证。
- **🚀 生产实战避坑指南**：
  - 在实际业务或开发中，此知识点最容易引发什么 Bug / 性能问题？如何防范？
"""
    system_prompt = "你是一名顶尖的计算机架构导师，擅长一针见血指出学员的思维漏洞并结合原著上下文给出通透题解。"
    analysis = await call_volcengine(LibraryConfig.ENDPOINT_DEEPSEEK_PRO, prompt, system_prompt, temperature=0.3)
    
    # 4. 更新做题记录到 Turso
    sql_update = """
    UPDATE library_quiz_history 
    SET user_id = ?, user_answer = ?, is_correct = ?, analysis = ?
    WHERE id = ?;
    """
    await execute_turso(sql_update, [user_id, user_ans, is_correct, analysis, quiz_id])
    
    return {
        "quiz_id": quiz_id,
        "is_correct": bool(is_correct),
        "correct_answer": correct_answer,
        "user_answer": user_ans,
        "chapter_title": chapter_title,
        "analysis": analysis
    }


async def evaluate_and_explain_stream(quiz_id: str, user_answer: str, user_id: str = "woodman"):
    """
    流式动态智能解析与错因排查：
    实时 yield 解析文本，首字响应 1~3 秒，并在完成时自动异步入库 Turso 历史台账。
    """
    # 1. 查询题目信息
    sql = "SELECT id, book_id, chunk_id, question, options_json, correct_answer FROM library_quiz_history WHERE id = ?;"
    rows = await execute_turso(sql, [quiz_id])
    if not rows:
        raise ValueError(f"未找到测试题记录: {quiz_id}")
        
    quiz_record = rows[0]
    correct_answer = quiz_record["correct_answer"].strip().upper()
    user_ans = user_answer.strip().upper()
    is_correct = 1 if user_ans == correct_answer else 0
    
    # 2. 查询原著切块上下文
    chunk_sql = "SELECT chapter_title, content FROM library_book_chunks WHERE id = ?;"
    chunk_rows = await execute_turso(chunk_sql, [quiz_record["chunk_id"]])
    chunk_content = chunk_rows[0]["content"] if chunk_rows else "（原著切块上下文）"
    chapter_title = chunk_rows[0].get("chapter_title", "对应章节") if chunk_rows else "相关章节"
    
    # 3. 构造提示词
    options = json.loads(quiz_record["options_json"])
    prompt = f"""你是一名资深技术导师。学员刚刚完成了《{quiz_record['book_id']}》中的一道研习题。
请根据学员作答生成通透犀利的专属解析（600字以内）。

【题目】：{quiz_record['question']}
【选项】：{json.dumps(options, ensure_ascii=False)}
【正确答案】：{correct_answer}
【学员选择】：{user_ans} ({'✅ 正确' if is_correct else '❌ 错误'})
【原著依据】：{chunk_content[:1200]}

【按以下 Markdown 输出】：
### {'🎉 回答正确！' if is_correct else '💡 错因深度复盘'}
- **🎯 正确答案**：`{correct_answer}` {'（你选对了）' if is_correct else f'（你的选择是 `{user_ans}`）'}
- **🔍 深度剖析**：
  - 结合底层原理讲透为什么 `{correct_answer}` 是正确解。
  {f"- 一针见血指出为什么 `{user_ans}` 是典型认知陷阱。" if not is_correct else "- 其他干扰项的典型误区。"}
- **📖 原著章节溯源**：
  > 📌 **出处章节**：《{chapter_title}》
  > 💬 **原著论据**：摘录最核心的原著原话。
- **🚀 实战避坑指南**：实际工程开发中的注意事项与防范技巧。
"""
    system_prompt = "你是一名顶尖架构导师，擅长结合原著上下文给出通透题解。"
    
    collected = []
    # 使用流式火山方舟 API
    async for chunk_text in stream_volcengine(
        LibraryConfig.ENDPOINT_DEEPSEEK_PRO,
        prompt,
        system_prompt,
        temperature=0.3,
        max_tokens=1200,
        book_id=quiz_record["book_id"],
        task_name="Quiz_Explain_Stream"
    ):
        collected.append(chunk_text)
        yield chunk_text
        
    full_analysis = "".join(collected).strip()
    
    # 4. 异步保存到 Turso
    try:
        sql_update = """
        UPDATE library_quiz_history 
        SET user_id = ?, user_answer = ?, is_correct = ?, analysis = ?
        WHERE id = ?;
        """
        await execute_turso(sql_update, [user_id, user_ans, is_correct, full_analysis, quiz_id])
    except Exception as err:
        logger.warning(f"保存做题记录异常: {err}")


if __name__ == "__main__":
    async def demo():
        books = await get_available_books()
        print(f"📚 当前已入库书籍 ({len(books)} 本):")
        for b in books:
            print(f"  - [{b['id']}] 《{b['title']}》 ({b['total_chunks']} chunks)")
            
        if books:
            target_book = books[0]["id"]
            print(f"\n🎲 正在为书籍 [{target_book}] 随机盲盒命制 1 道测试题...")
            quiz = await generate_dynamic_quiz(target_book)
            print(f"题目: {quiz['question']}")
            print(f"选项: {json.dumps(quiz['options'], ensure_ascii=False, indent=2)}")
            print(f"正确答案: {quiz['correct_answer']}")
            
            # 模拟用户作答
            test_ans = "A"
            print(f"\n📝 模拟用户选择: {test_ans}，正在动态生成深度解析与原著溯源...")
            eval_res = await evaluate_and_explain(quiz["quiz_id"], test_ans)
            print(eval_res["analysis"])

    asyncio.run(demo())

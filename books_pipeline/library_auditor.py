#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
第二大脑·AI 智能图书馆：成果质量巡检与自动修复引擎 (`library_auditor.py`)
功能：
  1. 深度巡检：扫描所有已入库图书的精读讲义，检测 400 Bad Request、章节提炼异常、假完成与残缺内容
  2. 无缝热修：优先复用 Turso 已存切块，无需重复下载，直接由阿里百炼 Qwen-Plus 旗舰重新提炼高水准讲义
  3. 双轨更新：自动回写 Turso 元数据与 Google Drive 输出目录 (`gdrive:CloseReading/output/`)
  4. 守护服务：支持一键批处理修复与常驻守护进程模式 (每 30 分钟自动巡检修补)
"""

import os
import sys
import time
import json
import logging
import asyncio
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Tuple

current_dir = Path(__file__).resolve().parent
parent_dir = current_dir.parent
if str(parent_dir) in sys.path:
    sys.path.remove(str(parent_dir))
if str(current_dir) in sys.path:
    sys.path.remove(str(current_dir))
sys.path.insert(0, str(current_dir))
sys.path.append(str(parent_dir))

from config import LibraryConfig
from db import execute_turso
from deep_distiller import distill_single_chapter
from dual_engine import QuotaExhaustedError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [LibraryAuditor] - %(levelname)s - %(message)s"
)
logger = logging.getLogger("LibraryAuditor")

LOCAL_OUTPUT_DIR = current_dir / "output"
LOCAL_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def check_summary_health(content: str) -> Tuple[bool, str]:
    """
    检测精读讲义的健康状态
    返回: (is_healthy, reason)
    """
    if not content or len(content.strip()) < 500:
        return False, "讲义字数过短 (<500字)"
        
    error_keywords = [
        "章节提炼异常",
        "Bad Request",
        "Client error '400",
        "Client error '404",
        "Client error '500",
        "HTTPStatusError",
        "api.siliconflow.cn",
        "Connection error",
        "Rate limit exceeded"
    ]
    for kw in error_keywords:
        if kw in content:
            return False, f"包含错误关键字: {kw}"
            
    # 检查有效章节标题数
    h2_count = content.count("## 📌") + content.count("## ")
    if h2_count == 0:
        return False, "缺少有效章节结构标题"
        
    return True, "健康正常"


async def get_all_books_from_db() -> List[Dict[str, Any]]:
    """获取 Turso 中所有书籍记录"""
    sql = "SELECT id, title, format, summary_chars, total_chunks, total_chars, summary_path, original_file_path FROM library_books ORDER BY id ASC;"
    return await execute_turso(sql)


async def get_book_summary_text(book_id: str, summary_path: str, fetch_remote: bool = False) -> str:
    """获取书籍讲义文本 (本地高速读取，必要时远端兜底)"""
    if summary_path and Path(summary_path).exists():
        try:
            return Path(summary_path).read_text(encoding="utf-8", errors="ignore")
        except Exception:
            pass

    local_file = LOCAL_OUTPUT_DIR / f"[Book]{book_id}_精读研习.md"
    if local_file.exists():
        try:
            return local_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            pass
            
    if fetch_remote:
        gdrive_path = f"gdrive:CloseReading/output/[Book]{book_id}_精读研习.md"
        cmd = ["rclone", "cat", gdrive_path]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0 and res.stdout.strip():
            try:
                local_file.write_text(res.stdout, encoding="utf-8")
            except Exception:
                pass
            return res.stdout
        
    return ""


async def audit_all_books() -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """全面巡检所有书籍成果"""
    books = await get_all_books_from_db()
    healthy_books = []
    corrupted_books = []
    
    logger.info(f"🔍 开始对数据库中 {len(books)} 本图书成果进行深度健康巡检...")
    
    for idx, b in enumerate(books, 1):
        bid = b["id"]
        title = b["title"]
        summary_chars = int(b.get("summary_chars") or 0)
        
        # 排除标记为格式异常跳过的图书
        if summary_chars == 1 and int(b.get("total_chunks") or 0) == 0:
            continue
            
        content = await get_book_summary_text(bid, b.get("summary_path") or "")
        is_healthy, reason = check_summary_health(content)
        
        if is_healthy:
            healthy_books.append({**b, "actual_chars": len(content)})
        else:
            corrupted_books.append({
                **b, 
                "corrupt_reason": reason, 
                "actual_chars": len(content),
                "has_chunks": int(b.get("total_chunks") or 0) > 0
            })
            
    logger.info(f"📊 巡检完成！总入库有效专著: {len(books)} 本 | ✅ 完美成果: {len(healthy_books)} 本 | ⚠️ 待修复受损专著: {len(corrupted_books)} 本")
    return healthy_books, corrupted_books


async def repair_single_book(book_info: Dict[str, Any]) -> bool:
    """
    自动修复单本书籍：
    1. 查询已有切块，聚合成章节
    2. 调度阿里百炼 Qwen-Plus 旗舰重新提炼
    3. 同步至 Google Drive 与 Turso
    """
    bid = book_info["id"]
    title = book_info["title"]
    logger.info(f"\n=======================================================")
    logger.info(f"🛠️ [修复流水线] 开始自动重构受损图书: 《{title}》")
    logger.info(f"📌 受损原因: {book_info.get('corrupt_reason', '未知')}")
    logger.info(f"=======================================================")
    
    t0 = time.time()
    
    # 1. 尝试从 Turso 查询已有切块
    chunks_sql = """
    SELECT chapter_title, chunk_index, content
    FROM library_book_chunks
    WHERE book_id = ? OR book_id LIKE ?
    ORDER BY chunk_index ASC;
    """
    chunk_rows = await execute_turso(chunks_sql, [bid, f"%{bid}%"])
    
    chapters = []
    if chunk_rows:
        # 按章节聚合切块内容
        chap_map = {}
        for r in chunk_rows:
            ctitle = r["chapter_title"]
            if ctitle not in chap_map:
                chap_map[ctitle] = {
                    "title": ctitle,
                    "chunks": [],
                    "start_chunk": int(r["chunk_index"]),
                    "end_chunk": int(r["chunk_index"])
                }
            chap_map[ctitle]["chunks"].append(r["content"])
            chap_map[ctitle]["end_chunk"] = max(chap_map[ctitle]["end_chunk"], int(r["chunk_index"]))
            
        for ctitle, cdata in chap_map.items():
            combined_text = "\n\n".join(cdata["chunks"])
            chapters.append({
                "title": ctitle,
                "content": combined_text,
                "start_chunk": cdata["start_chunk"],
                "end_chunk": cdata["end_chunk"]
            })
            
    if not chapters:
        logger.warning(f"⚠️ 书籍 《{title}》 数据库中缺少有效切块，需等待主 Worker 重新下载提取。")
        return False
        
    logger.info(f"📖 成功重组 {len(chapters)} 个核心章节，正在调度阿里百炼 Qwen-Plus 旗舰并发提炼...")
    
    # 选取最核心的 15 个章节进行深度提炼
    core_chaps = sorted(chapters, key=lambda x: len(x["content"]), reverse=True)[:15]
    # 恢复章节顺序
    core_chaps = sorted(core_chaps, key=lambda x: x["start_chunk"])
    
    sem = asyncio.Semaphore(2)
    distill_tasks = []
    for chap in core_chaps:
        distill_tasks.append(distill_single_chapter(
            book_id=bid,
            book_title=title,
            chapter_title=chap["title"],
            start_chunk=chap["start_chunk"],
            end_chunk=chap["end_chunk"],
            chapter_text=chap["content"],
            sem=sem
        ))
        
    distilled_results = await asyncio.gather(*distill_tasks)
    valid_sections = [r["markdown"] for r in distilled_results if r.get("markdown") and len(r.get("markdown", "").strip()) > 50]
    
    if not valid_sections:
        logger.error(f"❌ 《{title}》 提炼产物为空，修复失败。")
        return False
        
    distilled_text = "\n\n".join(valid_sections)
    
    # 写入本地文件
    out_file = LOCAL_OUTPUT_DIR / f"[Book]{bid}_精读研习.md"
    out_file.write_text(distilled_text, encoding="utf-8")
    
    # 更新 Turso 数据库
    update_sql = """
    UPDATE library_books 
    SET summary_chars = ?, summary_path = ?
    WHERE id = ?;
    """
    await execute_turso(update_sql, [len(distilled_text), str(out_file), bid])
    
    # 同步至 Google Drive
    sync_cmd = ["rclone", "copy", str(out_file), "gdrive:CloseReading/output/"]
    subprocess.run(sync_cmd, capture_output=True)
    
    t_spent = time.time() - t0
    logger.info(f"🎉 《{title}》 修复重构成功！耗时: {t_spent:.1f}s | 全新高质量讲义: {len(distilled_text):,} 字")
    return True


async def run_auditor_loop(auto_repair: bool = True, max_repairs_per_round: int = 100):
    """巡检与自动修复主循环"""
    logger.info("🛡️ 启动第二大脑·AI 图书馆成果质量巡检守护引擎...")
    healthy, corrupted = await audit_all_books()
    
    if not auto_repair or not corrupted:
        logger.info(f"✨ 巡检完成，暂无需修复项。")
        return
        
    logger.info(f"🚀 开始批处理自动修复受损专著 (计划本次修复前 {min(len(corrupted), max_repairs_per_round)} 本)...")
    
    repair_count = 0
    for b in corrupted:
        if repair_count >= max_repairs_per_round:
            break
        try:
            success = await repair_single_book(b)
            if success:
                repair_count += 1
                await asyncio.sleep(5)
            else:
                await asyncio.sleep(1)
        except QuotaExhaustedError as qe:
            logger.warning(f"🛡️ 触发 0 成本配额熔断保护: {qe}。本轮修复休眠退出。")
            break
        except Exception as err:
            logger.error(f"修复异常: {err}")
            await asyncio.sleep(2)
            
    logger.info(f"🏁 本轮质量修复结束！共成功重构并升级 {repair_count} 本专著讲义。")


async def run_daemon():
    """常驻后台守护模式 (每 30 分钟巡检一次)"""
    logger.info("🌟 启动常驻巡检守护服务模式 (轮询周期: 30 分钟)...")
    while True:
        try:
            await run_auditor_loop(auto_repair=True, max_repairs_per_round=10)
        except QuotaExhaustedError as qe:
            logger.warning(f"🛡️ 今日免费配额已达安全上限: {qe}。守护进程休眠 2 小时后再次复检...")
            await asyncio.sleep(7200)
        except Exception as e:
            logger.error(f"巡检循环异常: {e}", exc_info=True)
            await asyncio.sleep(600)
        else:
            logger.info("⏳ 等待下一次巡检 (30 分钟后)...")
            await asyncio.sleep(1800)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="第二大脑 AI 图书馆成果质量巡检与自动修复服务")
    parser.add_argument("--audit-only", action="store_true", help="仅执行质量巡检并输出健康度报告")
    parser.add_argument("--repair-all", action="store_true", help="立即执行所有受损专著的批量自动修复")
    parser.add_argument("--daemon", action="store_true", help="作为常驻守护服务在后台运行")
    parser.add_argument("--limit", type=int, default=50, help="单次最大修复书籍数")
    args = parser.parse_args()
    
    if args.audit_only:
        asyncio.run(audit_all_books())
    elif args.daemon:
        asyncio.run(run_daemon())
    else:
        asyncio.run(run_auditor_loop(auto_repair=True, max_repairs_per_round=args.limit))

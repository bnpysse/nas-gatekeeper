#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
每日 Auto_Clippings 聚合深度研报生成器 (Daily Intelligence Digest)
每天将当天抓取的所有财经、宏观、科技与社区高质量情报进行跨领域多维度融合提炼，并生成双向链接。
"""

import os
import sys
import re
import json
from datetime import datetime, timedelta
from pathlib import Path

# 配置代理与运行环境
os.environ['HTTP_PROXY'] = 'http://192.168.2.3:7890'
os.environ['HTTPS_PROXY'] = 'http://192.168.2.3:7890'
os.environ['http_proxy'] = 'http://192.168.2.3:7890'
os.environ['https_proxy'] = 'http://192.168.2.3:7890'
os.environ['ALL_PROXY'] = 'http://192.168.2.3:7890'
os.environ['all_proxy'] = 'http://192.168.2.3:7890'
os.environ['NO_PROXY'] = 'localhost,127.0.0.1,dashscope.aliyuncs.com,ark.cn-beijing.volces.com'
os.environ['no_proxy'] = 'localhost,127.0.0.1,dashscope.aliyuncs.com,ark.cn-beijing.volces.com'

project_root = str(Path(__file__).resolve().parent.parent.parent)
tg_bot_dir = str(Path(__file__).resolve().parent.parent / "tg-bot")
if project_root not in sys.path:
    sys.path.insert(0, project_root)
if tg_bot_dir not in sys.path:
    sys.path.insert(0, tg_bot_dir)

from processor import get_deepseek_client, VOLCENGINE_ENDPOINT_ID

VAULT_BASE = Path("/opt/obsidian-brain-data" if Path("/opt/obsidian-brain-data").exists() else Path.home() / "dev/nas-gatekeeper/SecondBrain-Quartz/content/notes")
CLIPPINGS_DIR = VAULT_BASE / "Auto_Clippings"
SUMMARY_DIR = VAULT_BASE / "Auto_Summary"

def get_today_clippings(target_date: str = None) -> list[dict]:
    """获取指定日期 (默认当天) 的所有 Auto_简报 笔记"""
    if not target_date:
        target_date = datetime.now().strftime("%Y-%m-%d")
        
    results = []
    if not CLIPPINGS_DIR.exists():
        print(f"⚠️ 目录不存在: {CLIPPINGS_DIR}")
        return results
        
    for f in CLIPPINGS_DIR.glob("Auto_简报_*.md"):
        try:
            with open(f, "r", encoding="utf-8", errors="ignore") as fp:
                content = fp.read()
                
            # 匹配创建日期或当天修改
            date_match = re.search(r'date:\s*["\']?(\d{4}-\d{2}-\d{2})', content)
            file_date = date_match.group(1) if date_match else None
            
            # 如果是当天或 24 小时内生成的
            mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d")
            if file_date == target_date or mtime == target_date:
                # 提取标题与源
                title_match = re.search(r'title:\s*["\']?(.*?)["\']?\n', content)
                title = title_match.group(1) if title_match else f.stem
                clean_title = re.sub(r'_简报$', '', title).strip()
                
                # 提取正文主体（去掉 frontmatter）
                body = re.sub(r'^---[\s\S]*?---\n', '', content).strip()
                
                results.append({
                    "filename": f.name,
                    "stem": f.stem,
                    "title": clean_title,
                    "content": body[:1200], # 截取核心摘要
                    "path": str(f)
                })
        except Exception as e:
            print(f"⚠️ 读取文件失败 {f.name}: {e}")
            
    print(f"📊 在 {target_date} 找到 {len(results)} 篇新剪报情报")
    return results

def generate_daily_digest(target_date: str = None) -> Path | None:
    """调用 DeepSeek-V4 生成高质量每日综合研报并落库"""
    if not target_date:
        target_date = datetime.now().strftime("%Y-%m-%d")
        
    clippings = get_today_clippings(target_date)
    if not clippings:
        print(f"ℹ️ {target_date} 暂无足量剪报，跳过每日简报生成。")
        return None
        
    print(f"🧠 正在调用火山方舟 DeepSeek-V4 生成《第二大脑每日情报全景汇编 ({target_date})》...")
    
    # 构建上下文素材
    context_blocks = []
    wikilink_list = []
    for c in clippings:
        wikilink = f"[[{c['stem']}]]"
        wikilink_list.append(wikilink)
        context_blocks.append(f"### 文章: 《{c['title']}》\n引用双链: {wikilink}\n{c['content']}\n")
        
    prompt = f"""你是一位全球宏观策略首席分析师与知识管理专家。
以下是系统在 {target_date} 自动化捕获并提炼的各大财经频道、顶级宏观智库（Substack）、科技前沿与开源社区的核心情报。

请撰写一份高密度、逻辑严密、洞察深刻的《每日全景情报与宏观决策汇编 (Daily Intelligence Digest)》。

【格式与排版要求】：
1. **🌟 宏观大势与市场风向标 (Executive Macro Overview)**：提炼全球经济、利率货币政策、大宗商品及资本市场的核心共振点。
2. **📈 重点深度观点与专题剖析 (Key Thematic Deep-Dives)**：分领域归纳重点论点，并且在每一项核心论点后面，**必须使用双链格式 [[笔记标题]] 明确引用对应的参考来源**！
3. **🔬 科技前沿与产业变革 (Tech & Industry Shifts)**：涵盖 AI 算力、半导体与前沿工程进展。
4. **💡 核心决策启示与行动建议 (Actionable Takeaways)**：提炼 3 点最重要的反直觉认知或中长期布局启发。

【今日参考情报材料】：
{"".join(context_blocks[:25])}
"""

    client = get_deepseek_client()
    try:
        stream = client.chat.completions.create(
            model=VOLCENGINE_ENDPOINT_ID,
            messages=[
                {"role": "system", "content": "你是一位顶尖的第二大脑首席情报分析师。"},
                {"role": "user", "content": prompt}
            ],
            stream=True,
            temperature=0.3,
            max_tokens=6000
        )
        chunks = []
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                chunks.append(chunk.choices[0].delta.content)
        report_content = "".join(chunks).strip()
        if not report_content:
            print("❌ DeepSeek 返回空报告内容")
            return None
    except Exception as e:
        print(f"❌ DeepSeek 生成每日简报失败: {e}")
        return None
        
    # 构建包含标准 YAML Frontmatter 的 Markdown 笔记
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    doc_title = f"Daily_Summary_{target_date.replace('-', '')}"
    
    frontmatter = f"""---
title: "第二大脑每日情报全景汇编 ({target_date})"
date: {now_str}
tags: [每日全景汇编, 宏观研报, 第二大脑日报]
type: daily_summary
---

# 🌐 第二大脑每日情报全景汇编 ({target_date})

> [!NOTE] 聚合元数据
> - **生成时间**: `{now_str}`
> - **情报聚合量**: `{len(clippings)}` 篇深度剪报
> - **知识网络引用**: 包含自动双向链接

---

{report_content}

---

## 📚 今日情报索引源 (References)
"""
    for c in clippings:
        frontmatter += f"- [[{c['stem']}]] —— 《{c['title']}》\n"
        
    SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
    summary_file = SUMMARY_DIR / f"{doc_title}.md"
    
    with open(summary_file, "w", encoding="utf-8") as f:
        f.write(frontmatter)
        
    print(f"✅ 每日情报汇编已生成并保存至: {summary_file}")
    return summary_file

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else None
    generate_daily_digest(target)

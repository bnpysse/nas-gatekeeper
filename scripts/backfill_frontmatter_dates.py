#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
全量标准化 Obsidian / Quartz / Nextra 笔记库的 YAML Frontmatter 日期
确保所有 Markdown 文件均具备标准的 date, created, modified, published 字段，
保证 Quartz 目录列表和 Nextra 导航始终按【最新发布/最新抓取】严格倒序展示！
"""

import os
import re
from pathlib import Path
from datetime import datetime

VAULT_DIR = Path("/opt/obsidian-brain-data")

def extract_date_from_file(file_path: Path, content: str) -> str:
    # 1. 从文件名末尾匹配 _YYYYMMDD_HHMM
    m = re.search(r'(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})', file_path.stem)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)} {m.group(4)}:{m.group(5)}:00"
        
    # 2. 从文件名匹配 YYYYMMDD
    m2 = re.search(r'(\d{4})(\d{2})(\d{2})', file_path.stem)
    if m2:
        return f"{m2.group(1)}-{m2.group(2)}-{m2.group(3)} 12:00:00"

    # 3. 从现有 Frontmatter 提取
    for line in content.splitlines()[:20]:
        if line.startswith("captured_at:") or line.startswith("date:") or line.startswith("created:"):
            raw = line.split(":", 1)[1].strip().strip('\'"')
            m3 = re.search(r'(\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?)?)', raw)
            if m3:
                val = m3.group(1).replace("T", " ")
                if len(val) == 10:
                    return f"{val} 12:00:00"
                if len(val) == 16:
                    return f"{val}:00"
                return val

    # 4. 回退为文件系统修改时间
    mtime = file_path.stat().st_mtime
    return datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")

def process_file(file_path: Path):
    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
        if not content.strip():
            return
            
        target_date = extract_date_from_file(file_path, content)
        
        # 检查是否已有 frontmatter
        fm_match = re.match(r'^---\s*\n(.*?)\n---\s*\n', content, re.DOTALL)
        if fm_match:
            raw_fm = fm_match.group(1)
            body = content[fm_match.end():]
            
            fm_lines = []
            has_date = has_created = has_mod = has_pub = False
            for line in raw_fm.splitlines():
                if line.startswith("date:"):
                    fm_lines.append(f'date: "{target_date}"')
                    has_date = True
                elif line.startswith("created:"):
                    fm_lines.append(f'created: "{target_date}"')
                    has_created = True
                elif line.startswith("modified:"):
                    fm_lines.append(f'modified: "{target_date}"')
                    has_mod = True
                elif line.startswith("published:"):
                    fm_lines.append(f'published: "{target_date}"')
                    has_pub = True
                else:
                    fm_lines.append(line)
                    
            if not has_date:
                fm_lines.append(f'date: "{target_date}"')
            if not has_created:
                fm_lines.append(f'created: "{target_date}"')
            if not has_mod:
                fm_lines.append(f'modified: "{target_date}"')
            if not has_pub:
                fm_lines.append(f'published: "{target_date}"')
                
            new_content = "---\n" + "\n".join(fm_lines) + "\n---\n" + body
        else:
            # 无 Frontmatter，创建新的
            new_content = f"""---
title: "{file_path.stem}"
date: "{target_date}"
created: "{target_date}"
modified: "{target_date}"
published: "{target_date}"
---

{content}"""
        
        file_path.write_text(new_content, encoding="utf-8")
    except Exception as e:
        print(f"Error processing {file_path}: {e}")

def main():
    if not VAULT_DIR.exists():
        print(f"Directory not found: {VAULT_DIR}")
        return
        
    count = 0
    for md_file in VAULT_DIR.rglob("*.md"):
        if ".git" in md_file.parts or ".obsidian" in md_file.parts:
            continue
        process_file(md_file)
        count += 1
        
    print(f"✅ 成功标准化 {count} 篇 Markdown 笔记的 Frontmatter 日期与排序字段！")

if __name__ == "__main__":
    main()

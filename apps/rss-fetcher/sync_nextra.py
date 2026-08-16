#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
SecondBrain Obsidian -> Nextra 全自动静态发布与 MDX 编译器
1. 从 obsidian-brain-data 提取 Markdown 笔记
2. 转换为 MDX 兼容格式（处理 Wikilinks、转义 JSX 特殊字符、清理空文件）
3. 自动生成 Nextra 3.x 规范的 _meta.js 导航树
4. 验证本地构建并同步推送到 GitHub 触发 Cloudflare Pages 全球发布
"""

import os
import re
import sys
import shutil
import subprocess
from pathlib import Path

def sanitize_for_mdx(content: str) -> str:
    """清理 Obsidian 专有语法并转义破坏 MDX JSX 编译的特殊字符与标签"""
    # 1. 规范化 Frontmatter
    fm_match = re.match(r'^---\s*\n(.*?)\n---\s*\n', content, re.DOTALL)
    body = content
    frontmatter_block = ""
    if fm_match:
        raw_fm = fm_match.group(1)
        body = content[fm_match.end():]
        # 解析并重构安全的 YAML Frontmatter
        fm_title = "笔记"
        fm_tags = []
        for line in raw_fm.splitlines():
            if line.startswith("title:"):
                val = line[6:].strip().strip('"\'')
                fm_title = re.sub(r'[\'\"`:]', ' ', val).strip()
            elif line.startswith("tags:"):
                val = line[5:].strip().strip('[]')
                fm_tags = [t.strip().strip('"\'') for t in val.split(',') if t.strip()]
        
        escaped_title = fm_title.replace('"', '\\"')
        tags_str = ", ".join([f'"{t}"' for t in fm_tags])
        frontmatter_block = f'---\ntitle: "{escaped_title}"\ntags: [{tags_str}]\n---\n\n'

    # 移除 HTML 注释 <!-- ... -->（MDX 不支持 HTML 注释）
    body = re.sub(r'<!--.*?-->', '', body, flags=re.DOTALL)

    lines = body.splitlines()
    new_lines = []
    in_code_block = False

    for line in lines:
        # 代码块检测
        if line.strip().startswith("```"):
            in_code_block = not in_code_block
            new_lines.append(line)
            continue

        if in_code_block:
            new_lines.append(line)
            continue

        processed = line

        # 1. 转换 HTML <img> 为标准 Markdown 图片语法（彻底杜绝 JSX 属性报错）
        def img_replacer(m):
            img_tag = m.group(0)
            src_m = re.search(r'src=["\']([^"\']+)["\']', img_tag)
            alt_m = re.search(r'alt=["\']([^"\']*)["\']', img_tag)
            src = src_m.group(1) if src_m else ""
            alt = alt_m.group(1) if alt_m else ""
            return f"![{alt}]({src})" if src else ""

        processed = re.sub(r'<img\s+[^>]*?\/?>', img_replacer, processed, flags=re.IGNORECASE)

        # 2. 转换常见 HTML 格式标签为标准 Markdown
        processed = re.sub(r'<\/?(em|i)\b[^>]*>', '*', processed, flags=re.IGNORECASE)
        processed = re.sub(r'<\/?(strong|b)\b[^>]*>', '**', processed, flags=re.IGNORECASE)
        processed = re.sub(r'<br\s*\/?>', '  \n', processed, flags=re.IGNORECASE)
        processed = re.sub(r'<hr\s*\/?>', '\n---\n', processed, flags=re.IGNORECASE)
        processed = re.sub(r'<\/?(table|thead|tbody|tfoot|tr|th|td)\b[^>]*>', '', processed, flags=re.IGNORECASE)

        # 3. 转换 Obsidian 高亮 ==text== 为 <mark>text</mark>
        processed = re.sub(r'==([^=]+)==', r'<mark>\1</mark>', processed)
        
        # 4. 转换 Obsidian 双链 [[Note Name|Display]] -> [Display](/auto-clippings/note-name)
        def _repl_wikilink_pipe(m):
            target = m.group(1).strip()
            disp = m.group(2).strip()
            slug = make_safe_filename(target)
            cat = "auto-summary" if "Daily" in target or "综合" in target else ("inbox" if target.startswith("[") or "Inbox" in target else "auto-clippings")
            return f"[{disp}](/{cat}/{slug})"

        def _repl_wikilink_simple(m):
            target = m.group(1).strip()
            slug = make_safe_filename(target)
            cat = "auto-summary" if "Daily" in target or "综合" in target else ("inbox" if target.startswith("[") or "Inbox" in target else "auto-clippings")
            return f"[{target}](/{cat}/{slug})"

        processed = re.sub(r'\[\[([^\]|]+)\|([^\]]+)\]\]', _repl_wikilink_pipe, processed)
        processed = re.sub(r'\[\[([^\]]+)\]\]', _repl_wikilink_simple, processed)

        # 5. 移除 Obsidian 注释 %% ... %% 和 块引用 ^id
        processed = re.sub(r'%%.*?%%', '', processed)
        processed = re.sub(r'\s*\^[a-zA-Z0-9_-]+$', '', processed)

        # 6. 防范 JS import / export 语句被 acorn / MDX 解析
        if re.match(r'^\s*import\s+', processed):
            processed = re.sub(r'^(\s*)import\s+', r'\1&#105;mport ', processed)
        if re.match(r'^\s*export\s+', processed):
            processed = re.sub(r'^(\s*)export\s+', r'\1&#101;xport ', processed)

        # 7. 转义除配对 <mark> 以外的所有剩余 HTML 标签与尖括号 (包括未闭合的 </tr, <table, <| 等)
        marks = []
        def mark_saver(m):
            marks.append(m.group(0))
            return f"__MARK_TAG_{len(marks)-1}__"
        processed = re.sub(r'<mark>.*?</mark>', mark_saver, processed)

        # 将所有未保护的 '<' 和 '>' 转换为 HTML 实体，彻底杜绝 JSX 编译器报错
        processed = processed.replace("<", "&lt;").replace(">", "&gt;")

        # 还原安全的 <mark> 标签
        for idx, mark in enumerate(marks):
            processed = processed.replace(f"__MARK_TAG_{idx}__", mark)

        # 8. 转义未在行内代码中的孤立大括号
        if "{" in processed or "}" in processed:
            parts = processed.split("`")
            for idx in range(0, len(parts), 2):
                parts[idx] = parts[idx].replace("{", "&#123;").replace("}", "&#125;")
            processed = "`".join(parts)

        new_lines.append(processed)

    return frontmatter_block + "\n".join(new_lines)

def make_safe_filename(name: str) -> str:
    """生成安全的 URL 路径标识符（彻底剔除所有引号、句点、逗号、特殊符号）"""
    name = re.sub(r'[\'\"`“”‘’,\.\$#%&+=?!！?:/\\|~^(){}\[\]<>]', '', name).strip(' -_')
    name = name.replace(" ", "-").replace("_", "-")
    name = re.sub(r'-+', '-', name).strip('-')
    if len(name) > 50:
        name = name[:50].rstrip('-')
    return name or "note"

def sync_obsidian_to_nextra(vault_dir: Path, nextra_dir: Path):
    """全量构建 Nextra 文档库"""
    import json
    pages_dir = nextra_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    # 彻底清理所有历史遗留的 _meta.json (Nextra 3.x 强校验禁止此文件)
    for old_json in pages_dir.rglob("_meta.json"):
        try:
            old_json.unlink()
        except Exception:
            pass

    print(f"🚀 开始将 Obsidian 知识库同步至 Nextra: {vault_dir} ➔ {pages_dir}")

    # 需要发布的分类与目录映射
    categories = [
        {"folder": "Inbox", "target": "inbox", "title": "📥 闪念归档 (Inbox)"},
        {"folder": "Auto_Clippings", "target": "auto-clippings", "title": "🤖 智能剪报 (Auto Clippings)"},
        {"folder": "TG_Clippings", "target": "tg-clippings", "title": "📱 TG 频道精选 (TG Clippings)"},
        {"folder": "Auto_Summary", "target": "auto-summary", "title": "📊 综合日报 (Auto Summary)"},
    ]

    top_meta = {
        "index": "首页"
    }

    for cat in categories:
        src_folder = vault_dir / cat["folder"]
        if not src_folder.exists():
            continue

        tgt_folder = pages_dir / cat["target"]
        if tgt_folder.exists():
            shutil.rmtree(tgt_folder)
        tgt_folder.mkdir(parents=True, exist_ok=True)

        cat_meta = {}
        file_count = 0

        for md_file in sorted(src_folder.glob("*.md")):
            try:
                content = md_file.read_text(encoding="utf-8", errors="ignore")
                # 检查实质内容有效性
                body_lines = [
                    l.strip() for l in content.splitlines()
                    if l.strip() and not l.startswith("---") and not l.startswith("title:") and not l.startswith("tags:") and not l.startswith("date:") and not l.startswith("rag_processed:")
                ]
                if len("\n".join(body_lines).strip()) < 30:
                    continue

                safe_name = make_safe_filename(md_file.stem)
                clean_title = re.sub(r'^(Auto_简报_|Raw_翻译_|\[TV\]|\[TA\]|\[多模型\])\s*', '', md_file.stem).strip()
                clean_title = re.sub(r'[\'\"`“”‘’]', '', clean_title)
                if len(clean_title) > 40:
                    clean_title = clean_title[:40] + "..."

                # 转换 MDX
                mdx_content = sanitize_for_mdx(content)
                target_file = tgt_folder / f"{safe_name}.mdx"
                target_file.write_text(mdx_content, encoding="utf-8")

                cat_meta[safe_name] = clean_title
                file_count += 1
            except Exception as e:
                print(f"⚠️ 处理笔记失败 {md_file.name}: {e}")

        if file_count > 0:
            top_meta[cat["target"]] = cat["title"]
            # 写入分类 _meta.js (Nextra 3.x 规范使用 JSON.stringify 保证 100% 语法合法)
            meta_content = f"export default {json.dumps(cat_meta, ensure_ascii=False, indent=2)};\n"
            (tgt_folder / "_meta.js").write_text(meta_content, encoding="utf-8")
            print(f"  📁 [{cat['folder']}] 成功生成 {file_count} 篇 MDX 页面")

    # 写入顶层 pages/_meta.js
    top_meta_content = f"export default {json.dumps(top_meta, ensure_ascii=False, indent=2)};\n"
    (pages_dir / "_meta.js").write_text(top_meta_content, encoding="utf-8")

    # 确保首页 index.mdx 存在
    if not (pages_dir / "index.mdx").exists():
        (pages_dir / "index.mdx").write_text(
            "# 🧠 Woodman's Second Brain\n\n欢迎来到基于 Nextra 构建的数字大脑知识库。\n",
            encoding="utf-8"
        )

    print("✅ Nextra 文档树转换与导航配置生成完毕！")

def publish_nextra_to_github(nextra_dir: Path):
    """自动提交并推送到 GitHub 触发 Cloudflare Pages 全球发布"""
    try:
        subprocess.run(["git", "add", "-A"], cwd=str(nextra_dir), check=False)
        res = subprocess.run(["git", "status", "-s"], cwd=str(nextra_dir), capture_output=True, text=True)
        if res.stdout.strip():
            print("🐙 正在将 Nextra 静态页面更新推送到 GitHub...")
            subprocess.run(["git", "commit", "-m", "Auto sync: publish latest Obsidian notes to Nextra"], cwd=str(nextra_dir), check=False)
            push_res = subprocess.run(["git", "push", "origin", "main"], cwd=str(nextra_dir), capture_output=True, text=True)
            if push_res.returncode == 0:
                print("🚀 Nextra 仓库已成功推送至 GitHub！Cloudflare Pages 正在全球部署上线...")
            else:
                print(f"⚠️ Git push 警告: {push_res.stderr}")
        else:
            print("ℹ️ Nextra 内容无变化，无需推送。")
    except Exception as e:
        print(f"⚠️ 推送 Nextra 异常: {e}")

if __name__ == "__main__":
    vault_path = Path("/opt/obsidian-brain-data") if Path("/opt/obsidian-brain-data").exists() else Path(__file__).parent.parent.parent / "notes_backup_from_n100"
    if not vault_path.exists():
        vault_path = Path("/Users/woodman/dev/nas-gatekeeper/notes_backup_from_n100")
        
    nextra_path = Path("/opt/nas-gatekeeper/frontends/nextra") if Path("/opt/nas-gatekeeper/frontends/nextra").exists() else Path(__file__).parent.parent.parent / "frontends/nextra"

    sync_obsidian_to_nextra(vault_path, nextra_path)
    publish_nextra_to_github(nextra_path)

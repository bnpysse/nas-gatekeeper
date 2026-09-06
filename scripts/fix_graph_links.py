#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
fix_graph_links.py
修复知识库中的双向图谱关联与 Frontmatter 别名 (aliases)
1. 给 Inbox 下全部笔记注入规范 aliases (支持标题别名匹配与重定向)
2. 修复 AI 图谱双向关联中失效的 404 链接，将其解析为精准的相对路径内部链接
"""

import os
import re
import glob
import yaml

INBOX_DIR = "/opt/obsidian-brain-data/Inbox"
CLIPPINGS_DIR = "/opt/obsidian-brain-data/Auto_Clippings"

def parse_md_frontmatter(content: str):
    """解析 Markdown 的 frontmatter 与正文"""
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            try:
                meta = yaml.safe_load(parts[1]) or {}
                body = parts[2]
                return meta, body, True
            except Exception:
                pass
    return {}, content, False

def dump_md_frontmatter(meta: dict, body: str) -> str:
    """序列化 frontmatter 与正文"""
    yaml_str = yaml.dump(meta, allow_unicode=True, sort_keys=False, default_flow_style=False)
    return f"---\n{yaml_str}---\n{body.lstrip()}"

def clean_title_for_alias(title: str) -> list[str]:
    """生成笔记的若干有效别名（严格限制最大字节长度，防止 Quartz AliasRedirects 触发 ENAMETOOLONG）"""
    aliases = set()
    t = title.strip()
    if t:
        aliases.add(t)
    t_no_model = re.sub(r'^\[多模型\]\s*', '', t).strip()
    if t_no_model:
        aliases.add(t_no_model)
    t_no_tags = re.sub(r'#[^\s#]+', '', t_no_model).strip()
    if t_no_tags:
        aliases.add(t_no_tags)
    t_norm = re.sub(r'[?？!！_]+$', '', t_no_tags).strip()
    if t_norm:
        aliases.add(t_norm)
    # 严格限制：只有长度 >= 2 且 UTF-8 编码不超过 120 字节（约 40 个中文字符）的才保留为别名
    return [a for a in aliases if len(a) >= 2 and len(a.encode('utf-8')) <= 120]

def build_knowledge_index():
    """建立全库文档的标准化索引"""
    inbox_files = glob.glob(os.path.join(INBOX_DIR, "*.md"))
    clippings_files = glob.glob(os.path.join(CLIPPINGS_DIR, "*.md"))
    
    index = {} # norm_key -> (rel_path, display_name, full_path)
    
    def norm_str(s):
        s = re.sub(r'^\[.*?\]', '', s)
        s = re.sub(r'^(Auto_简报_|Raw_翻译_)', '', s)
        s = re.sub(r'(_简报|_全翻译)$', '', s)
        s = re.sub(r'_2026\d+_\d+', '', s)
        s = re.sub(r'#[^\s#]+', '', s)
        s = re.sub(r'(_股票|_股民交流|_投资理财|_资讯|_纳斯达克|_存储|_AI|_芯片|_cpo|_英伟达|_硅光|_asic|_els|_nand)+', '', s)
        s = re.sub(r'[_\s:：?？!！#（）()\.,，。、《》“”\'\-+~…]+', '', s)
        return s.lower()

    # 1. 索引 Inbox
    for f in inbox_files:
        base = os.path.basename(f)
        stem = os.path.splitext(base)[0]
        norm = norm_str(stem)
        rel = f"./{base}"
        try:
            with open(f, "r", encoding="utf-8", errors="ignore") as fp:
                meta, _, has_fm = parse_md_frontmatter(fp.read())
            if has_fm:
                t = meta.get("title", "")
                if t:
                    norm_t = norm_str(t)
                    if norm_t:
                        index[norm_t] = (rel, t, f)
        except Exception:
            pass
        if norm:
            index[norm] = (rel, stem, f)

    # 2. 索引 Auto_Clippings
    for f in clippings_files:
        base = os.path.basename(f)
        stem = os.path.splitext(base)[0]
        norm = norm_str(stem)
        rel = f"../Auto_Clippings/{base}"
        try:
            with open(f, "r", encoding="utf-8", errors="ignore") as fp:
                meta, _, has_fm = parse_md_frontmatter(fp.read())
            if has_fm:
                t = meta.get("title", "")
                if t:
                    norm_t = norm_str(t)
                    if norm_t:
                        index[norm_t] = (rel, t, f)
        except Exception:
            pass
        if norm:
            index[norm] = (rel, stem, f)
            
    return index, norm_str

def resolve_target(raw_text: str, index: dict, norm_str_fn):
    """尝试将给定的原始链接文本解析到真实文档"""
    raw_clean = raw_text.split('|')[0].strip()
    norm = norm_str_fn(raw_clean)
    if not norm:
        return None
    
    # 1. 精确匹配
    if norm in index:
        return index[norm]
        
    # 2. 包含匹配 (长度至少 4)
    for k, v in index.items():
        if len(norm) >= 4 and len(k) >= 4:
            if norm in k or k in norm:
                return v
                
    # 3. 针对特定关键词的语义兜底
    if "半导体" in raw_text or "芯片" in raw_text or "光模" in raw_text:
        for k, v in index.items():
            if "存储大涨真正受益" in k or "为什么不买存储股" in k:
                return v
    if "大轮回" in raw_text or "周期" in raw_text:
        for k, v in index.items():
            if "轮回" in k or "a股" in k:
                return v

    return None

def main():
    print("🚀 开始扫描并修复知识库双向图谱关联与别名...")
    index, norm_fn = build_knowledge_index()
    print(f"📚 已建立索引文档数: {len(index)}")

    inbox_files = sorted(glob.glob(os.path.join(INBOX_DIR, "*.md")))
    alias_updated_count = 0
    link_updated_count = 0

    for f in inbox_files:
        try:
            with open(f, "r", encoding="utf-8", errors="ignore") as fp:
                raw_content = fp.read()
                
            meta, body, has_fm = parse_md_frontmatter(raw_content)
            changed = False

            # 1. 注入/补全 aliases
            if has_fm:
                title = meta.get("title", "")
                if title:
                    wanted_aliases = clean_title_for_alias(title)
                    current_aliases = meta.get("aliases", [])
                    if isinstance(current_aliases, str):
                        current_aliases = [current_aliases]
                    elif not isinstance(current_aliases, list):
                        current_aliases = []
                    # 过滤掉任何超过 120 字节的无效/超长别名
                    current_aliases = [a for a in current_aliases if isinstance(a, str) and len(a.encode('utf-8')) <= 120]
                    new_aliases = list(dict.fromkeys(list(current_aliases) + wanted_aliases))
                    if new_aliases != meta.get("aliases", []):
                        meta["aliases"] = new_aliases
                        changed = True
                        alias_updated_count += 1

            # 2. 修复 AI 图谱双向关联 / 知识库双向关联
            if "## 🔗" in body:
                def replace_wikilink(m):
                    nonlocal changed, link_updated_count
                    full_match = m.group(0)
                    inner = m.group(1).strip()
                    display_text = inner
                    if '|' in inner:
                        target_part, display_part = inner.split('|', 1)
                        display_text = display_part.strip()
                        raw_target = target_part.strip()
                    else:
                        raw_target = inner

                    res = resolve_target(raw_target, index, norm_fn)
                    if res:
                        rel_path, target_title, _ = res
                        changed = True
                        link_updated_count += 1
                        print(f"  🔗 修复链接: [[{inner}]] -> [{display_text}](<{rel_path}>)")
                        return f"[{display_text}](<{rel_path}>)"
                    else:
                        print(f"  ⚠️ 未找到匹配文档: [[{inner}]] 在文件 {os.path.basename(f)}")
                        return full_match

                new_body = re.sub(r'\[\[(.*?)\]\]', replace_wikilink, body)
                if new_body != body:
                    body = new_body
                    changed = True

            if changed:
                st = os.stat(f)
                if has_fm:
                    new_full_content = dump_md_frontmatter(meta, body)
                else:
                    new_full_content = body
                with open(f, "w", encoding="utf-8") as fp:
                    fp.write(new_full_content)
                os.utime(f, (st.st_atime, st.st_mtime))
                print(f"✅ 更新笔记: {os.path.basename(f)}")

        except Exception as e:
            print(f"❌ 处理文件异常 {f}: {e}")

    print(f"\n🎉 修复完成！更新别名笔记数: {alias_updated_count}，修复双向关联链接数: {link_updated_count}")

if __name__ == "__main__":
    main()

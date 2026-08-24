#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
电子书文本解析与结构提取器
支持 PDF、EPUB、MOBI、TXT 等主流格式的目录抽取与章节文本切分
"""

import re
from pathlib import Path
from typing import List, Dict, Any
import pypdf
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup

def clean_text(text: str) -> str:
    """清理文本中的异常空白与控制字符"""
    if not text:
        return ""
    # 替换连续空白为单个空格，但保留段落换行
    lines = [re.sub(r'[ \t]+', ' ', line).strip() for line in text.splitlines()]
    clean_lines = []
    prev_empty = False
    for line in lines:
        if not line:
            if not prev_empty:
                clean_lines.append("")
                prev_empty = True
        else:
            clean_lines.append(line)
            prev_empty = False
    return "\n".join(clean_lines).strip()

def extract_pdf(pdf_path: Path) -> Dict[str, Any]:
    """提取 PDF 电子书目录与章节文本 (优先 PyMuPDF 毫秒级极速解析)"""
    try:
        import pymupdf as fitz
        doc = fitz.open(str(pdf_path))
        total_pages = len(doc)
        
        toc_items = []
        try:
            toc = doc.get_toc()  # [[lvl, title, page, ...], ...]
            for item in toc:
                toc_items.append({
                    "title": str(item[1]).strip(),
                    "page": int(item[2]),
                    "depth": int(item[0]) - 1
                })
        except Exception:
            toc_items = []
            
        full_text_list = []
        for i, page in enumerate(doc):
            text = page.get_text() or ""
            if text.strip():
                full_text_list.append(f"--- [Page {i+1}] ---\n" + text.strip())
                
        full_text = "\n\n".join(full_text_list)
        return {
            "title": pdf_path.stem,
            "format": "pdf",
            "total_pages": total_pages,
            "toc": toc_items,
            "text": full_text,
            "word_count": len(full_text)
        }
    except Exception:
        # 降级备用 pypdf
        reader = pypdf.PdfReader(str(pdf_path))
        total_pages = len(reader.pages)
        full_text_list = []
        for i, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            if text.strip():
                full_text_list.append(f"--- [Page {i+1}] ---\n" + text.strip())
        full_text = "\n\n".join(full_text_list)
        return {
            "title": pdf_path.stem,
            "format": "pdf",
            "total_pages": total_pages,
            "toc": [],
            "text": full_text,
            "word_count": len(full_text)
        }

def extract_epub(epub_path: Path) -> Dict[str, Any]:
    """提取 EPUB 电子书章节与文本"""
    book = epub.read_epub(str(epub_path))
    title_meta = book.get_metadata('DC', 'title')
    title = title_meta[0][0] if title_meta else epub_path.stem
    author_meta = book.get_metadata('DC', 'creator')
    author = author_meta[0][0] if author_meta else "未知作者"
    
    chapters = []
    full_text_list = []
    
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        soup = BeautifulSoup(item.get_content(), 'html.parser')
        # 移除 script 与 style
        for s in soup(['script', 'style', 'nav']):
            s.decompose()
            
        text = clean_text(soup.get_text())
        if len(text) > 100:  # 忽略极短的版权页或空页
            h1 = soup.find(['h1', 'h2'])
            ch_title = h1.get_text().strip() if h1 else f"章节_{len(chapters)+1}"
            chapters.append({
                "title": ch_title,
                "content": text
            })
            full_text_list.append(f"## {ch_title}\n\n" + text)
            
    full_text = "\n\n".join(full_text_list)
    
    return {
        "title": title,
        "author": author,
        "format": "epub",
        "chapters_count": len(chapters),
        "chapters": chapters,
        "text": full_text,
        "word_count": len(full_text)
    }

def extract_book(file_path: Path) -> Dict[str, Any]:
    """统一电子书解析入口"""
    ext = file_path.suffix.lower()
    if ext == ".pdf":
        return extract_pdf(file_path)
    elif ext == ".epub":
        return extract_epub(file_path)
    elif ext in [".txt", ".md"]:
        text = file_path.read_text(encoding="utf-8", errors="ignore")
        return {
            "title": file_path.stem,
            "format": ext[1:],
            "text": text,
            "word_count": len(text)
        }
    else:
        raise ValueError(f"暂不支持的文件格式: {ext}")

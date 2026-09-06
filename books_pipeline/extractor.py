#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
电子书文本解析与结构提取器
支持 PDF、EPUB、MOBI、TXT 等主流格式的目录抽取与章节文本切分
"""

import re
from pathlib import Path
from typing import List, Dict, Any, Tuple
import pypdf
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

def extract_pdf_chapters(file_path: Path) -> List[Dict[str, Any]]:
    """
    轻量且高效地解析 PDF 电子书章节与文本内容 (优先使用 PyMuPDF)
    支持自动大纲 (TOC) 目录切割与无大纲自适应分章，返回 [{"title": ..., "content": ...}]
    """
    chapters = []
    try:
        try:
            import pymupdf as fitz
        except ImportError:
            import fitz

        doc = fitz.open(str(file_path))
        total_pages = len(doc)
        if total_pages == 0:
            return []

        toc = []
        try:
            toc = doc.get_toc()  # [[lvl, title, page_1_based, ...], ...]
        except Exception:
            toc = []

        # 过滤有效 TOC (去掉空白标题，且层级 <= 2)
        valid_toc = [item for item in toc if item[1] and item[1].strip() and item[0] <= 2 and 1 <= item[2] <= total_pages]

        if len(valid_toc) >= 2:
            # 依据 TOC 页码切分章节
            for idx, item in enumerate(valid_toc):
                lvl, raw_title, start_p = item[0], item[1].strip(), item[2] - 1  # 转换为 0-based
                end_p = (valid_toc[idx + 1][2] - 1) if idx + 1 < len(valid_toc) else total_pages
                
                # 提取该页码范围内的文本
                chap_pages_text = []
                for p_no in range(max(0, start_p), min(total_pages, end_p)):
                    p_txt = doc[p_no].get_text() or ""
                    if p_txt.strip():
                        chap_pages_text.append(p_txt.strip())
                
                full_chap_text = "\n\n".join(chap_pages_text)
                clean_chap_text = clean_text(full_chap_text)
                
                if len(clean_chap_text) > 150:
                    clean_title = re.sub(r"\s+", " ", raw_title).strip()[:80]
                    chapters.append({
                        "title": clean_title or f"第 {idx+1:02d} 章",
                        "content": clean_chap_text
                    })
        
        # 若无有效 TOC 或 TOC 提取失败，采用自适应页面分块与标题正则扫描
        if not chapters:
            pages_per_chunk = 15
            for chunk_idx, start_p in enumerate(range(0, total_pages, pages_per_chunk), 1):
                end_p = min(total_pages, start_p + pages_per_chunk)
                chap_pages_text = []
                detected_title = ""
                
                for p_no in range(start_p, end_p):
                    p_txt = doc[p_no].get_text() or ""
                    if p_txt.strip():
                        chap_pages_text.append(p_txt.strip())
                        # 尝试从前两页的第一行探查章节标题
                        if not detected_title and p_no <= start_p + 1:
                            lines = [ln.strip() for ln in p_txt.splitlines() if ln.strip()]
                            for line in lines[:5]:
                                if re.search(r"^(Chapter\s+\d+|第[0-9一二三四五六七八九十百]+[章回节篇]|Part\s+\d+|SECTION\s+\d+)", line, re.I):
                                    detected_title = line[:80]
                                    break

                full_chap_text = "\n\n".join(chap_pages_text)
                clean_chap_text = clean_text(full_chap_text)
                if len(clean_chap_text) > 150:
                    chap_title = detected_title or f"第 {chunk_idx:02d} 节 (P.{start_p+1}~P.{end_p})"
                    chapters.append({
                        "title": chap_title,
                        "content": clean_chap_text
                    })
        doc.close()
    except Exception as e:
        # 降级使用 pypdf
        try:
            reader = pypdf.PdfReader(str(file_path))
            total_pages = len(reader.pages)
            pages_per_chunk = 15
            for chunk_idx, start_p in enumerate(range(0, total_pages, pages_per_chunk), 1):
                end_p = min(total_pages, start_p + pages_per_chunk)
                chap_pages_text = []
                for p_no in range(start_p, end_p):
                    txt = reader.pages[p_no].extract_text() or ""
                    if txt.strip():
                        chap_pages_text.append(txt.strip())
                full_chap_text = "\n\n".join(chap_pages_text)
                clean_chap_text = clean_text(full_chap_text)
                if len(clean_chap_text) > 150:
                    chapters.append({
                        "title": f"第 {chunk_idx:02d} 节 (P.{start_p+1}~P.{end_p})",
                        "content": clean_chap_text
                    })
        except Exception as e2:
            pass

    return chapters


def check_epub_drm(file_path: Path) -> Tuple[bool, str]:
    """检测 EPUB 文件是否受 DRM 加密保护 (如 HanvonDRM, Adobe DRM, Apple FairPlay)"""
    import zipfile
    try:
        with zipfile.ZipFile(file_path, 'r') as z:
            namelist = z.namelist()
            if 'META-INF/encryption.xml' in namelist:
                enc_data = z.read('META-INF/encryption.xml').decode('utf-8', errors='ignore')
                if 'CipherData' in enc_data or 'EncryptedData' in enc_data:
                    rights = ''
                    if 'META-INF/rights.xml' in namelist:
                        rights = z.read('META-INF/rights.xml').decode('utf-8', errors='ignore')
                    if 'HanvonDRM' in rights or 'Hanvon' in enc_data:
                        return True, 'HanvonDRM 2.1 (汉王私有加密)'
                    elif 'adobe' in enc_data.lower() or 'adept' in rights.lower():
                        return True, 'Adobe DRM'
                    elif 'fairplay' in enc_data.lower():
                        return True, 'Apple FairPlay DRM'
                    return True, 'XML-Enc AES 商业加密'
    except Exception as e:
        return False, f'检测异常: {e}'
    return False, '无加密'


def is_valid_readable_text(text: str) -> bool:
    """质检文本可读性与信息熵，过滤二进制流、乱码与解码失败数据"""
    if not text or len(text.strip()) < 100:
        return False
    
    clean_sample = text[:5000]
    total_len = len(clean_sample)
    if total_len == 0:
        return False

    # 1. 严格检查控制字符比例 (\x00-\x08, \x0b, \x0c, \x0e-\x1f)
    ctrl_chars = sum(1 for ch in clean_sample if ord(ch) < 32 and ch not in '\r\n\t')
    if (ctrl_chars / total_len) > 0.005:  # 控制字符超过 0.5% 判定为二进制乱码
        return False

    # 2. 检查有效可读字符比例 (中文、中英文标点、英文字母与数字)
    valid_chars = sum(1 for ch in clean_sample if '\u4e00' <= ch <= '\u9fa5' or ch.isalnum() or ch in '，。！？、“”《》；：、‘’（）—…,.!?;:\'\"()-_ \n\r\t')
    if (valid_chars / total_len) < 0.65:  # 有效字符低于 65% 判定为乱码
        return False

    return True


def decode_html_bytes(raw_bytes: bytes) -> str:
    """多字符集自适应解码，全面支持中文字符集 (UTF-8, GB18030, GBK, Big5, UTF-16)"""
    for enc in ['utf-8', 'utf-8-sig', 'gb18030', 'gbk', 'big5', 'utf-16']:
        try:
            decoded = raw_bytes.decode(enc)
            if is_valid_readable_text(decoded):
                return decoded
        except Exception:
            continue
    return ""


def extract_epub_text_and_chapters(file_path: Path) -> List[Dict[str, Any]]:
    """
    工业级健壮中文与英文 EPUB 章节解析器：
    1. DRM 商业加密检测与拦截：自动识别 HanvonDRM、Adobe DRM 等，杜绝密文进入 LLM
    2. 多字符集智能适配：自动穿透 UTF-8、GB18030、GBK、Big5 中文字符集
    3. 文本可读性与信息熵闸门：彻底过滤非文本二进制、压缩字节流与乱码
    """
    import zipfile
    from bs4 import BeautifulSoup
    import logging

    log = logging.getLogger("Extractor")

    # 1. DRM 拦截
    is_drm, drm_type = check_epub_drm(file_path)
    if is_drm:
        log.warning(f"🚫 [DRM 拦截] 电子书受商业加密保护 ({drm_type}): {file_path.name}，拒绝进入提取流水线。")
        return []

    chapters = []
    
    # 2. 优先使用 EbookLib 标准库进行结构化提取
    try:
        import ebooklib
        from ebooklib import epub
        book = epub.read_epub(str(file_path), options={"ignore_ncx": True})
        doc_items = [item for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT)]
        
        for idx, item in enumerate(doc_items, 1):
            raw_content = item.get_content()
            content_str = decode_html_bytes(raw_content)
            if not content_str:
                continue
                
            soup = BeautifulSoup(content_str, 'html.parser')
            for s in soup(['script', 'style', 'nav', 'header', 'footer']):
                s.decompose()
                
            h_tag = soup.find(['h1', 'h2', 'h3'])
            if h_tag and h_tag.get_text().strip():
                chap_title = h_tag.get_text().strip()
            elif soup.title and soup.title.get_text().strip() and "EPUB" not in soup.title.get_text():
                chap_title = soup.title.get_text().strip()
            else:
                chap_title = f"第 {idx:02d} 节"
                
            chap_title = re.sub(r"\s+", " ", chap_title).strip()[:80]
            
            paragraphs = []
            for p in soup.find_all(['p', 'pre', 'code', 'blockquote', 'li', 'h4', 'h5', 'div']):
                txt = p.get_text().strip()
                if txt and len(txt) > 5:
                    paragraphs.append(txt)
                    
            full_text = "\n\n".join(paragraphs)
            if len(full_text) < 150:
                full_text = soup.get_text().strip()
                
            clean_chap = clean_text(full_text)
            if len(clean_chap) > 150 and is_valid_readable_text(clean_chap):
                chapters.append({
                    "title": chap_title,
                    "content": clean_chap
                })
        if chapters:
            return chapters
    except Exception as e:
        log.debug(f"EbookLib 尝试提取失败，降级至原生 zip 解析: {e}")

    # 3. 降级使用原生 zipfile 提取
    try:
        with zipfile.ZipFile(file_path, 'r') as z:
            html_files = [f for f in z.namelist() if f.endswith(('.html', '.xhtml', '.htm'))]
            for idx, hfile in enumerate(html_files, 1):
                try:
                    raw = z.read(hfile)
                    content = decode_html_bytes(raw)
                    if not content:
                        continue
                        
                    soup = BeautifulSoup(content, 'html.parser')
                    for s in soup(['script', 'style', 'nav', 'header', 'footer']):
                        s.decompose()
                        
                    h_tag = soup.find(['h1', 'h2', 'h3'])
                    if h_tag and h_tag.get_text().strip():
                        chap_title = h_tag.get_text().strip()
                    elif soup.title and soup.title.get_text().strip() and "EPUB" not in soup.title.get_text():
                        chap_title = soup.title.get_text().strip()
                    else:
                        chap_title = f"第 {idx:02d} 节"
                        
                    chap_title = re.sub(r"\s+", " ", chap_title).strip()[:80]
                        
                    paragraphs = []
                    for p in soup.find_all(['p', 'pre', 'code', 'blockquote', 'li', 'h4', 'h5', 'div']):
                        txt = p.get_text().strip()
                        if txt and len(txt) > 5:
                            paragraphs.append(txt)
                            
                    full_text = "\n\n".join(paragraphs)
                    if len(full_text) < 150:
                        full_text = soup.get_text().strip()

                    clean_chap = clean_text(full_text)
                    if len(clean_chap) > 150 and is_valid_readable_text(clean_chap):
                        chapters.append({
                            "title": chap_title,
                            "content": clean_chap
                        })
                except Exception:
                    pass
    except Exception as e:
        log.warning(f"原生 zipfile 解析 EPUB 异常: {e}")
        
    return chapters


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
            "text": clean_text(text),
            "word_count": len(text)
        }
    else:
        raise ValueError(f"暂不支持的文件格式: {ext}")


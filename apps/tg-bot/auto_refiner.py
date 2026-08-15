#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import json
import logging
import requests
from pathlib import Path
from config import Config

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

CLIPPINGS_DIR = Path("/app/notes/Auto_Clippings")
SUMMARY_DIR = Path("/app/notes/Auto_Summary")

def _call_deepseek(text: str) -> str:
    """调用 DeepSeek 生成摘要"""
    url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {Config.DASHSCOPE_API_KEY}",
        "Content-Type": "application/json"
    }
    
    prompt = f"""你是一个个人知识库的智能提炼助手。
请对以下用户收集的内容进行深度提炼。请严格按以下格式输出，不要输出多余的解释：

1. **一句话核心总结**：（用最简练的语言概括核心）
2. **核心观点**：（提取3-5个核心 bullet points）
3. **洞察与启发**：（对此内容的深层思考、潜在价值或启发）
4. **推荐标签**：（例如：#AI #产品设计 #工具）

============== 原始内容 ==============
{text}
"""
    payload = {
        "model": Config.DASHSCOPE_CHAT_MODEL,
        "messages": [
            {"role": "user", "content": prompt}
        ]
    }
    
    proxies = {"http": Config.HTTP_PROXY, "https": Config.HTTPS_PROXY} if Config.HTTP_PROXY else None
    
    response = requests.post(url, json=payload, headers=headers, proxies=proxies, timeout=120)
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]

def main():
    if not CLIPPINGS_DIR.exists():
        logger.warning(f"目录不存在: {CLIPPINGS_DIR}")
        return
        
    SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
    
    logger.info("开始扫描 Auto_Clippings 目录...")
    
    for file_path in CLIPPINGS_DIR.glob("*.md"):
        if not file_path.is_file(): continue
            
        summary_path = SUMMARY_DIR / f"Refined_{file_path.name}"
        if summary_path.exists():
            # 已经处理过
            continue
            
        logger.info(f"正在处理: {file_path.name}")
        
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
                
            # 去除可能过长的内容（DeepSeek v4 支持长文本，但可以做个基础截断防爆内存，假设最大保留3万字）
            if len(content) > 30000:
                content = content[:30000] + "\n\n... (由于篇幅限制，内容已截断)"
                
            summary = _call_deepseek(content)
            
            # 追加原文引用 (Obsidian WikiLink 格式)
            # 因为文件都在notes目录下，[[Auto_Clippings/xxx.md]] 或者直接写相对路径
            original_link_name = file_path.name.replace(".md", "")
            final_content = f"{summary}\n\n---\n> [!quote] 引用来源\n> 原文：[[{original_link_name}]]\n"
            
            with open(summary_path, "w", encoding="utf-8") as f:
                f.write(final_content)
                
            logger.info(f"✅ 处理完成: {summary_path.name}")
            
        except Exception as e:
            logger.error(f"处理失败 {file_path.name}: {e}")

if __name__ == "__main__":
    main()

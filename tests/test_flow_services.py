#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import unittest
import struct
import math
from pathlib import Path

# Setup paths
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir / "apps" / "tg-bot"))
sys.path.insert(0, str(root_dir / "apps" / "rss-fetcher"))

from services.obsidian import sanitize_filename
from services.downloader import (
    is_video_url,
    extract_url,
    extract_group_id,
    build_toutiao_url
)
from services.rag import cosine_similarity, float_array_to_blob

class TestSecondBrainFlow(unittest.TestCase):

    def test_sanitize_filename_length_and_characters(self):
        """测试文件名防崩溃截断与特殊字符清洗"""
        raw_long_title = "【重大新闻】这是一个极其冗长的视频标题，包含了各种特殊符号：/?*#%&+=！!？以及超长文字" * 5
        clean = sanitize_filename(raw_long_title)
        
        # 1. 长度限制 <= 60 字符
        self.assertLessEqual(len(clean), 60)
        # 2. 不能包含 Windows / URL 非法字符
        for invalid_char in ['\\', '/', ':', '*', '?', '"', '<', '>', '|', '#', '%', '&', '+', '=']:
            self.assertNotIn(invalid_char, clean)
        # 3. 首尾不能有点或空格
        self.assertFalse(clean.startswith('.') or clean.startswith(' '))
        self.assertFalse(clean.endswith('.') or clean.endswith(' '))

    def test_downloader_url_detection(self):
        """测试视频链接与图文短链提取逻辑"""
        # 视频链接
        yt_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        self.assertTrue(is_video_url(yt_url))
        
        tt_url = "https://www.toutiao.com/video/7123456789012345678/"
        self.assertTrue(is_video_url(tt_url))
        
        # 提取 URL
        text_with_url = "快看这个视频：https://v.douyin.com/abc1234/ 真的太精彩了！"
        extracted = extract_url(text_with_url)
        self.assertEqual(extracted, "https://v.douyin.com/abc1234/")
        
        # Group ID 提取
        group_id = extract_group_id("https://www.toutiao.com/video/7123456789012345678/?wid=123")
        self.assertEqual(group_id, "7123456789012345678")
        self.assertEqual(build_toutiao_url(group_id), "https://www.toutiao.com/video/7123456789012345678/")

    def test_rag_vector_conversion(self):
        """测试 RAG 向量编解码与余弦相似度计算"""
        # 1. 余弦相似度
        v1 = [1.0, 0.0, 0.0]
        v2 = [1.0, 0.0, 0.0]
        v3 = [0.0, 1.0, 0.0]
        self.assertAlmostEqual(cosine_similarity(v1, v2), 1.0)
        self.assertAlmostEqual(cosine_similarity(v1, v3), 0.0)
        
        # 2. Float array to F32 BLOB
        emb = [0.123, -0.456, 0.789]
        blob = float_array_to_blob(emb)
        self.assertEqual(len(blob), len(emb) * 4) # 3 * 4 = 12 bytes
        unpacked = struct.unpack(f'{len(emb)}f', blob)
        for original, restored in zip(emb, unpacked):
            self.assertAlmostEqual(original, restored, places=5)

    def test_rss_feeds_configuration(self):
        """测试 RSS 信息源配置格式完整性"""
        from rss_fetcher import RSS_FEEDS
        self.assertGreater(len(RSS_FEEDS), 0)
        for feed in RSS_FEEDS:
            self.assertIn("name", feed)
            self.assertIn("urls", feed)
            self.assertIn("type", feed)
            self.assertIn(feed["type"], ["youtube", "reddit", "substack"])
            self.assertTrue(len(feed["urls"]) > 0)
            for u in feed["urls"]:
                self.assertTrue(u.startswith("http://") or u.startswith("https://"))

    def test_cleaner_pruning_logic(self):
        """测试过期草稿自动清理逻辑"""
        import tempfile
        import time
        from config import Config
        from services.cleaner import auto_prune_inbox
        
        with tempfile.TemporaryDirectory() as tmpdir:
            old_path = Config.OBSIDIAN_INBOX_PATH
            Config.OBSIDIAN_INBOX_PATH = Path(tmpdir)
            try:
                # 创建一个新鲜文件
                fresh_file = Path(tmpdir) / "fresh_note.md"
                fresh_file.write_text("fresh content", encoding="utf-8")
                
                # 创建一个过期文件 (模拟 40 天前)
                old_file = Path(tmpdir) / "old_note.md"
                old_file.write_text("old content", encoding="utf-8")
                past_time = time.time() - (40 * 86400)
                os.utime(old_file, (past_time, past_time))
                
                removed = auto_prune_inbox()
                self.assertEqual(removed, 1)
                self.assertTrue(fresh_file.exists())
                self.assertFalse(old_file.exists())
            finally:
                Config.OBSIDIAN_INBOX_PATH = old_path

if __name__ == "__main__":
    unittest.main()

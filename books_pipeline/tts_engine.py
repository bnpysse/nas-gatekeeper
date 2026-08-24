#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
第二大脑·AI 智能图书馆：男女双声多轨听书播客 TTS 引擎
将 Markdown 对谈剧本精准分段，分别由男声（睿哥）与女声（小林）合成，并注入自然微停顿缝合输出高保真音频。
"""

import os
import re
import sys
import logging
import asyncio
import tempfile
from pathlib import Path
from typing import List, Tuple

import edge_tts
from pydub import AudioSegment

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("TTSEngine")

# =========================================================================
# 音色与声线角色配置 (一男一女标准配置)
# =========================================================================
VOICE_MALE = "zh-CN-YunyangNeural"      # 睿哥：沉稳、专业、资深架构师/技术老兵
VOICE_FEMALE = "zh-CN-XiaoxiaoNeural"   # 小林：灵动、温和、敏锐求知学员

RATE_MALE = "+0%"
PITCH_MALE = "+0Hz"

RATE_FEMALE = "+4%"
PITCH_FEMALE = "+3Hz"

PAUSE_DURATION_MS = 350  # 对话轮次之间的自然思考微停顿 (毫秒)


def parse_podcast_script(script_text: str) -> List[Tuple[str, str]]:
    """
    解析 Markdown 播客剧本，提取发言人与对应台词
    返回: [("male", "大家好我是睿哥..."), ("female", "睿哥今天我们聊什么呢..."), ...]
    """
    dialogues: List[Tuple[str, str]] = []
    
    # 清理非台词部分 (如 Markdown 标题、括号说明、分割线)
    lines = script_text.splitlines()
    
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("---") or line.startswith("```"):
            continue
            
        # 匹配发言人前缀，例如：
        # **睿哥**：... / 睿哥: ... / [睿哥] ... / 【睿哥】...
        # **小林**：... / 小林: ... / [小林] ... / 【小林】...
        match_male = re.match(r"^(?:\*\*|\*|\[|【)?(?:睿哥|男|HostA|Speaker1)(?:\*\*|\*|\]|】)?\s*[:：]\s*(.+)$", line, re.IGNORECASE)
        match_female = re.match(r"^(?:\*\*|\*|\[|【)?(?:小林|晓雨|女|HostB|Speaker2)(?:\*\*|\*|\]|】)?\s*[:：]\s*(.+)$", line, re.IGNORECASE)
        
        if match_male:
            content = match_male.group(1).strip()
            # 过滤台词内的括号动作提示，如 (笑) [沉思] （翻书声）
            content = re.sub(r"[\(（\[【][^\)）\]】]*[\)）\]】]", "", content).strip()
            if content:
                dialogues.append(("male", content))
        elif match_female:
            content = match_female.group(1).strip()
            content = re.sub(r"[\(（\[【][^\)）\]】]*[\)）\]】]", "", content).strip()
            if content:
                dialogues.append(("female", content))
        else:
            # 如果行首无明确前缀但有内容，若上一句存在则追加
            if dialogues and not line.startswith(">"):
                cleaned = re.sub(r"[\(（\[【][^\)）\]】]*[\)）\]】]", "", line).strip()
                if cleaned:
                    last_role, last_content = dialogues[-1]
                    dialogues[-1] = (last_role, f"{last_content} {cleaned}")
                    
    return dialogues


async def synthesize_segment(role: str, text: str, output_file: str):
    """合成单条语音片段"""
    if role == "male":
        voice = VOICE_MALE
        rate = RATE_MALE
        pitch = PITCH_MALE
    else:
        voice = VOICE_FEMALE
        rate = RATE_FEMALE
        pitch = PITCH_FEMALE
        
    communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate, pitch=pitch)
    await communicate.save(output_file)


async def generate_podcast_audio(script_path: str | Path, output_audio_path: str | Path = None) -> str:
    """
    端到端：从 Markdown 剧本生成男女双声对谈音频 (.mp3)
    """
    script_path = Path(script_path)
    if not script_path.exists():
        raise FileNotFoundError(f"剧本文件未找到: {script_path}")
        
    if output_audio_path is None:
        output_audio_path = script_path.parent / f"{script_path.stem}.mp3"
    else:
        output_audio_path = Path(output_audio_path)
        
    logger.info(f"🎙️ 开始解析剧本: {script_path.name}")
    script_text = script_path.read_text(encoding="utf-8")
    dialogues = parse_podcast_script(script_text)
    
    if not dialogues:
        raise ValueError("未能从剧本中识别出有效的对谈台词，请检查剧本格式是否包含 [睿哥] / [小林] 前缀")
        
    male_count = sum(1 for role, _ in dialogues if role == "male")
    female_count = sum(1 for role, _ in dialogues if role == "female")
    logger.info(f"📊 解析完成: 发现 {len(dialogues)} 轮对话 (👨 睿哥: {male_count} 句, 👩 小林: {female_count} 句)")
    
    # 创建临时目录存放语音切片
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_dir_path = Path(tmp_dir)
        segment_files = []
        
        logger.info(f"⚡ 正在并发合成 {len(dialogues)} 段男女语音切片...")
        tasks = []
        for i, (role, text) in enumerate(dialogues):
            seg_path = tmp_dir_path / f"seg_{i:04d}_{role}.mp3"
            segment_files.append((role, seg_path))
            tasks.append(synthesize_segment(role, text, str(seg_path)))
            
        # 并发合成 (带限流控制)
        semaphore = asyncio.Semaphore(5)
        async def sem_task(t):
            async with semaphore:
                await t
        await asyncio.gather(*(sem_task(t) for t in tasks))
        
        logger.info("🎵 语音切片全部合成完毕，正在进行多轨缝合与自然停顿注入...")
        
        # 使用 pydub 拼接音频并在轮次间插入停顿
        combined = AudioSegment.empty()
        pause_segment = AudioSegment.silent(duration=PAUSE_DURATION_MS)
        
        for i, (role, seg_path) in enumerate(segment_files):
            if seg_path.exists() and seg_path.stat().st_size > 0:
                audio_seg = AudioSegment.from_file(str(seg_path), format="mp3")
                combined += audio_seg
                # 在对话轮次之间添加自然微停顿
                if i < len(segment_files) - 1:
                    combined += pause_segment
                    
        # 导出为最终音频 (.m4a AAC 为移动端、Obsidian 与 Telegram 原生高质量格式)
        if output_audio_path.suffix.lower() == ".mp3":
            output_audio_path = output_audio_path.with_suffix(".m4a")
            
        output_audio_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            combined.export(str(output_audio_path), format="ipod", codec="aac", bitrate="192k")
        except Exception:
            # 降级导出为标准 wav 或 aac
            combined.export(str(output_audio_path), format="adts", codec="aac")
        
        duration_sec = len(combined) / 1000.0
        logger.info(f"✅ 双人听书播客音频生成成功: {output_audio_path} (时长: {duration_sec:.1f} 秒, 文件大小: {output_audio_path.stat().st_size / 1024 / 1024:.2f} MB)")
        
    return str(output_audio_path)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        target_script = sys.argv[1]
    else:
        # 默认找一个现成的剧本进行测试
        target_script = "/Users/woodman/dev/nas-gatekeeper/books_pipeline/output/[Podcast]Haskell (almost) Standard Libraries (Alejandro Serrano Mena) (Z-Library)_剧本.md"
        
    if os.path.exists(target_script):
        asyncio.run(generate_podcast_audio(target_script))
    else:
        print(f"请提供剧本路径: python3 -m books_pipeline.tts_engine <script.md>")

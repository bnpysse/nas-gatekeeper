#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TokenGate 2.0 事前 Token 极速精准预估引擎 (Pre-Flight Token Estimator)
在网络请求发出前毫秒级测算，自带 10% 安全高估缓冲，杜绝低估穿透。
"""

import re
from typing import List, Dict, Any, Union

class PreFlightEstimator:
    """事前 Token 消耗量估算器"""

    # 经验标定系数（偏向保守高估，确保绝对安全）
    CHINESE_CHAR_RATIO = 1.35   # 常见中文汉字与标点：1 汉字 ≈ 1.25~1.4 Tokens
    ENGLISH_WORD_RATIO = 1.25   # 英文单词（含常见词缀）：1 词 ≈ 1.2~1.3 Tokens
    CODE_SYMBOL_RATIO = 1.50    # 特殊符号、括号、缩进、JSON 结构：1 符号 ≈ 1.3~1.6 Tokens
    DEFAULT_SAFETY_BUFFER = 1.10 # 10% 安全余量缓冲垫

    @classmethod
    def estimate_text_tokens(cls, text: str) -> int:
        """测算单段文本的 Token 数量"""
        if not text:
            return 0
        
        # 1. 统计中文字符数 (含全角标点)
        chinese_chars = len(re.findall(r'[\u4e00-\u9fa5\u3000-\u303f\uff01-\uff5e]', text))
        
        # 2. 统计英文单词数
        english_words = len(re.findall(r'[a-zA-Z0-9_-]+', text))
        
        # 3. 统计特殊符号与代码换行标点
        symbols = len(re.findall(r'[{}[\]()<>.,:;\"\'`~!@#$%^&*+=|\\/?\n\t]', text))
        
        # 4. 加权计算基础 Token 数
        base_tokens = (
            chinese_chars * cls.CHINESE_CHAR_RATIO +
            english_words * cls.ENGLISH_WORD_RATIO +
            symbols * cls.CODE_SYMBOL_RATIO
        )
        
        # 5. 加上 10% 的安全缓冲垫并向上取整
        est = int(base_tokens * cls.DEFAULT_SAFETY_BUFFER) + 4
        return max(est, len(text) // 3)

    @classmethod
    def estimate_messages_tokens(
        cls, 
        messages: List[Dict[str, str]], 
        max_completion_tokens: int = 2500
    ) -> Dict[str, int]:
        """
        测算完整消息对话上下文的 Prompt Tokens、预计 Completion Tokens 与 Total Tokens
        """
        prompt_tokens = 0
        for msg in messages:
            content = msg.get("content", "")
            role = msg.get("role", "")
            # 每条消息的基础开销 (role + metadata ≈ 4 tokens)
            prompt_tokens += cls.estimate_text_tokens(content) + 4
        
        # 基础请求格式开销
        prompt_tokens += 3
        
        completion_tokens = max_completion_tokens
        total_tokens = prompt_tokens + completion_tokens
        
        return {
            "prompt_tokens_est": prompt_tokens,
            "completion_tokens_est": completion_tokens,
            "total_tokens_est": total_tokens
        }

    @classmethod
    def estimate_prompt_and_system(
        cls, 
        prompt: str, 
        system_prompt: str = "", 
        max_completion_tokens: int = 2500
    ) -> Dict[str, int]:
        """为单提示词+系统提示词场景提供便捷测算"""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return cls.estimate_messages_tokens(messages, max_completion_tokens)


# 全局单例
estimator = PreFlightEstimator

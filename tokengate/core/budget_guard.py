#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TokenGate 2.0 日配额水库与安全硬锁门神 (Budget Guard & Quota Watermark Manager)
1. 设立 180 万（90% 安全水位）绝对硬上限，留足 20 万 Token 缓冲；
2. 彻底拉黑/锁死豆包（0.2 系数模型）；
3. 纯本地 SQLite 原子计数，随自然日 (00:00:00) 自动归档重置；
4. 任何请求超额前直接本地硬拦截改道，杜绝一切穿透扣费。
"""

import os
import sqlite3
import datetime
import logging
from typing import Dict, Any, Tuple, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "daily_budget.db"


class BudgetGuard:
    """日预算与安全水库门神"""

    # 各模型每日绝对硬顶限制 (Tokens / 天)
    MODEL_HARD_LIMITS = {
        # 火山方舟 1:1 满额返还旗舰 (上限 200 万，硬锁阈值 180 万 90%)
        "volcengine/deepseek-v4-pro": 1_800_000,
        "volcengine/glm-5.2": 1_800_000,
        "volcengine/deepseek-v4-flash": 1_800_000,
        "ep-20260820195716-snkzx": 1_800_000, # DeepSeek-V4-Pro Endpoint
        "ep-20260814105356-zvsw5": 1_800_000, # GLM-5.2 Endpoint
        "ep-20260809122445-td2g2": 1_800_000, # DeepSeek-V4-Flash Endpoint

        # 豆包自进化：0.2 极低回馈系数，彻底硬锁拉黑 (限额 0，绝对禁止调用)
        "volcengine/doubao-evolving": 0,
        "ep-20260814105629-t99mw": 0,

        # 硅基流动 0 元免费模型 (无限额度)
        "siliconflow/deepseek-ai/DeepSeek-V3": 999_999_999,
        "siliconflow/deepseek-ai/DeepSeek-R1": 999_999_999,
        "siliconflow/BAAI/bge-m3": 999_999_999,
        "siliconflow/FunAudioLLM/SenseVoiceSmall": 999_999_999,
    }

    # 规范化映射表
    MODEL_ALIAS_MAP = {
        "deepseek-v4-pro": "volcengine/deepseek-v4-pro",
        "deepseek-v4": "volcengine/deepseek-v4-pro",
        "ep-20260820195716-snkzx": "volcengine/deepseek-v4-pro",
        
        "glm-5.2": "volcengine/glm-5.2",
        "glm": "volcengine/glm-5.2",
        "ep-20260814105356-zvsw5": "volcengine/glm-5.2",
        
        "deepseek-v4-flash": "volcengine/deepseek-v4-flash",
        "flash": "volcengine/deepseek-v4-flash",
        "ep-20260809122445-td2g2": "volcengine/deepseek-v4-flash",

        "doubao-evolving": "volcengine/doubao-evolving",
        "doubao": "volcengine/doubao-evolving",
        "ep-20260814105629-t99mw": "volcengine/doubao-evolving",

        "deepseek-v3": "siliconflow/deepseek-ai/DeepSeek-V3",
        "deepseek-ai/DeepSeek-V3": "siliconflow/deepseek-ai/DeepSeek-V3",
    }

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """初始化每日预算数据库"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS daily_token_usage (
                date_str TEXT NOT NULL,
                model_key TEXT NOT NULL,
                provider TEXT NOT NULL,
                prompt_tokens INTEGER DEFAULT 0,
                completion_tokens INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                call_count INTEGER DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (date_str, model_key)
            );
            """)
            conn.commit()

    def _get_today_str(self) -> str:
        """获取当前本地自然日字符串 YYYY-MM-DD"""
        return datetime.datetime.now().strftime("%Y-%m-%d")

    def normalize_model_key(self, raw_model: str) -> str:
        """规范化模型标识"""
        cleaned = raw_model.strip().lower()
        if cleaned in self.MODEL_ALIAS_MAP:
            return self.MODEL_ALIAS_MAP[cleaned]
        for alias, target in self.MODEL_ALIAS_MAP.items():
            if alias in cleaned:
                return target
        return raw_model

    def get_current_usage(self, model_key: str, today_str: Optional[str] = None) -> int:
        """查询指定模型今日已累计消耗的 Tokens"""
        today = today_str or self._get_today_str()
        norm_key = self.normalize_model_key(model_key)
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT total_tokens FROM daily_token_usage WHERE date_str = ? AND model_key = ?",
                (today, norm_key)
            )
            row = cursor.fetchone()
            return int(row[0]) if row else 0

    def can_allocate(self, model_key: str, est_tokens: int) -> Tuple[bool, int, int, float, str]:
        """
        事前预算准入判定：
        返回: (是否允许调用, 当前消耗量, 硬上限限额, 当前水位占比, 判定原因)
        """
        norm_key = self.normalize_model_key(model_key)
        limit = self.MODEL_HARD_LIMITS.get(norm_key, 1_800_000)
        
        # 1. 针对豆包等被拉黑模型，直接拒绝
        if limit == 0:
            return False, 0, 0, 1.0, f"🚫 模型 [{norm_key}] 属于低回馈付费模型，已被 TokenGate 2.0 永久硬锁拉黑"

        # 2. 针对无限额度的免费模型 (如 SiliconFlow)，无条件放行
        if limit >= 999_999_999:
            curr = self.get_current_usage(norm_key)
            return True, curr, limit, 0.0, f"🟢 0元原生免费模型 [{norm_key}]，无配额上限放行"

        # 3. 针对火山 1:1 旗舰模型，严格校验 180 万安全水位
        current_used = self.get_current_usage(norm_key)
        projected = current_used + est_tokens
        ratio = round(current_used / limit, 4)

        if projected <= limit:
            return True, current_used, limit, ratio, f"🟢 水位安全 ({current_used:,}/{limit:,} Tokens, 占比 {ratio*100:.1f}%)，批准调用"
        else:
            return False, current_used, limit, ratio, f"🚨 触顶熔断：今日已用 {current_used:,} + 本次预估 {est_tokens:,} = {projected:,} Tokens 将超过 180万安全水位硬顶，已自动拦截改道！"

    def record_usage(
        self, 
        model_key: str, 
        actual_tokens: int, 
        prompt_tokens: int = 0, 
        completion_tokens: int = 0,
        provider: str = ""
    ):
        """实际请求完成后，原子累加回写今日真实消耗台账"""
        if actual_tokens <= 0:
            return
            
        today = self._get_today_str()
        norm_key = self.normalize_model_key(model_key)
        
        if not provider:
            provider = norm_key.split("/")[0] if "/" in norm_key else "unknown"

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO daily_token_usage (date_str, model_key, provider, prompt_tokens, completion_tokens, total_tokens, call_count, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
            ON CONFLICT(date_str, model_key) DO UPDATE SET
                prompt_tokens = prompt_tokens + excluded.prompt_tokens,
                completion_tokens = completion_tokens + excluded.completion_tokens,
                total_tokens = total_tokens + excluded.total_tokens,
                call_count = call_count + 1,
                updated_at = CURRENT_TIMESTAMP;
            """, (today, norm_key, provider, prompt_tokens, completion_tokens, actual_tokens))
            conn.commit()

    def get_watermark_status(self) -> Dict[str, Any]:
        """获取全景水库实时水位仪表盘数据"""
        today = self._get_today_str()
        
        tracked_models = [
            {
                "key": "volcengine/deepseek-v4-pro",
                "name": "DeepSeek-V4-Pro",
                "provider": "火山方舟 (VolcEngine)",
                "limit": 1_800_000,
                "official_cap": 2_000_000,
                "rebate_rate": "1:1 满额循环免费",
                "task_desc": "深度推演 / 架构拓扑 / 考题命制"
            },
            {
                "key": "volcengine/glm-5.2",
                "name": "智谱 GLM-5.2",
                "provider": "火山方舟 (VolcEngine)",
                "limit": 1_800_000,
                "official_cap": 2_000_000,
                "rebate_rate": "1:1 满额循环免费",
                "task_desc": "章节级 20% 去水提炼 / 文脉梳理"
            },
            {
                "key": "volcengine/deepseek-v4-flash",
                "name": "DeepSeek-V4-Flash",
                "provider": "火山方舟 (VolcEngine)",
                "limit": 1_800_000,
                "official_cap": 2_000_000,
                "rebate_rate": "1:1 满额循环免费",
                "task_desc": "极速清洗 / 双语速读"
            },
            {
                "key": "siliconflow/deepseek-ai/DeepSeek-V3",
                "name": "DeepSeek-V3 (671B MoE)",
                "provider": "硅基流动 (SiliconFlow)",
                "limit": 999_999_999,
                "official_cap": 999_999_999,
                "rebate_rate": "原生 0 元永久免费",
                "task_desc": "无限吞吐保底 / 熔断接力池"
            }
        ]

        reservoirs = []
        total_used_today = 0
        total_safe_capacity = 5_400_000 # 3 大旗舰 180 万合计

        for m in tracked_models:
            used = self.get_current_usage(m["key"], today)
            if m["limit"] < 999_999_999:
                total_used_today += used
                ratio = min(round(used / m["limit"], 4), 1.0)
                status = "safe" if ratio < 0.85 else ("warning" if ratio < 1.0 else "locked")
            else:
                ratio = 0.0
                status = "unlimited"

            reservoirs.append({
                "model_key": m["key"],
                "model_name": m["name"],
                "provider": m["provider"],
                "used_tokens": used,
                "hard_limit": m["limit"],
                "official_cap": m["official_cap"],
                "watermark_ratio": ratio,
                "watermark_percent": f"{ratio*100:.1f}%",
                "status": status,
                "rebate_rate": m["rebate_rate"],
                "task_desc": m["task_desc"]
            })

        # 估算今日节省金额 (按每百万 Tokens 2~4 元估算)
        saved_cny = round(total_used_today * 0.0000035, 2)

        return {
            "date": today,
            "total_used_today": total_used_today,
            "total_safe_capacity": total_safe_capacity,
            "total_watermark_percent": f"{min(round(total_used_today / total_safe_capacity, 4)*100, 100):.1f}%",
            "saved_cny_estimate": saved_cny,
            "reservoirs": reservoirs
        }


# 全局单例
budget_guard = BudgetGuard()

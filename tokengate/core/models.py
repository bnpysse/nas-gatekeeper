#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TokenGate Pydantic 数据模型定义
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from enum import Enum


class TaskType(str, Enum):
    GENERAL = "general"          # 通用对话/问答
    CODING = "coding"            # 编程与代码实现
    REASONING = "reasoning"      # 深度链式推理 / 量化审计
    SUMMARY = "summary"          # 长文本分析与速读
    VISION = "vision"            # 多模态视觉与图表分析
    EMBEDDING = "embedding"      # 向量化与知识库嵌入
    RERANK = "rerank"            # 语义检索重排


class StrategyType(str, Enum):
    EXPIRING_FIRST = "expiring_first"      # 临期优先（优先消耗即将过期的免费额度）
    DAILY_FIRST = "daily_first"            # 循环保底（优先消耗每日重置的免费额度）
    MAX_CAPABILITY = "max_capability"      # 战力天花板（无条件选用任务匹配的最强旗舰模型）
    FASTEST = "fastest"                    # 极速模式（选用响应最快的 Flash 模型）


class ModelItem(BaseModel):
    id: str                                # 模型唯一标识 (如 deepseek-ai/DeepSeek-V4-Pro)
    name: str                              # 易读名称
    provider: str                          # 所属平台 (dashscope, volcengine, modelscope, gemini, etc.)
    context_window: str = "32K"            # 上下文窗口
    is_free: bool = True                   # 是否为免费/0元模型
    tier_desc: str = ""                    # 档位描述
    days_left: Optional[int] = None        # 距离过期剩余天数 (None 表示每日循环或永久)
    expire_date: Optional[str] = None      # 到期日期 (YYYY-MM-DD)
    total_quota: Optional[str] = None      # 免费额度总量 (如 1M tokens)
    used_quota: Optional[str] = None       # 已消耗额度
    remaining_ratio: float = 1.0           # 剩余比例 (0.0 ~ 1.0)
    category: str = "chat"                 # chat, code, reasoning, vision, embedding, rerank
    latency_ms: int = 0                    # 测速延迟


class ProviderQuota(BaseModel):
    provider_id: str                       # dashscope, volcengine, modelscope, gemini, deepseek, siliconflow
    provider_name: str                     # 显示名称
    status: str                            # 在线 (正常), 未配置, 异常
    active: bool                           # 是否可用
    latency_ms: int = 0                    # 整体 API 探测延迟
    masked_key: str = ""                   # 脱敏后的密钥指纹 (如 ms-2b89****ffe54)
    balance_info: str = ""                 # 余额或配额说明
    pricing_type: str = ""                 # 计费类型 (0元免费, 每日循环, 赠送包)
    rate_limits: str = ""                  # 速率限制
    models: List[ModelItem] = Field(default_factory=list)
    expiring_count: int = 0                # 7天内即将过期的模型数


class QuotaSummary(BaseModel):
    updated_at: str                        # 最后更新时间
    total_providers: int                   # 总平台数
    active_providers: int                  # 在线平台数
    total_free_models: int                 # 累计可用免费模型数
    urgent_expiring_models: int            # 7天内紧急临期模型数
    daily_replenish_tokens: str = "200万+ / 天" # 每日循环补给算力
    providers: Dict[str, ProviderQuota] = Field(default_factory=dict)


class RecommendationResult(BaseModel):
    task: TaskType
    strategy: StrategyType
    recommended_model: ModelItem
    reason: str
    backup_models: List[ModelItem] = Field(default_factory=list)

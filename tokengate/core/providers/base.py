#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TokenGate Provider 抽象基类
"""

from abc import ABC, abstractmethod
from ..models import ProviderQuota

class BaseProvider(ABC):
    provider_id: str
    provider_name: str

    @abstractmethod
    async def detect(self) -> ProviderQuota:
        """异步执行平台配额、健康度与可用模型探测"""
        pass

"""
天眼全息智导系统 V6.0 — 数据模型与常量定义

所有维度名称、指标列名、窗口周期等集中管理，
供 engine / signals / 前端共同引用。
"""
from dataclasses import dataclass, field

# ==========================================
# 核心数值列 (CSV 原始列，需要清污脱敏)
# ==========================================
NUMERIC_COLS: list[str] = [
    "Main_Pct", "Dare_Pct", "ASR", "CYS34", "LFS",
    "Turnover", "PTR", "D_Pos", "Close", "HCCYF13",
    "Y_Overlap", "Open", "High", "Low",
    "X70", "X90", "Z_Profit", "DeltaX",
]

# ==========================================
# 时空窗口 (Fibonacci 周期)
# ==========================================
FIB_PERIODS: list[tuple[str, int]] = [
    ("全部数据", 0),
    ("5日 (极短探测)", 5),
    ("13日 (Fib短)", 13),
    ("34日 (Fib中)", 34),
    ("55日 (Fib长)", 55),
    ("132日 (战略底座)", 132),
]

# ==========================================
# 维五专属均线周期
# ==========================================
DIM5_MA_PERIODS: list[tuple[str, int]] = [
    ("5日 (短线游资)", 5),
    ("10日 (波段中枢)", 10),
    ("20日 (标准月线)", 20),
    ("多维共振 (5日+20日)", 0),
]

# ==========================================
# Fibonacci 全局 PTR 均线窗口
# ==========================================
FIB_PTR_WINDOWS: list[int] = [5, 13, 21, 34]

# ==========================================
# 资金面累积窗口
# ==========================================
FUND_WINDOWS: list[int] = [5, 22, 66, 132]

FUND_WINDOW_LABELS: dict[int, str] = {
    5: "周线",
    22: "月线",
    66: "季线",
    132: "半年线",
}

# ==========================================
# 维度定义
# ==========================================
@dataclass(frozen=True)
class DimensionDef:
    """单个雷达维度的元数据"""
    index: int
    title: str
    subtitle: str
    primary_color: str
    indicators: list[str] = field(default_factory=list)
    fund_window: int = 0  # 对应资金背景的窗口天数


DIMENSIONS: list[DimensionDef] = [
    DimensionDef(
        index=1,
        title="底座阵地",
        subtitle="长短防线 | 资金背景: 半年线",
        primary_color="#3B82F6",
        indicators=["LFS", "HCCYF13", "Close"],
        fund_window=132,
    ),
    DimensionDef(
        index=2,
        title="抛压真空",
        subtitle="Z' 透视 | 资金背景: 季线",
        primary_color="#FFD700",
        indicators=["Z_diff1", "CYS34"],
        fund_window=66,
    ),
    DimensionDef(
        index=3,
        title="活筹点火",
        subtitle="单日流速 vs 锁仓 | 资金背景: 月线",
        primary_color="#EC4899",
        indicators=["PTR", "D_Pos"],
        fund_window=22,
    ),
    DimensionDef(
        index=4,
        title="情绪极值",
        subtitle="活筹残量 | 资金背景: 周线",
        primary_color="#A855F7",
        indicators=["Y_Overlap", "ASR"],
        fund_window=5,
    ),
    DimensionDef(
        index=5,
        title="量筹剪刀差",
        subtitle="表象换手 vs 真实内驱",
        primary_color="#F97316",
        indicators=["Turnover", "PTR"],
        fund_window=0,
    ),
]

# ==========================================
# 标的信息
# ==========================================
@dataclass
class TARGET_INFO:
    code: str
    name: str

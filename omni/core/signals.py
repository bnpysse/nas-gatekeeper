"""
天眼全息智导系统 V6.0 — 五维信号判定引擎

从原 radar_v52.py 的 update_hud_native() 中提取的
纯逻辑判定层，不依赖任何 UI 框架。
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class ZoneVerdict:
    """战区定性结果"""
    zone_code: str    # S / A / B / C
    zone_label: str   # 中文描述
    color: str        # 主题色
    command: str      # 战术裁决


@dataclass(frozen=True)
class MomentumTier:
    """动能等级 (维一专用)"""
    tier_label: str
    tier_color: str


class SignalJudge:
    """纯逻辑信号判定器，前端无关"""

    @staticmethod
    def judge_zone(scissor: float, slope_3d: float) -> ZoneVerdict:
        """
        基于剪刀差和3日斜率判定战区等级。

        S档 (Scissor > 20)：绝对护城河
        A档 (Scissor > 0, 斜率 > 0)：常规博弈
        B档 (Scissor > 0, 斜率 ≤ 0)：防线松动
        C档 (Scissor ≤ 0)：极寒死叉
        """
        if scissor > 20:
            return ZoneVerdict(
                zone_code="S",
                zone_label="★ S档：绝对护城河 (满配主升)",
                color="#FFD700",
                command="战术裁决：允许常规洗盘。防线极厚，绝不轻易交出底仓。",
            )
        elif scissor > 0:
            if slope_3d > 0:
                return ZoneVerdict(
                    zone_code="A",
                    zone_label="■ A档：常规博弈区 (点火上攻)",
                    color="#10B981",
                    command="战术裁决：动能健康。盯紧流速，跌破零轴前坚定持有。",
                )
            else:
                return ZoneVerdict(
                    zone_code="B",
                    zone_label="◆ B档：防线松动区 (滞涨预警)",
                    color="#F59E0B",
                    command="战术裁决：动能衰减。内部筹码松动，随时准备右侧止盈。",
                )
        else:
            return ZoneVerdict(
                zone_code="C",
                zone_label="✖ C档：极寒死叉区 (无条件清算)",
                color="#EF4444",
                command="战术裁决：防线崩塌，右侧杀跌风险极高！立刻清仓！",
            )

    @staticmethod
    def judge_momentum(slope_3d: float) -> MomentumTier:
        """维一动能等级判定 (VMA 3日斜率)"""
        if slope_3d > 2.0:
            return MomentumTier("★ 点火级 (绝对主升)", "#FFD700")
        elif slope_3d > 0:
            return MomentumTier("■ 滞涨级 (动能衰减)", "#10B981")
        elif slope_3d > -2.0:
            return MomentumTier("◆ 松动级 (筹码外泄)", "#F59E0B")
        else:
            return MomentumTier("✖ 崩塌级 (恐慌抛售)", "#EF4444")

    @staticmethod
    def judge_z_quality(z_prime: float, turnover: float) -> str:
        """Z' 动能质量判定"""
        if z_prime > 10 and turnover < 5.0:
            return "极品无量穿透"
        elif z_prime > 10:
            return "真空爆破"
        elif z_prime > 0:
            return "正向动能"
        else:
            return "负向压制"

    @staticmethod
    def judge_fund_momentum(delta_sum_22d: float) -> tuple[str, str]:
        """月线资金势能判定 → (描述, 颜色)"""
        if delta_sum_22d > 1.0:
            return ("月线势能加速流入", "#EF4444")
        elif delta_sum_22d < -1.0:
            return ("月线势能向下破位", "#10B981")
        else:
            return ("势能胶着，多空弱平衡", "#E5E7EB")

    @staticmethod
    def get_z_bar_color(z_prime: float, turnover: float) -> str:
        """Z' 柱状图着色逻辑"""
        if z_prime > 10 and turnover < 5.0:
            return "#FFFFFF"   # 极品无量：白色
        elif z_prime > 0:
            return "#FFD700"   # 正向：金色
        else:
            return "#10B981"   # 负向：绿色

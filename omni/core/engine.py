"""
天眼全息智导系统 V6.0 — Polars 数据引擎

完整迁移自 radar_v52.py 的 Pandas 数据管线。
所有 groupby().transform() 改用 Polars 的 .over() 表达式。

使用方式：
    from core import OmniEngine
    engine = OmniEngine("stock.csv", "battle_plan.json")
    df = engine.get_stock_data("300475", days=34)
    snap = engine.get_latest_snapshot("300475")
"""
import json
import os
from pathlib import Path

import polars as pl

from core.models import (
    NUMERIC_COLS, FIB_PTR_WINDOWS, DIM5_MA_PERIODS,
    FUND_WINDOWS, TARGET_INFO,
)


class OmniEngine:
    """
    Polars 驱动的天眼数据引擎。

    初始化时完成全部清洗和派生计算，
    之后通过方法获取切片数据供前端消费。
    """

    def __init__(self, csv_path: str, battle_plan_path: str | None = None):
        self._csv_path = csv_path
        self._battle_plan_path = battle_plan_path

        # 自动识别代码列名
        raw = pl.read_csv(csv_path, infer_schema_length=5000)
        self._code_col = "Target_Code" if "Target_Code" in raw.columns else "Code"
        self._z_col = "Z_Profit" if "Z_Profit" in raw.columns else "Z"

        # 完整数据管线
        self._df = self._build_pipeline(raw)

        # 标的列表
        self._targets = self._load_targets()

    # ==========================================
    # 公共 API
    # ==========================================

    @property
    def df(self) -> pl.DataFrame:
        """完整的预处理后 DataFrame"""
        return self._df

    @property
    def code_col(self) -> str:
        return self._code_col

    def get_targets(self) -> list[TARGET_INFO]:
        """获取标的列表"""
        return self._targets

    def get_stock_data(self, code: str, days: int = 0) -> pl.DataFrame:
        """
        获取单标的数据切片。

        Args:
            code: 股票代码 (如 "300475")
            days: 截取最近 N 天，0 表示全部
        """
        code_padded = str(code).replace(".0", "").zfill(6)

        stock_df = self._df.filter(
            pl.col(self._code_col)
            .cast(pl.Utf8)
            .str.replace_all(r"\.0$", "")
            .str.zfill(6)
            == code_padded
        )

        if days > 0:
            stock_df = stock_df.tail(days)

        return stock_df

    def get_latest_snapshot(self, code: str) -> dict:
        """
        获取单标的最新一日的全维数据快照。

        返回一个 dict，键为列名，值为标量值。
        供 HUD 面板使用。
        """
        stock_df = self.get_stock_data(code, days=1)
        if stock_df.is_empty():
            return {}
        return stock_df.row(0, named=True)

    def get_all_codes(self) -> list[str]:
        """获取所有唯一股票代码"""
        return (
            self._df.select(
                pl.col(self._code_col)
                .cast(pl.Utf8)
                .str.replace_all(r"\.0$", "")
                .str.zfill(6)
            )
            .unique()
            .to_series()
            .to_list()
        )

    # ==========================================
    # 内部数据管线
    # ==========================================

    def _build_pipeline(self, raw: pl.DataFrame) -> pl.DataFrame:
        """
        完整的数据预处理管线，对应原 radar_v52.py L662-L726。

        执行顺序：
        1. 清污脱敏
        2. 资金合力
        3. Fibonacci PTR 均线
        4. 维五专属均线 + 斜率
        5. 多周期资金面累积
        6. 维度斜率 (一阶导)
        7. 双轨防线 (剪刀差 / 3日斜率)
        8. CYS13 代理
        9. 日期格式化
        """
        code = self._code_col

        # ── Step 1: 清污脱敏 ──
        df = self._sanitize_numeric(raw)

        # ── Step 2: 资金合力 ──
        df = df.with_columns(
            (pl.col("Main_Pct") + pl.col("Dare_Pct")).alias("Sum_Pct"),
        )
        df = df.with_columns(
            pl.col("Sum_Pct").diff(1).over(code).fill_null(0).alias("Delta_Sum_1d"),
        )

        # ── Step 3: Fibonacci 全局 PTR 均线 ──
        fib_exprs = [
            pl.col("PTR")
            .rolling_mean(window_size=p, min_periods=1)
            .over(code)
            .alias(f"PTR_MA{p}")
            for p in FIB_PTR_WINDOWS
        ]
        df = df.with_columns(fib_exprs)

        # ── Step 4: 维五专属均线 + 斜率 ──
        dim5_periods = [p for _, p in DIM5_MA_PERIODS if p > 0]  # [5, 10, 20]
        dim5_exprs = []
        for p in dim5_periods:
            dim5_exprs.extend([
                pl.col("Turnover")
                .rolling_mean(window_size=p, min_periods=1)
                .over(code)
                .alias(f"Turnover_MA{p}"),
                pl.col("PTR")
                .rolling_mean(window_size=p, min_periods=1)
                .over(code)
                .alias(f"PTR_MA{p}"),
            ])
        df = df.with_columns(dim5_exprs)

        # 斜率 (均线的一阶导)
        slope_exprs = []
        for p in dim5_periods:
            slope_exprs.extend([
                pl.col(f"Turnover_MA{p}").diff(1).over(code).fill_null(0).alias(f"Turnover_MA{p}_slope"),
                pl.col(f"PTR_MA{p}").diff(1).over(code).fill_null(0).alias(f"PTR_MA{p}_slope"),
            ])
        df = df.with_columns(slope_exprs)

        # ── Step 5: 多周期资金面累积 ──
        fund_exprs = []
        for w in FUND_WINDOWS:
            fund_exprs.extend([
                pl.col("Main_Pct").rolling_sum(window_size=w, min_periods=1).over(code).alias(f"Main_{w}d"),
                pl.col("Dare_Pct").rolling_sum(window_size=w, min_periods=1).over(code).alias(f"Dare_{w}d"),
                pl.col("Sum_Pct").rolling_sum(window_size=w, min_periods=1).over(code).alias(f"Sum_{w}d"),
            ])
        df = df.with_columns(fund_exprs)

        # 资金面势能 (Delta)
        delta_exprs = [
            pl.col(f"Sum_{w}d").diff(1).over(code).fill_null(0).alias(f"Delta_Sum_{w}d")
            for w in FUND_WINDOWS
        ]
        df = df.with_columns(delta_exprs)

        # ── Step 6: 维度斜率 (一阶导) ──
        df = df.with_columns([
            pl.col("LFS").diff(1).over(code).fill_null(0).alias("LFS_slope"),
            pl.col("HCCYF13").diff(1).over(code).fill_null(0).alias("HCCYF13_slope"),
            pl.col("ASR").diff(1).over(code).fill_null(0).alias("ASR_slope"),
            pl.col("Y_Overlap").diff(1).over(code).fill_null(0).alias("Y_Ovp_slope"),
            pl.col("PTR").diff(1).over(code).fill_null(0).alias("PTR_1d_slope"),
            pl.col(self._z_col).diff(1).over(code).fill_null(0).alias("Z_diff1"),
        ])

        # ── Step 7: 双轨防线引擎 ──
        df = df.with_columns(
            (pl.col("HCCYF13") - pl.col("LFS")).alias("Scissor"),
        )
        df = df.with_columns(
            pl.col("HCCYF13").shift(3).over(code).alias("HCCYF13_shift3"),
        )
        # fill_null 用原值填充头部缺失
        df = df.with_columns(
            pl.col("HCCYF13_shift3")
            .fill_null(pl.col("HCCYF13"))
            .alias("HCCYF13_shift3"),
        )
        df = df.with_columns(
            (pl.col("HCCYF13") - pl.col("HCCYF13_shift3")).alias("Slope_3d"),
        )

        # ── Step 8: CYS13 代理 ──
        if "Close" in df.columns:
            df = df.with_columns(
                pl.col("Close")
                .rolling_mean(window_size=13, min_periods=1)
                .over(code)
                .alias("_MA13"),
            )
            df = df.with_columns(
                ((pl.col("Close") - pl.col("_MA13")) / pl.col("_MA13") * 100)
                .alias("CYS13_Proxy"),
            )
            df = df.drop("_MA13")

        # ── Step 9: 日期格式化 ──
        df = df.with_columns(
            pl.col("Date").cast(pl.Utf8).alias("_date_str"),
        )
        df = df.with_columns(
            pl.col("_date_str").str.to_date("%Y%m%d", strict=False).alias("Date_parsed"),
        )
        df = df.with_columns([
            pl.col("Date_parsed")
            .dt.strftime("%m-%d")
            .fill_null(pl.col("_date_str").str.slice(-4))
            .alias("Date_Disp"),
            pl.col("Date_parsed")
            .dt.strftime("%Y-%m-%d")
            .fill_null(pl.col("_date_str"))
            .alias("Date_Full"),
        ])
        df = df.drop("_date_str")

        return df

    def _sanitize_numeric(self, df: pl.DataFrame) -> pl.DataFrame:
        """
        清污脱敏：移除百分号、逗号，强制转为 Float64。
        对应原 radar_v52.py L664-L671。
        """
        exprs = []
        for col in NUMERIC_COLS:
            if col not in df.columns:
                continue

            # 如果原始列是字符串类型，先清洗再转数值
            if df.schema[col] == pl.Utf8:
                exprs.append(
                    pl.col(col)
                    .str.replace_all("%", "")
                    .str.replace_all(",", "")
                    .cast(pl.Float64, strict=False)
                    .fill_null(0.0)
                    .alias(col)
                )
            else:
                # 已经是数值类型，只做 null 填充
                exprs.append(
                    pl.col(col)
                    .cast(pl.Float64, strict=False)
                    .fill_null(0.0)
                    .alias(col)
                )

        if exprs:
            df = df.with_columns(exprs)

        return df

    # ==========================================
    # 标的列表加载
    # ==========================================

    def _load_targets(self) -> list[TARGET_INFO]:
        """
        从 battle_plan.json 加载标的列表。
        若文件不存在，则从数据中推断。
        """
        targets = []

        if self._battle_plan_path and os.path.exists(self._battle_plan_path):
            with open(self._battle_plan_path, "r", encoding="utf-8") as f:
                plan = json.load(f)
                for code_str, name_val in plan.get("stock_names", {}).items():
                    targets.append(TARGET_INFO(code=code_str, name=name_val))

        if not targets:
            codes = self.get_all_codes()
            targets = [TARGET_INFO(code=c, name=f"标的 {c}") for c in codes]

        return targets


# ==========================================
# 便捷工厂函数
# ==========================================

def create_engine(base_dir: str | None = None) -> OmniEngine:
    """
    从指定目录或脚本所在目录创建引擎实例。

    Args:
        base_dir: 数据文件所在目录，默认为当前工作目录。
    """
    if base_dir is None:
        base_dir = str(Path(__file__).parent.parent)

    csv_path = os.path.join(base_dir, "data", "stock.csv")
    plan_path = os.path.join(base_dir, "data", "battle_plan.json")

    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"致命错误：未找到数据底座 {csv_path}")

    return OmniEngine(
        csv_path=csv_path,
        battle_plan_path=plan_path if os.path.exists(plan_path) else None,
    )

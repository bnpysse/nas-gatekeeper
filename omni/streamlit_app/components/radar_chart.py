"""
天眼全息智导系统 V6.0 — Plotly 五维雷达图表组件

五维子图(shared_xaxes)，Y 轴配置:
  - 右轴统一: 资金面红色刻度
  - 左轴双标注: 主指标 + 副指标各自颜色
  - 维一特殊: 三标注 (LFS蓝 + VMA黄 + Close灰)

维一: LFS/HCCYF13/Close + 资金面132d
维二: Z'柱 + CYS34 + 资金面66d
维三: PTR + D_Pos + 资金面22d
维四: Y_Overlap + ASR + 资金面5d
维五: Turnover_MA vs PTR_MA
"""
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import polars as pl

# ==========================================
# 颜色常量
# ==========================================
BG_COLOR = "#0B0F19"
PANEL_COLOR = "#1F2937"
GRID_COLOR = "#1F2937"
TEXT_COLOR = "#E5E7EB"
MUTE_COLOR = "#4B5563"

COLORS = {
    "lfs": "#3B82F6",
    "hccyf13": "#F59E0B",
    "close": "rgba(255,255,255,0.5)",
    "close_tick": "#9CA3AF",
    "z_gold": "#FFD700",
    "z_white": "#FFFFFF",
    "z_green": "#10B981",
    "cys34": "#38BDF8",
    "ptr": "#F97316",
    "dpos": "#EC4899",
    "y_overlap": "#A855F7",
    "asr": "#06B6D4",
    "turnover_ma": "#3B82F6",
    "ptr_ma": "#EF4444",
    "fund": "#EF4444",
    "fund_neg": "#10B981",
}

# make_subplots 生成的 Y 轴命名 (5行 × secondary_y):
# row1: yaxis/yaxis2, row2: yaxis3/yaxis4, row3: yaxis5/yaxis6
# row4: yaxis7/yaxis8, row5: yaxis9/yaxis10
# 额外手动添加: yaxis11 (dim1 Close), yaxis12 (dim2 CYS34),
#                yaxis13 (dim3 D_Pos), yaxis14 (dim4 ASR)

# 各行主 Y 轴 (left primary) 对应名称
_PRIMARY_Y = {1: "yaxis", 2: "yaxis3", 3: "yaxis5", 4: "yaxis7", 5: "yaxis9"}
# 各行 secondary Y 轴 (right, 用于资金) 对应名称
_SECONDARY_Y = {1: "yaxis2", 2: "yaxis4", 3: "yaxis6", 4: "yaxis8", 5: "yaxis10"}
# 各行 X 轴名称
_XAXIS = {1: "x", 2: "x2", 3: "x3", 4: "x4", 5: "x5"}
# 额外的第三 Y 轴 (left secondary)
_THIRD_Y = {1: "yaxis11", 2: "yaxis12", 3: "yaxis13", 4: "yaxis14"}
_THIRD_Y_REF = {1: "y11", 2: "y12", 3: "y13", 4: "y14"}
_OVERLAY_Y = {1: "y", 2: "y3", 3: "y5", 4: "y7"}


def _fund_axis_style(tick_color: str = COLORS["fund"]) -> dict:
    """右轴统一样式: 资金面"""
    return dict(
        gridcolor="rgba(0,0,0,0)",
        zerolinecolor=MUTE_COLOR,
        tickfont=dict(size=9, color=tick_color),
        tickformat=".0f",
        showgrid=False,
        showline=True,
        linewidth=1,
        linecolor=tick_color,
        ticks="outside",
        ticklen=3,
        tickcolor=tick_color,
    )


def _left_axis_style(tick_color: str = MUTE_COLOR) -> dict:
    """左轴样式: 带轴线和刻度线"""
    return dict(
        gridcolor=GRID_COLOR,
        zerolinecolor=MUTE_COLOR,
        tickfont=dict(size=9, color=tick_color),
        showline=True,
        linewidth=1,
        linecolor=tick_color,
        ticks="outside",
        ticklen=3,
        tickcolor=tick_color,
    )


def _third_axis_config(row: int, tick_color: str, anchor_x: str, overlay_y: str) -> dict:
    """第三 Y 轴配置 (左侧物理偏移, autoshift), 带轴线"""
    return dict(
        overlaying=overlay_y,
        side="left",
        anchor="free",
        autoshift=True,
        shift=-10,
        tickfont=dict(size=9, color=tick_color),
        gridcolor="rgba(0,0,0,0)",
        zerolinecolor="rgba(0,0,0,0)",
        showgrid=False,
        showline=True,
        linewidth=1,
        linecolor=tick_color,
        ticks="outside",
        ticklen=3,
        tickcolor=tick_color,
        title=None,
    )


def build_radar_figure(
    df: pl.DataFrame,
    stock_name: str,
    dim5_mode: int = 0,
) -> go.Figure:
    """构建五维雷达 Plotly Figure。"""
    dates = df["Date_Disp"].to_list()
    dates_full = df["Date_Full"].to_list()
    x = list(range(len(dates)))

    # 计算星期几: 周一=0 ... 周五=4
    WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    from datetime import datetime
    hover_labels = []
    for i, d in enumerate(dates_full):
        try:
            dt = datetime.strptime(str(d), "%Y-%m-%d")
            wd = WEEKDAYS[dt.weekday()]
        except (ValueError, IndexError):
            wd = ""
        hover_labels.append(f"#{i} | {d} ({wd})")

    fig = make_subplots(
        rows=5, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.035,
        row_heights=[0.22, 0.20, 0.20, 0.20, 0.18],
        subplot_titles=[
            "维度一：底座阵地 (LFS·VMA·价格 | 资金: 半年132d)",
            "维度二：抛压真空 (Z'·CYS34 | 资金: 季66d)",
            "维度三：活筹点火 (PTR·D_Pos | 资金: 月22d)",
            "维度四：情绪极值 (Y_Ovp·ASR | 资金: 周5d)",
            "维度五：量筹剪刀差",
        ],
        specs=[
            [{"secondary_y": True}],
            [{"secondary_y": True}],
            [{"secondary_y": True}],
            [{"secondary_y": True}],
            [{"secondary_y": True}],
        ],
    )

    # 渲染各维度 (传入 hover_labels)
    _render_dim1(fig, df, x, dates, hover_labels)
    _render_dim2(fig, df, x, dates, hover_labels)
    _render_dim3(fig, df, x, dates, hover_labels)
    _render_dim4(fig, df, x, dates, hover_labels)
    _render_dim5(fig, df, x, dates, dim5_mode, hover_labels)

    # ==========================================
    # 配置第三 Y 轴 (维一~四各一个)
    # ==========================================
    third_configs = {
        # dim1: Close (灰色, 左侧偏移)
        "yaxis11": _third_axis_config(1, COLORS["close_tick"], "x", "y"),
        # dim2: CYS34 (天蓝, 左侧偏移)
        "yaxis12": _third_axis_config(2, COLORS["cys34"], "x2", "y3"),
        # dim3: D_Pos (粉红, 左侧偏移)
        "yaxis13": _third_axis_config(3, COLORS["dpos"], "x3", "y5"),
        # dim4: ASR (青色, 左侧偏移)
        "yaxis14": _third_axis_config(4, COLORS["asr"], "x4", "y7"),
    }

    # ==========================================
    # 全局布局
    # ==========================================
    fig.update_layout(
        height=800,
        plot_bgcolor=PANEL_COLOR,
        paper_bgcolor=BG_COLOR,
        font=dict(family="PingFang SC, Microsoft YaHei, sans-serif", color=TEXT_COLOR),
        margin=dict(l=90, r=55, t=24, b=24),
        showlegend=False,
        hovermode="x",
        hoverlabel=dict(
            bgcolor="#1F2937",
            font_size=11,
            font_color=TEXT_COLOR,
            bordercolor=MUTE_COLOR,
        ),
        **third_configs,
    )

    # ── 统一右轴 = 资金 (红色刻度) ──
    for row in range(1, 5):
        fig.update_yaxes(row=row, col=1, secondary_y=True, **_fund_axis_style())

    # ── 左轴颜色 ──
    fig.update_yaxes(row=1, col=1, secondary_y=False, **_left_axis_style(COLORS["lfs"]))
    fig.update_yaxes(row=2, col=1, secondary_y=False, **_left_axis_style(COLORS["z_gold"]))
    fig.update_yaxes(row=3, col=1, secondary_y=False, **_left_axis_style(COLORS["ptr"]))
    fig.update_yaxes(row=4, col=1, secondary_y=False, **_left_axis_style(COLORS["y_overlap"]))

    # ── 维五双轴颜色 ──
    fig.update_yaxes(row=5, col=1, secondary_y=False, rangemode="tozero",
                     **_left_axis_style(COLORS["turnover_ma"]))
    fig.update_yaxes(row=5, col=1, secondary_y=True, rangemode="tozero",
                     **_left_axis_style(COLORS["ptr_ma"]))

    # X 轴
    tick_spacing = max(1, len(dates) // 12)
    fig.update_xaxes(
        row=5, col=1,
        tickvals=x[::tick_spacing],
        ticktext=[dates[i] for i in range(0, len(dates), tick_spacing)],
        tickfont=dict(size=9, color=MUTE_COLOR),
        gridcolor=GRID_COLOR,
    )
    for row in range(1, 5):
        fig.update_xaxes(row=row, col=1, showticklabels=False, gridcolor=GRID_COLOR)

    # ── 子图标题颜色 ──
    title_colors = [COLORS["lfs"], COLORS["z_gold"], COLORS["dpos"], COLORS["y_overlap"], "#FFD700"]
    for i, ann in enumerate(fig.layout.annotations):
        ann.font = dict(size=10, color=title_colors[i] if i < len(title_colors) else TEXT_COLOR)
        ann.x = 0.01
        ann.xanchor = "left"

    # ── 内嵌图例 (叠加在各子图左上角) ──
    # 使用各子图的 y domain 上边界定位
    y_domains = [fig.layout[f"yaxis{'' if r == 1 else (r * 2 - 1)}"].domain
                 for r in range(1, 6)]

    inline_legends = [
        # 维一
        (f'<span style="color:{COLORS["lfs"]}">━ LFS</span>  '
         f'<span style="color:{COLORS["hccyf13"]}">━ VMA</span>  '
         f'<span style="color:{COLORS["close_tick"]}">━ Close</span>  '
         f'<span style="color:{COLORS["fund"]}">▐ 资金132d</span>',
         y_domains[0]),
        # 维二
        (f'<span style="color:{COLORS["z_gold"]}">▌Z\'</span>  '
         f'<span style="color:{COLORS["cys34"]}">━ CYS34</span>  '
         f'<span style="color:{COLORS["fund"]}">▐ 资金66d</span>',
         y_domains[1]),
        # 维三
        (f'<span style="color:{COLORS["ptr"]}">━ PTR</span>  '
         f'<span style="color:{COLORS["dpos"]}">━ D_Pos</span>  '
         f'<span style="color:{COLORS["fund"]}">▐ 资金22d</span>',
         y_domains[2]),
        # 维四
        (f'<span style="color:{COLORS["y_overlap"]}">━ Y_Ovp</span>  '
         f'<span style="color:{COLORS["asr"]}">━ ASR</span>  '
         f'<span style="color:{COLORS["fund"]}">▐ 资金5d</span>',
         y_domains[3]),
        # 维五
        (f'<span style="color:{COLORS["turnover_ma"]}">━ T_MA</span>  '
         f'<span style="color:{COLORS["ptr_ma"]}">━ P_MA</span>',
         y_domains[4]),
    ]

    for text, domain in inline_legends:
        fig.add_annotation(
            text=text,
            xref="paper", yref="paper",
            x=0.06, y=domain[1] - 0.01,
            xanchor="left", yanchor="top",
            showarrow=False,
            font=dict(size=9),
            bgcolor="rgba(11,15,25,0.7)",
            borderpad=2,
        )

    return fig


# ==========================================
# 各维度渲染函数
# ==========================================

def _render_dim1(fig, df, x, dates, hover_labels):
    """维一：底座阵地 — LFS(蓝/左1), HCCYF13(黄/左1), Close(灰/左2), 资金(红/右)"""
    lfs = df["LFS"].to_list()
    hccyf13 = df["HCCYF13"].to_list()
    close = df["Close"].to_list()
    fund = df["Sum_132d"].to_list()

    # LFS 蓝线 → 左主轴
    fig.add_trace(go.Scatter(
        x=x, y=lfs, mode="lines", name="LFS(底座)",
        line=dict(color=COLORS["lfs"], width=2.5),
        hovertemplate="LFS: %{y:.2f}<extra></extra>",
    ), row=1, col=1, secondary_y=False)

    # HCCYF13 黄线 → 左主轴
    fig.add_trace(go.Scatter(
        x=x, y=hccyf13, mode="lines", name="HCCYF13",
        line=dict(color=COLORS["hccyf13"], width=1.2),
        hovertemplate="VMA: %{y:.2f}<extra></extra>",
    ), row=1, col=1, secondary_y=False)

    # Close 白线 → 第三轴 (左2, 灰色刻度)
    close_trace = go.Scatter(
        x=x, y=close, mode="lines", name="Close",
        line=dict(color=COLORS["close"], width=1),
        hovertemplate="Close: %{y:.2f}<extra></extra>",
    )
    fig.add_trace(close_trace, row=1, col=1, secondary_y=False)
    fig.data[-1].yaxis = "y11"

    # 绿色填充 (HCCYF13 < LFS)
    fill_y = [h if h < l else None for h, l in zip(hccyf13, lfs)]
    fig.add_trace(go.Scatter(
        x=x, y=fill_y, mode="lines",
        line=dict(width=0), fill="tonexty", fillcolor="rgba(16,185,129,0.12)",
        showlegend=False, hoverinfo="skip",
    ), row=1, col=1, secondary_y=False)

    # 资金面 → 右轴 (作为该维度的首部展示唯一的日期/天数 Header)
    _add_fund_area(fig, x, fund, row=1, alpha=0.25, label="半年132d", hover_labels=hover_labels)


def _render_dim2(fig, df, x, dates, hover_labels):
    """维二：抛压真空 — Z'(金/左1), CYS34(天蓝/左2), 资金(红/右)"""
    z_prime = df["Z_diff1"].to_list()
    cys34 = df["CYS34"].to_list()
    turnover = df["Turnover"].to_list()
    fund = df["Sum_66d"].to_list()

    # Z' 柱状图 → 左主轴
    bar_colors = []
    for z, t in zip(z_prime, turnover):
        if z > 10 and t < 5.0:
            bar_colors.append(COLORS["z_white"])
        elif z > 0:
            bar_colors.append(COLORS["z_gold"])
        else:
            bar_colors.append(COLORS["z_green"])

    fig.add_trace(go.Bar(
        x=x, y=z_prime, name="Z' 动能",
        marker=dict(color=bar_colors, opacity=0.9),
        width=0.6,
        hovertemplate="Z': %{y:.2f}<extra></extra>",
    ), row=2, col=1, secondary_y=False)

    fig.add_hline(y=10, line=dict(color=COLORS["z_gold"], width=1, dash="dash"),
                  opacity=0.6, row=2, col=1)

    # 资金面 → 右轴 (保留唯一日期 Header)
    _add_fund_area(fig, x, fund, row=2, alpha=0.18, label="季66d", hover_labels=hover_labels)

    # CYS34 → 第三轴 (左2, 天蓝刻度)
    fig.add_trace(go.Scatter(
        x=x, y=cys34, mode="lines", name="CYS34",
        line=dict(color=COLORS["cys34"], width=1.5),
        hovertemplate="CYS34: %{y:.2f}<extra></extra>",
    ), row=2, col=1, secondary_y=False)
    fig.data[-1].yaxis = "y12"


def _render_dim3(fig, df, x, dates, hover_labels):
    """维三：活筹点火 — PTR(橙/左1), D_Pos(粉/左2), 资金(红/右)"""
    ptr = df["PTR"].to_list()
    dpos = df["D_Pos"].to_list()
    fund = df["Sum_22d"].to_list()

    # PTR 橙线 → 左主轴
    fig.add_trace(go.Scatter(
        x=x, y=ptr, mode="lines", name="PTR(单日)",
        line=dict(color=COLORS["ptr"], width=1.5),
        hovertemplate="PTR: %{y:.2f}%<extra></extra>",
    ), row=3, col=1, secondary_y=False)

    # 资金面 → 右轴 (保留唯一日期 Header)
    _add_fund_area(fig, x, fund, row=3, alpha=0.12, label="月22d", hover_labels=hover_labels)

    # D_Pos → 第三轴 (左2, 粉色刻度)
    fig.add_trace(go.Scatter(
        x=x, y=dpos, mode="lines", name="D_Pos",
        line=dict(color=COLORS["dpos"], width=1.5),
        hovertemplate="D_Pos: %{y:.2f}<extra></extra>",
    ), row=3, col=1, secondary_y=False)
    fig.data[-1].yaxis = "y13"


def _render_dim4(fig, df, x, dates, hover_labels):
    """维四：情绪极值 — Y_Overlap(紫/左1), ASR(青/左2), 资金(红/右)"""
    y_ovp = df["Y_Overlap"].to_list()
    asr = df["ASR"].to_list()
    fund = df["Sum_5d"].to_list()

    # Y_Overlap 紫线 → 左主轴
    fig.add_trace(go.Scatter(
        x=x, y=y_ovp, mode="lines", name="Y_Overlap",
        line=dict(color=COLORS["y_overlap"], width=1.5),
        hovertemplate="Y_Ovp: %{y:.2f}<extra></extra>",
    ), row=4, col=1, secondary_y=False)

    fig.add_hline(y=60, line=dict(color=COLORS["y_overlap"], width=1, dash="dot"),
                  opacity=0.5, row=4, col=1)

    # 资金面 → 右轴 (保留唯一日期 Header)
    _add_fund_area(fig, x, fund, row=4, alpha=0.10, label="周5d", hover_labels=hover_labels)

    # ASR → 第三轴 (左2, 青色刻度)
    fig.add_trace(go.Scatter(
        x=x, y=asr, mode="lines", name="ASR",
        line=dict(color=COLORS["asr"], width=2),
        hovertemplate="ASR: %{y:.2f}<extra></extra>",
    ), row=4, col=1, secondary_y=False)
    fig.data[-1].yaxis = "y14"


def _render_dim5(fig, df, x, dates, mode: int, hover_labels):
    """维五：量筹剪刀差 — 左:Turnover_MA(蓝), 右:PTR_MA(红)"""
    cd = [[h] for h in hover_labels]

    if mode > 0:
        t_col = f"Turnover_MA{mode}"
        p_col = f"PTR_MA{mode}"
        t_vals = df[t_col].to_list()
        p_vals = df[p_col].to_list()

        # 仅第一条曲线带日期 Header
        fig.add_trace(go.Scatter(
            x=x, y=t_vals, mode="lines", name=f"T_MA{mode}(大众)",
            line=dict(color=COLORS["turnover_ma"], width=1.5),
            fill="tozeroy", fillcolor="rgba(37,99,235,0.2)",
            customdata=cd,
            hovertemplate=f"%{{customdata[0]}}<br>T_MA{mode}: %{{y:.2f}}<extra></extra>",
        ), row=5, col=1, secondary_y=False)

        fig.add_trace(go.Scatter(
            x=x, y=p_vals, mode="lines", name=f"P_MA{mode}(活筹)",
            line=dict(color=COLORS["ptr_ma"], width=1.5),
            hovertemplate=f"P_MA{mode}: %{{y:.2f}}<extra></extra>",
        ), row=5, col=1, secondary_y=True)
    else:
        t5 = df["Turnover_MA5"].to_list()
        t20 = df["Turnover_MA20"].to_list()
        p5 = df["PTR_MA5"].to_list()
        p20 = df["PTR_MA20"].to_list()

        # 仅 T_MA5 带日期 Header
        fig.add_trace(go.Scatter(
            x=x, y=t5, mode="lines", name="T_MA5(突击)",
            line=dict(color=COLORS["turnover_ma"], width=1),
            fill="tozeroy", fillcolor="rgba(37,99,235,0.1)",
            customdata=cd,
            hovertemplate="%{customdata[0]}<br>T_MA5: %{y:.2f}<extra></extra>",
        ), row=5, col=1, secondary_y=False)

        fig.add_trace(go.Scatter(
            x=x, y=t20, mode="lines", name="T_MA20(底牌)",
            line=dict(color="#60A5FA", width=2, dash="dash"),
            hovertemplate="T_MA20: %{y:.2f}<extra></extra>",
        ), row=5, col=1, secondary_y=False)

        fig.add_trace(go.Scatter(
            x=x, y=p5, mode="lines", name="P_MA5(突击)",
            line=dict(color=COLORS["ptr_ma"], width=1),
            hovertemplate="P_MA5: %{y:.2f}<extra></extra>",
        ), row=5, col=1, secondary_y=True)

        fig.add_trace(go.Scatter(
            x=x, y=p20, mode="lines", name="P_MA20(底牌)",
            line=dict(color="#F87171", width=2, dash="dash"),
            hovertemplate="P_MA20: %{y:.2f}<extra></extra>",
        ), row=5, col=1, secondary_y=True)


# ==========================================
# 辅助函数
# ==========================================

def _add_fund_area(fig, x: list, fund_vals: list, row: int, alpha: float, label: str = "资金", hover_labels: list = None):
    """在指定行的副 Y 轴 (右轴) 上添加资金面红绿面积图，单一 hover"""
    # 先 round 到 3 位小数，消除浮点器噪音
    fund_vals = [round(v, 3) for v in fund_vals]
    pos = [v if v >= 0 else 0 for v in fund_vals]
    neg = [v if v < 0 else 0 for v in fund_vals]

    a_fill = f"{alpha:.2f}"
    a_line = f"{min(alpha * 2, 0.6):.2f}"

    # 正值红色面积 (纯填充, 不参与 hover)
    fig.add_trace(go.Scatter(
        x=x, y=pos, mode="lines",
        line=dict(width=0.8, color=f"rgba(239,68,68,{a_line})"),
        fill="tozeroy",
        fillcolor=f"rgba(239,68,68,{a_fill})",
        showlegend=False, hoverinfo="skip",
    ), row=row, col=1, secondary_y=True)

    # 负值绿色面积 (纯填充, 不参与 hover)
    fig.add_trace(go.Scatter(
        x=x, y=neg, mode="lines",
        line=dict(width=0.8, color=f"rgba(16,185,129,{a_line})"),
        fill="tozeroy",
        fillcolor=f"rgba(16,185,129,{a_fill})",
        showlegend=False, hoverinfo="skip",
    ), row=row, col=1, secondary_y=True)

    # 唯一 hover trace: 显示实际值, 3位小数
    hover_kwargs = {}
    if hover_labels:
        hover_kwargs["customdata"] = [[h] for h in hover_labels]
        hover_kwargs["hovertemplate"] = f"%{{customdata[0]}}<br>{label}: %{{y:+.3f}}%<extra></extra>"
    else:
        hover_kwargs["hovertemplate"] = f"{label}: %{{y:+.3f}}%<extra></extra>"

    fig.add_trace(go.Scatter(
        x=x, y=fund_vals, mode="lines",
        line=dict(width=0, color="rgba(0,0,0,0)"),
        name=label,
        showlegend=False,
        **hover_kwargs,
    ), row=row, col=1, secondary_y=True)

    # 零轴参考线
    fig.add_hline(y=0, line=dict(color="rgba(255,255,255,0.15)", width=0.8),
                  row=row, col=1, secondary_y=True)



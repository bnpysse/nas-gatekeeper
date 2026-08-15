"""
天眼全息智导系统 V6.0 — HUD 面板组件

生成右侧 HUD 的全部 HTML 内容：
  - 天眼作战枢纽 (日期/价格)
  - 战术全息仪 (六维数据)
  - X光合力透视 (资金矩阵)
  - 战区定性裁决 (S/A/B/C)
"""


def _fmt(v, sign=False) -> str:
    """智能精度：最多3位小数，自动剥离末尾零"""
    try:
        s = f"{float(v):.3f}"
    except (TypeError, ValueError):
        return "N/A"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    if sign and float(v) > 0:
        s = "+" + s
    return s


def _color(v: float, pos_color: str = "#EF4444", neg_color: str = "#10B981") -> str:
    """正值红/负值绿 的颜色"""
    return pos_color if v >= 0 else neg_color


def render_header(day: dict) -> str:
    """天眼作战枢纽 — 日期/价格"""
    return f"""
    <div class="hud-card">
        <div class="hud-card-title">【天眼全维作战枢纽】</div>
        <div style="color:#FFD700; font-size:1.1rem; font-weight:700;">
            {day.get('Date_Full', '')}
        </div>
        <div style="color:#FFFFFF; font-size:1rem; margin-top:4px;">
            切片价: <span style="font-weight:700;">{_fmt(day.get('Close', 0))}</span>
        </div>
    </div>
    """


def render_hologram(day: dict, dim5_mode: int = 0) -> str:
    """战术全息仪 — 六维核心数据"""
    z_prime = day.get("Z_diff1", 0)
    turnover = day.get("Turnover", 0)
    z_color = "#FFFFFF" if (z_prime > 10 and turnover < 5) else "#FFD700"

    # 维五数据
    if dim5_mode == 0:
        dim5_html = f"""
        <div class="data-row">
            <span class="data-label" style="color:#6B7280;">[维五]</span>
            <span class="data-value" style="color:#3B82F6;">T5:{_fmt(day.get('Turnover_MA5',0))} T20:{_fmt(day.get('Turnover_MA20',0))}</span>
        </div>
        <div class="data-row">
            <span class="data-label"></span>
            <span class="data-value" style="color:#EF4444;">P5:{_fmt(day.get('PTR_MA5',0))} P20:{_fmt(day.get('PTR_MA20',0))}</span>
        </div>
        """
    else:
        dim5_html = f"""
        <div class="data-row">
            <span class="data-label" style="color:#6B7280;">[维五]</span>
            <span class="data-value" style="color:#3B82F6;">T_{dim5_mode}:{_fmt(day.get(f'Turnover_MA{dim5_mode}',0))}</span>
            <span class="data-value" style="color:#EF4444;">P_{dim5_mode}:{_fmt(day.get(f'PTR_MA{dim5_mode}',0))}</span>
        </div>
        """

    return f"""
    <div class="hud-card">
        <div class="hud-card-title">&gt;&gt; 战术全息仪 &lt;&lt;</div>
        <div class="data-row">
            <span class="data-label" style="color:#6B7280;">[资金]</span>
            <span class="data-value" style="color:#EF4444;">Main: {_fmt(day.get('Main_Pct',0))}%</span>
            <span class="data-value" style="color:#10B981;">Flow: {_fmt(day.get('Flow_5d',0))}</span>
        </div>
        <div class="data-row">
            <span class="data-label" style="color:#6B7280;">[维一]</span>
            <span class="data-value" style="color:#3B82F6;">LFS: {_fmt(day.get('LFS',0))}</span>
            <span class="data-value" style="color:#F59E0B;">VMA: {_fmt(day.get('HCCYF13',0))}</span>
        </div>
        <div class="data-row">
            <span class="data-label" style="color:#6B7280;">[维二]</span>
            <span class="data-value" style="color:{z_color};">Z': {_fmt(z_prime)}</span>
            <span class="data-value" style="color:#38BDF8;">CYS: {_fmt(day.get('CYS34',0))}</span>
        </div>
        <div class="data-row">
            <span class="data-label" style="color:#6B7280;">[维三]</span>
            <span class="data-value" style="color:#EC4899;">D_Pos: {_fmt(day.get('D_Pos',0))}</span>
            <span class="data-value" style="color:#F97316;">PTR: {_fmt(day.get('PTR',0))}%</span>
        </div>
        <div class="data-row">
            <span class="data-label" style="color:#6B7280;">[维四]</span>
            <span class="data-value" style="color:#A855F7;">Y_Ovp: {_fmt(day.get('Y_Overlap',0))}</span>
            <span class="data-value" style="color:#06B6D4;">ASR: {_fmt(day.get('ASR',0))}</span>
        </div>
        {dim5_html}
        <div style="border-top:1px dashed #374151; margin-top:6px; padding-top:6px;">
            <div class="data-row">
                <span class="data-label" style="color:#FFD700; font-weight:700;">[核心]</span>
                <span class="data-value" style="color:#F59E0B; font-weight:700;">Sci: {_fmt(day.get('Scissor',0))}</span>
                <span class="data-value" style="color:#F59E0B; font-weight:700;">3d: {_fmt(day.get('Slope_3d',0), sign=True)}</span>
            </div>
        </div>
    </div>
    """


def render_fund_matrix(day: dict) -> str:
    """X光合力透视 — 资金矩阵"""
    matrix_data = [
        ("当日", day.get("Main_Pct", 0), day.get("Sum_Pct", 0), day.get("Delta_Sum_1d", 0)),
        ("周线", day.get("Main_5d", 0), day.get("Sum_5d", 0), day.get("Delta_Sum_5d", 0)),
        ("月线", day.get("Main_22d", 0), day.get("Sum_22d", 0), day.get("Delta_Sum_22d", 0)),
        ("季线", day.get("Main_66d", 0), day.get("Sum_66d", 0), day.get("Delta_Sum_66d", 0)),
        ("半年", day.get("Main_132d", 0), day.get("Sum_132d", 0), day.get("Delta_Sum_132d", 0)),
    ]

    rows = ""
    for label, main, sum_v, delta in matrix_data:
        cm = _color(main)
        cs = _color(sum_v)
        arrow = "↑" if delta > 0 else "↓" if delta < 0 else "-"
        ca = "#EF4444" if delta > 0 else "#10B981" if delta < 0 else "#6B7280"
        rows += f"""
        <tr>
            <td style="color:#E5E7EB;">{label}</td>
            <td style="color:{cm};">{_fmt(main, sign=True)}%</td>
            <td style="color:{cs}; font-weight:600;">{_fmt(sum_v, sign=True)}%</td>
            <td style="color:{ca}; font-weight:600;">{arrow} {_fmt(abs(delta))}</td>
        </tr>
        """

    # 月线势能判读
    delta_22 = day.get("Delta_Sum_22d", 0)
    if delta_22 > 1.0:
        momentum = '<span style="color:#EF4444;">月线势能加速流入</span>'
    elif delta_22 < -1.0:
        momentum = '<span style="color:#10B981;">月线势能向下破位</span>'
    else:
        momentum = '<span style="color:#E5E7EB;">势能胶着，多空弱平衡</span>'

    return f"""
    <div class="hud-card">
        <div class="hud-card-title">&gt;&gt; X光合力透视 &lt;&lt;</div>
        <div class="fund-matrix">
            <table>
                <tr>
                    <th>周期</th><th>主力</th><th>合力</th><th>势能</th>
                </tr>
                {rows}
            </table>
        </div>
        <div style="margin-top:8px; padding:6px 10px; background-color:#374151; border-radius:6px; font-size:0.82rem;">
            <b>判读:</b> {momentum}
        </div>
    </div>
    """


def render_zone_verdict(scissor: float, slope_3d: float) -> str:
    """战区定性裁决"""
    from core.signals import SignalJudge
    verdict = SignalJudge.judge_zone(scissor, slope_3d)

    return f"""
    <div class="zone-bar" style="border-left-color:{verdict.color};">
        <div class="zone-label" style="color:{verdict.color};">{verdict.zone_label}</div>
        <div class="zone-command">{verdict.command}</div>
    </div>
    """

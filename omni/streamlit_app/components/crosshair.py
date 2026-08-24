"""
天眼全息智导系统 V6.0 — 全 JS 交互组件

将 Plotly 图表 + HUD 面板打包成一个 HTML 组件:
- 跨子图垂直准星线 (paper yref shape)
- 鼠标悬停实时更新右侧 HUD (纯 JS，零延迟)
- 每个子图悬停时显示该维度全部指标的 tooltip
"""
import json
import streamlit.components.v1 as components
import plotly.graph_objects as go
import polars as pl


def render_radar_with_hud(
    fig: go.Figure,
    df: pl.DataFrame,
    stock_name: str,
    dim5_mode: int,
    height: int = 800,
):
    """
    渲染完整的雷达+HUD组件。

    Args:
        fig: Plotly Figure
        df: 当前标的的完整切片数据
        stock_name: 标的名称
        dim5_mode: 维五均线模式 (0=多维共振)
        height: 图表高度
    """
    fig_json = fig.to_json()

    # 将 df 转为 JS 可消费的 JSON 数组
    # 只传 HUD 需要的列，减少数据量
    hud_cols = [
        "Date_Full", "Close", "Main_Pct", "Dare_Pct", "Flow_5d", "DeltaX",
        "LFS", "HCCYF13", "Z_diff1", "CYS34", "Turnover",
        "PTR", "D_Pos", "Y_Overlap", "ASR",
        "X70", "X90", "Z_Profit",
        "Scissor", "Slope_3d", "Sum_Pct", "Delta_Sum_1d",
        "Main_5d", "Sum_5d", "Delta_Sum_5d",
        "Main_22d", "Sum_22d", "Delta_Sum_22d",
        "Main_66d", "Sum_66d", "Delta_Sum_66d",
        "Main_132d", "Sum_132d", "Delta_Sum_132d",
        "Turnover_MA5", "Turnover_MA10", "Turnover_MA20",
        "PTR_MA5", "PTR_MA10", "PTR_MA20",
    ]
    # 过滤存在的列
    existing_cols = [c for c in hud_cols if c in df.columns]
    rows_data = df.select(existing_cols).to_dicts()
    rows_json = json.dumps(rows_data, ensure_ascii=False, default=str)

    total = len(rows_data)

    html = f"""
    <div id="omni-root" style="display:flex; gap:8px; height:{height}px; font-family:'PingFang SC','Microsoft YaHei',sans-serif;">
        <div id="radar-chart" style="flex:5; min-width:0;"></div>
        <div id="hud-panel" style="flex:1.2; overflow-y:auto; font-size:12px; color:#E5E7EB;">
            <div id="hud-header" class="hc"></div>
            <div id="hud-holo" class="hc"></div>
            <div id="hud-matrix" class="hc"></div>
            <div id="hud-zone" class="zb"></div>
            <div id="hud-tactical" class="hc" style="margin-top:4px; border-left:3px solid #FFD700;"></div>
            <div id="hud-glossary" class="hc" style="margin-top:4px;"></div>
        </div>
    </div>

    <style>
    #omni-root .hc {{ background:linear-gradient(135deg,#1F2937,#111827); border:1px solid #374151; border-radius:6px; padding:4px 8px; margin-bottom:3px; }}
    #omni-root .ht {{ color:#6B7280; font-size:9.5px; font-weight:700; text-transform:uppercase; letter-spacing:0.05em; margin-bottom:2px; padding-bottom:1px; border-bottom:1px dashed #374151; }}
    #omni-root .dr {{ display:flex; justify-content:space-between; padding:1px 0; font-size:11px; }}
    #omni-root .dl {{ color:#6B7280; font-weight:500; min-width:26px; }}
    #omni-root .holo-tb {{ width:100%; border-collapse:collapse; font-size:11px; table-layout:fixed; }}
    #omni-root .holo-tb td {{ padding:1.5px 1px; vertical-align:middle; overflow:hidden; white-space:nowrap; }}
    #omni-root .h-d {{ width:22px; color:#6B7280; font-weight:500; }}
    #omni-root .h-v1 {{ font-weight:600; font-variant-numeric:tabular-nums; text-align:left; }}
    #omni-root .h-v2 {{ font-weight:600; font-variant-numeric:tabular-nums; text-align:left; }}
    #omni-root .h-f {{ width:76px; font-size:9.5px; font-weight:600; font-variant-numeric:tabular-nums; text-align:right; }}
    #omni-root .fm table {{ width:100%; border-collapse:collapse; font-size:10px; }}
    #omni-root .fm th {{ color:#6B7280; font-weight:600; text-align:left; padding:1px 2px; border-bottom:1px solid #374151; }}
    #omni-root .fm td {{ padding:1px 2px; font-variant-numeric:tabular-nums; font-weight:500; }}
    #omni-root .zb {{ padding:4px 6px; border-radius:5px; background:#1F2937; border-left:3px solid #6B7280; margin-top:2px; }}
    #omni-root .zl {{ font-size:11px; font-weight:700; margin-bottom:1px; }}
    #omni-root .zc {{ font-size:9.5px; color:#D1D5DB; line-height:1.25; }}
    #omni-root .k-chip {{ display:inline-block; padding:1px 3px; margin:1px 1px; border-radius:3px; background:#374151; font-size:9px; color:#9CA3AF; }}
    </style>

    <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
    <script>
    (function() {{
        const figData = {fig_json};
        const allRows = {rows_json};
        const stockName = "{stock_name}";
        const dim5Mode = {dim5_mode};
        const total = {total};
        const chartDiv = document.getElementById('radar-chart');

        // --- 初始化准星线 shape ---
        if (!figData.layout.shapes) figData.layout.shapes = [];
        figData.layout.shapes.push({{
            type:'line', x0:0, x1:0, y0:0, y1:1,
            xref:'x', yref:'paper',
            line:{{ color:'#E5E7EB', width:1.2, dash:'dot' }},
            opacity:0, name:'crosshair'
        }});

        Plotly.newPlot(chartDiv, figData.data, figData.layout, {{
            displayModeBar: false, responsive: true
        }});

        // --- 悬停事件 ---
        chartDiv.on('plotly_hover', function(ev) {{
            if (!ev || !ev.points || !ev.points.length) return;
            const pt = ev.points[0];
            const idx = Math.round(pt.x);
            if (idx < 0 || idx >= total) return;

            // 1. 移动准星线
            const shapes = chartDiv.layout.shapes.map((s, i) => {{
                if (i === chartDiv.layout.shapes.length - 1) {{
                    return Object.assign({{}}, s, {{ x0:idx, x1:idx, opacity:0.8 }});
                }}
                return s;
            }});
            Plotly.relayout(chartDiv, {{ shapes }});

            // 2. 更新 HUD
            updateHUD(idx);
        }});

        chartDiv.on('plotly_unhover', function() {{
            const shapes = chartDiv.layout.shapes.map((s,i) => {{
                if (i === chartDiv.layout.shapes.length -1) return Object.assign({{}}, s, {{ opacity:0 }});
                return s;
            }});
            Plotly.relayout(chartDiv, {{ shapes }});
        }});

        // --- 初始 HUD ---
        updateHUD(total - 1);

        // --- HUD 原始真值与单位格式化函数 ---
        function fmt(v, sign, unit) {{
            if (v == null || v === '' || isNaN(v)) return '-';
            let num = Number(v);
            let s = (Math.abs(num) < 0.0001 && num !== 0) ? num.toString() : Number(num.toFixed(3)).toString();
            if (sign && num > 0) s = '+' + s;
            if (unit) s += unit;
            return s;
        }}
        function clr(v, pos, neg) {{ return v >= 0 ? (pos||'#EF4444') : (neg||'#10B981'); }}

        function updateHUD(idx) {{
            const d = allRows[idx];
            if (!d) return;

            const z = d.Z_diff1 || 0;
            const to = d.Turnover || 0;
            const zc = (z > 10 && to < 5) ? '#FFF' : '#FFD700';
            const sci = d.Scissor || 0;
            const s3d = d.Slope_3d || 0;
            const asr = Number(d.ASR || 0);
            const x70 = Number(d.X70 || 0);
            const x90 = Number(d.X90 || 0);
            const z_profit = Number(d.Z_Profit || 0);
            const y_ovp = Number(d.Y_Overlap || 0);
            const hccyf = Number(d.HCCYF13 || 0);
            const dt1 = Number(d.Delta_Sum_1d || 0);
            const eta = to > 0.05 ? (Math.abs(dt1) / to).toFixed(2) : '1.00';

            // 维五
            let d5h = '';
            if (dim5Mode === 0) {{
                d5h = `<tr><td class="h-d">[五]</td><td class="h-v1" style="color:#3B82F6">T5:${{fmt(d.Turnover_MA5)}}</td><td class="h-v2" style="color:#EF4444">P5:${{fmt(d.PTR_MA5, false, '%')}}</td><td class="h-f"></td></tr>
                <tr><td class="h-d"></td><td class="h-v1" style="color:#60A5FA">T20:${{fmt(d.Turnover_MA20)}}</td><td class="h-v2" style="color:#F87171">P20:${{fmt(d.PTR_MA20, false, '%')}}</td><td class="h-f"></td></tr>`;
            }} else {{
                const tk = 'Turnover_MA'+dim5Mode, pk = 'PTR_MA'+dim5Mode;
                d5h = `<tr><td class="h-d">[五]</td><td class="h-v1" style="color:#3B82F6">T${{dim5Mode}}:${{fmt(d[tk])}}</td><td class="h-v2" style="color:#EF4444">P${{dim5Mode}}:${{fmt(d[pk], false, '%')}}</td><td class="h-f"></td></tr>`;
            }}

            // Header
            document.getElementById('hud-header').innerHTML = `
                <div class="ht">枢纽 · ${{stockName}}</div>
                <div style="color:#FFD700;font-size:13px;font-weight:700">${{d.Date_Full||''}}</div>
                <div style="color:#FFF;font-size:12px">价: <b>${{Number(d.Close||0).toFixed(2)}}</b> <span style="font-size:10px;color:#9CA3AF;margin-left:4px">换手: ${{fmt(to, false, '%')}}</span></div>`;

            // Hologram - 全息仪指标严格垂直等宽对齐 (含[筹] X70/X90/Z获利比)
            document.getElementById('hud-holo').innerHTML = `
                <div class="ht">全息仪</div>
                <table class="holo-tb">
                    <tr><td class="h-d">[资]</td><td class="h-v1" style="color:#EF4444">M:${{fmt(d.Main_Pct, true, '%')}}</td><td class="h-v2" style="color:#10B981">F:${{fmt(d.Flow_5d, true)}}</td><td class="h-f" style="color:#F59E0B">D:${{fmt(d.Dare_Pct, true, '%')}}</td></tr>
                    <tr><td class="h-d">[一]</td><td class="h-v1" style="color:#3B82F6">L:${{fmt(d.LFS)}}</td><td class="h-v2" style="color:#F59E0B">V:${{fmt(d.HCCYF13)}}</td><td class="h-f" style="color:${{clr(d.Sum_132d||0)}}">132d:${{fmt(d.Sum_132d, true, '%')}}</td></tr>
                    <tr><td class="h-d">[二]</td><td class="h-v1" style="color:${{zc}}">Z':${{fmt(z, true)}}</td><td class="h-v2" style="color:#38BDF8">C:${{fmt(d.CYS34, true)}}</td><td class="h-f" style="color:${{clr(d.Sum_66d||0)}}">66d:${{fmt(d.Sum_66d, true, '%')}}</td></tr>
                    <tr><td class="h-d">[三]</td><td class="h-v1" style="color:#EC4899">D:${{fmt(d.D_Pos)}}</td><td class="h-v2" style="color:#F97316">P:${{fmt(d.PTR, false, '%')}}</td><td class="h-f" style="color:${{clr(d.Sum_22d||0)}}">22d:${{fmt(d.Sum_22d, true, '%')}}</td></tr>
                    <tr><td class="h-d">[四]</td><td class="h-v1" style="color:#A855F7">Y:${{fmt(d.Y_Overlap, false, '%')}}</td><td class="h-v2" style="color:#06B6D4">A:${{fmt(d.ASR)}}</td><td class="h-f" style="color:${{clr(d.Sum_5d||0)}}">5d:${{fmt(d.Sum_5d, true, '%')}}</td></tr>
                    <tr><td class="h-d" style="color:#38BDF8;font-weight:700">[筹]</td><td class="h-v1" style="color:#38BDF8">X70:${{fmt(d.X70, false, '%')}}</td><td class="h-v2" style="color:#60A5FA">X90:${{fmt(d.X90, false, '%')}}</td><td class="h-f" style="color:#FBBF24">Z:${{fmt(d.Z_Profit, false, '%')}}</td></tr>
                    ${{d5h}}
                </table>
                <div style="border-top:1px dashed #374151;margin-top:3px;padding-top:3px">
                    <table class="holo-tb">
                        <tr><td class="h-d" style="color:#FFD700;font-weight:700">[核]</td><td class="h-v1" style="color:#F59E0B;font-weight:700">S:${{fmt(sci, true)}}</td><td class="h-v2" style="color:#F59E0B;font-weight:700">3d:${{fmt(s3d, true)}}</td><td class="h-f"></td></tr>
                    </table>
                </div>`;

            // Matrix
            const mx = [
                ['日', d.Main_Pct, d.Sum_Pct, d.Delta_Sum_1d],
                ['周', d.Main_5d, d.Sum_5d, d.Delta_Sum_5d],
                ['月', d.Main_22d, d.Sum_22d, d.Delta_Sum_22d],
                ['季', d.Main_66d, d.Sum_66d, d.Delta_Sum_66d],
                ['半', d.Main_132d, d.Sum_132d, d.Delta_Sum_132d],
            ];
            let rh = '';
            for (const [lb,m,s,dt] of mx) {{
                const cm = clr(m), cs = clr(s);
                const ar = dt>0?'↑':dt<0?'↓':'-', ca = dt>0?'#EF4444':dt<0?'#10B981':'#6B7280';
                rh += `<tr><td style="color:#E5E7EB">${{lb}}</td><td style="color:${{cm}}">${{fmt(m, true, '%')}}</td><td style="color:${{cs}};font-weight:600">${{fmt(s, true, '%')}}</td><td style="color:${{ca}};font-weight:600">${{ar}}${{fmt(Math.abs(dt||0))}}</td></tr>`;
            }}
            const d22 = d.Delta_Sum_22d || 0;
            const mo = d22>1 ? '<span style="color:#EF4444">加速流入</span>' : d22<-1 ? '<span style="color:#10B981">下破</span>' : '<span style="color:#E5E7EB">胶着</span>';

            document.getElementById('hud-matrix').innerHTML = `
                <div class="ht">X光合力</div>
                <div class="fm"><table><tr><th></th><th>主力</th><th>合力</th><th>势</th></tr>${{rh}}</table></div>
                <div style="margin-top:2px;padding:2px 5px;background:#374151;border-radius:3px;font-size:10px"><b>月:</b> ${{mo}}</div>`;

            // Zone
            let zone, zcolor, cmd;
            if (sci > 20) {{
                zone='★ S档：绝对护城河 (满配主升)'; zcolor='#FFD700'; cmd='允许常规洗盘。防线极厚，绝不轻易交出底仓。';
            }} else if (sci > 0) {{
                if (s3d > 0) {{ zone='■ A档：常规博弈区 (点火上攻)'; zcolor='#10B981'; cmd='动能健康。盯紧流速，跌破零轴前坚定持有。'; }}
                else {{ zone='◆ B档：防线松动区 (滞涨预警)'; zcolor='#F59E0B'; cmd='动能衰减。内部筹码松动，随时准备右侧止盈。'; }}
            }} else {{
                zone='✖ C档：极寒死叉区 (无条件清算)'; zcolor='#EF4444'; cmd='防线崩塌，右侧杀跌风险极高！立刻清仓！';
            }}
            const zEl = document.getElementById('hud-zone');
            zEl.style.borderLeftColor = zcolor;
            zEl.innerHTML = `<div class="zl" style="color:${{zcolor}}">${{zone}}</div><div class="zc">${{cmd}}</div>`;

            // 参谋部量化战术舱 (Tactical Cabin)
            const isPincer = (hccyf >= 40 && asr < 15 && x70 < 10);
            const isVacuum = (x70 < 10 && y_ovp <= 35);
            let tTitle = isPincer ? '★ 黄金反向钳形 (真龙主升)' : isVacuum ? '◆ 哑铃型真空走廊' : '● 常规多空博弈';
            let tOrder = (isPincer || sci > 20) ? '【继续锁仓装死】' : (sci > 0 && s3d > 0) ? '【坚定持股待涨】' : '【防范冲高震荡】';
            let tColor = isPincer ? '#FFD700' : '#10B981';

            document.getElementById('hud-tactical').innerHTML = `
                <div class="ht" style="color:#FFD700">参谋部 · 量化战术舱</div>
                <div style="font-size:11.5px;font-weight:700;color:${{tColor}};margin-bottom:2px">${{tTitle}}</div>
                <div style="font-size:10px;color:#9CA3AF;line-height:1.45">
                    • 效率 η: <b style="color:#FFF">${{eta}}</b> (低耗推升)<br>
                    • ASR 活动筹码: <b style="color:${{asr<15?'#10B981':'#EF4444'}}">${{fmt(asr)}}</b> ${{asr<15?'(极度死锁)':'(浮筹泛滥)'}}<br>
                    • 筹码聚焦: X70=<b style="color:#38BDF8">${{fmt(x70, false, '%')}}</b> | X90=<b style="color:#60A5FA">${{fmt(x90, false, '%')}}</b><br>
                    • 空间获利: Z获利=<b style="color:#FBBF24">${{fmt(z_profit, false, '%')}}</b> | Y重合=<b style="color:#A855F7">${{fmt(y_ovp, false, '%')}}</b>
                </div>
                <div style="margin-top:3px;padding:2px 4px;background:#374151;border-radius:4px;font-size:11px;font-weight:700;color:#FBBF24">
                    ⚡ 裁决军令: ${{tOrder}}
                </div>`;

            // 指标图谱知识库快捷说明
            document.getElementById('hud-glossary').innerHTML = `
                <div class="ht">参谋部 · 指标图谱速查</div>
                <div style="font-size:9.5px;color:#9CA3AF;line-height:1.3">
                    <span class="k-chip">CYF 40~65 黄金主升</span>
                    <span class="k-chip">ASR&lt;15 浮筹死锁</span>
                    <span class="k-chip">X70&lt;10% 超级单峰</span>
                    <span class="k-chip">η&ge;0.85 顶级效率</span>
                </div>`;
        }}
    }})();
    </script>
    """

    components.html(html, height=height + 10, scrolling=False)

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
        "Date_Full", "Close", "Main_Pct", "Flow_5d",
        "LFS", "HCCYF13", "Z_diff1", "CYS34", "Turnover",
        "PTR", "D_Pos", "Y_Overlap", "ASR",
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
        </div>
    </div>

    <style>
    #omni-root .hc {{ background:linear-gradient(135deg,#1F2937,#111827); border:1px solid #374151; border-radius:8px; padding:7px 10px; margin-bottom:4px; }}
    #omni-root .ht {{ color:#6B7280; font-size:10px; font-weight:700; text-transform:uppercase; letter-spacing:0.06em; margin-bottom:3px; padding-bottom:2px; border-bottom:1px dashed #374151; }}
    #omni-root .dr {{ display:flex; justify-content:space-between; padding:1px 0; font-size:11.5px; }}
    #omni-root .dl {{ color:#6B7280; font-weight:500; min-width:28px; }}
    #omni-root .dv {{ font-weight:600; font-variant-numeric:tabular-nums; }}
    #omni-root .fm table {{ width:100%; border-collapse:collapse; font-size:10.5px; }}
    #omni-root .fm th {{ color:#6B7280; font-weight:600; text-align:left; padding:1px 3px; border-bottom:1px solid #374151; }}
    #omni-root .fm td {{ padding:2px 3px; font-variant-numeric:tabular-nums; font-weight:500; }}
    #omni-root .zb {{ padding:6px 8px; border-radius:6px; background:#1F2937; border-left:3px solid #6B7280; margin-top:3px; }}
    #omni-root .zl {{ font-size:12px; font-weight:700; margin-bottom:1px; }}
    #omni-root .zc {{ font-size:10.5px; color:#D1D5DB; line-height:1.3; }}
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

        // --- HUD 更新函数 ---
        function fmt(v, sign) {{
            if (v == null || isNaN(v)) return 'N/A';
            let s = Number(v).toFixed(1);
            if (sign && v > 0) s = '+' + s;
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

            // 维五
            let d5h = '';
            if (dim5Mode === 0) {{
                d5h = `<div class="dr"><span class="dl">[五]</span><span class="dv" style="color:#3B82F6">T5:${{fmt(d.Turnover_MA5)}}</span><span class="dv" style="color:#EF4444">P5:${{fmt(d.PTR_MA5)}}</span></div>
                <div class="dr"><span class="dl"></span><span class="dv" style="color:#60A5FA">T20:${{fmt(d.Turnover_MA20)}}</span><span class="dv" style="color:#F87171">P20:${{fmt(d.PTR_MA20)}}</span></div>`;
            }} else {{
                const tk = 'Turnover_MA'+dim5Mode, pk = 'PTR_MA'+dim5Mode;
                d5h = `<div class="dr"><span class="dl">[五]</span><span class="dv" style="color:#3B82F6">T${{dim5Mode}}:${{fmt(d[tk])}}</span><span class="dv" style="color:#EF4444">P${{dim5Mode}}:${{fmt(d[pk])}}</span></div>`;
            }}

            // Header
            document.getElementById('hud-header').innerHTML = `
                <div class="ht">枢纽 · ${{stockName}}</div>
                <div style="color:#FFD700;font-size:13px;font-weight:700">${{d.Date_Full||''}}</div>
                <div style="color:#FFF;font-size:12px">价: <b>${{Number(d.Close||0).toFixed(2)}}</b></div>`;

            // Hologram - 各维度核心指标 + 对应资金累计
            document.getElementById('hud-holo').innerHTML = `
                <div class="ht">全息仪</div>
                <div class="dr"><span class="dl">[资]</span><span class="dv" style="color:#EF4444">M:${{fmt(d.Main_Pct)}}%</span><span class="dv" style="color:#10B981">F:${{fmt(d.Flow_5d)}}</span></div>
                <div class="dr"><span class="dl">[一]</span><span class="dv" style="color:#3B82F6">L:${{fmt(d.LFS)}}</span><span class="dv" style="color:#F59E0B">V:${{fmt(d.HCCYF13)}}</span><span class="dv" style="color:${{clr(d.Sum_132d||0)}};font-size:10px">132d:${{fmt(d.Sum_132d,true)}}</span></div>
                <div class="dr"><span class="dl">[二]</span><span class="dv" style="color:${{zc}}">Z':${{fmt(z)}}</span><span class="dv" style="color:#38BDF8">C:${{fmt(d.CYS34)}}</span><span class="dv" style="color:${{clr(d.Sum_66d||0)}};font-size:10px">66d:${{fmt(d.Sum_66d,true)}}</span></div>
                <div class="dr"><span class="dl">[三]</span><span class="dv" style="color:#EC4899">D:${{fmt(d.D_Pos)}}</span><span class="dv" style="color:#F97316">P:${{fmt(d.PTR)}}%</span><span class="dv" style="color:${{clr(d.Sum_22d||0)}};font-size:10px">22d:${{fmt(d.Sum_22d,true)}}</span></div>
                <div class="dr"><span class="dl">[四]</span><span class="dv" style="color:#A855F7">Y:${{fmt(d.Y_Overlap)}}</span><span class="dv" style="color:#06B6D4">A:${{fmt(d.ASR)}}</span><span class="dv" style="color:${{clr(d.Sum_5d||0)}};font-size:10px">5d:${{fmt(d.Sum_5d,true)}}</span></div>
                ${{d5h}}
                <div style="border-top:1px dashed #374151;margin-top:3px;padding-top:3px">
                <div class="dr"><span class="dl" style="color:#FFD700;font-weight:700">[核]</span><span class="dv" style="color:#F59E0B;font-weight:700">S:${{fmt(sci)}}</span><span class="dv" style="color:#F59E0B;font-weight:700">3d:${{fmt(s3d,true)}}</span></div></div>`;

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
                rh += `<tr><td style="color:#E5E7EB">${{lb}}</td><td style="color:${{cm}}">${{fmt(m,true)}}%</td><td style="color:${{cs}};font-weight:600">${{fmt(s,true)}}%</td><td style="color:${{ca}};font-weight:600">${{ar}}${{fmt(Math.abs(dt||0))}}</td></tr>`;
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
        }}
    }})();
    </script>
    """

    components.html(html, height=height + 10, scrolling=False)

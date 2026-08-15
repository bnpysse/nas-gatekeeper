import sys
import os
import json
import numpy as np
import pandas as pd
import platform

# ==========================================
# 0. 引擎初始化
# ==========================================
import matplotlib

matplotlib.use('QtAgg')
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.gridspec as gridspec

from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                               QHBoxLayout, QLabel, QFrame, QScrollArea, QComboBox)
from PySide6.QtCore import Qt

# ==========================================
# 1. 战术暗黑渲染引擎 (字体安全配置)
# ==========================================
system = platform.system()
if system == 'Darwin':
    plt.rcParams['font.sans-serif'] = ['PingFang SC', 'Heiti TC']
elif system == 'Windows':
    plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei']
else:
    plt.rcParams['font.sans-serif'] = ['WenQuanYi Micro Hei']
plt.rcParams['axes.unicode_minus'] = False


def _fmt(v, sign=False):
    """智能精度：最多保留3位小数，自动剥离末尾零"""
    s = f"{v:.3f}"
    if '.' in s:
        s = s.rstrip('0').rstrip('.')
    if sign and v > 0:
        s = '+' + s
    return s


# ==========================================
# 2. V5.2 终极版：双轨制时空探测雷达 (V2.0 增量防御)
# ==========================================
class RadarV52_PySide6(QMainWindow):
    def __init__(self, df_full, targets_list):
        super().__init__()
        self.df_full = df_full
        self.targets = targets_list

        self.bg_color = '#111827'
        self.panel_color = '#1F2937'
        self.text_color = '#E5E7EB'
        self.mute_color = '#4B5563'
        self.legend_bg = '#111827'

        self.setWindowTitle("天眼全息智导系统 V5.2.4 (终极重载版)")
        self.resize(1680, 1000)

        self.cid_mouse = None
        self.vlines = []

        # [轨一]：全局截取视野 (Fibonacci 窗口)
        self.periods = [
            ("全部数据", 0),
            ("5日 (极短探测)", 5),
            ("13日 (Fib短)", 13),
            ("34日 (Fib中)", 34),
            ("55日 (Fib长)", 55),
            ("132日 (战略底座)", 132)
        ]

        # [轨二]：第五维度专属探测 (标准均线变频)
        self.turnover_periods = [
            ("5日 (短线游资)", 5),
            ("10日 (波段中枢)", 10),
            ("20日 (标准月线)", 20),
            ("多维共振 (5日+20日)", 0)
        ]

        self._setup_ui()
        self.combo_targets.setCurrentIndex(0)
        self.combo_period.setCurrentIndex(3)  # 默认34日
        self.combo_to_period.setCurrentIndex(2)  # 默认20日肉搏

    def _setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(12)

        self.sys_font = "PingFang SC" if system == 'Darwin' else "Microsoft YaHei"

        self.setStyleSheet(f"""
            QMainWindow {{ background-color: {self.bg_color}; }}
            QWidget {{ background-color: {self.bg_color}; font-family: '{self.sys_font}'; }}
            QScrollBar:vertical {{ background: transparent; width: 8px; }}
            QScrollBar::handle:vertical {{ background: #4B5563; border-radius: 4px; }}
            QComboBox {{ 
                background-color: #374151; color: #FFD700; border: 1px solid #4B5563; 
                border-radius: 6px; padding: 5px 15px; font-weight: bold; min-width: 160px;
            }}
            QComboBox::drop-down {{ border: none; }}
            QComboBox QAbstractItemView {{ background-color: #1F2937; color: #E5E7EB; selection-background-color: #4B5563; }}
        """)

        nav_bar = QFrame()
        nav_bar.setFixedHeight(55)
        nav_bar.setStyleSheet(
            f"QFrame {{ background-color: {self.panel_color}; border-radius: 8px; }} QLabel {{ font-size: 14px; font-weight: bold; color: #9CA3AF; }}")
        nav_layout = QHBoxLayout(nav_bar)
        nav_layout.setContentsMargins(20, 0, 20, 0)

        nav_layout.addWidget(QLabel("[ 战术目标 ]"))
        self.combo_targets = QComboBox()
        for t in self.targets: self.combo_targets.addItem(f"{t['name']} ({t['code']})", t['code'])
        self.combo_targets.currentIndexChanged.connect(self.render_current)
        nav_layout.addWidget(self.combo_targets)

        nav_layout.addSpacing(20)

        nav_layout.addWidget(QLabel("[ 时空窗口(Fib) ]"))
        self.combo_period = QComboBox()
        for name, _ in self.periods: self.combo_period.addItem(name)
        self.combo_period.currentIndexChanged.connect(self.render_current)
        nav_layout.addWidget(self.combo_period)

        nav_layout.addSpacing(20)

        nav_layout.addWidget(QLabel("[ 维五变频(MA) ]"))
        self.combo_to_period = QComboBox()
        for name, _ in self.turnover_periods: self.combo_to_period.addItem(name)
        self.combo_to_period.currentIndexChanged.connect(self.render_current)
        nav_layout.addWidget(self.combo_to_period)

        nav_layout.addStretch()
        self.lbl_status = QLabel("全景引擎V5.2.4：双轨防御体系在线")
        self.lbl_status.setStyleSheet("color: #F59E0B; font-size: 16px;")
        nav_layout.addWidget(self.lbl_status)
        nav_layout.addStretch()

        main_layout.addWidget(nav_bar)

        content_layout = QHBoxLayout()
        main_layout.addLayout(content_layout)

        self.fig = Figure(facecolor=self.bg_color)
        self.canvas = FigureCanvas(self.fig)
        self.canvas.setStyleSheet("background-color: transparent;")
        content_layout.addWidget(self.canvas, 1)

        self.right_panel = QScrollArea()
        self.right_panel.setWidgetResizable(True)
        self.right_panel.setFixedWidth(400)
        self.right_panel.setStyleSheet("QScrollArea { border: none; background-color: transparent; }")

        self.hud_container = QWidget()
        self.hud_layout = QVBoxLayout(self.hud_container)
        self.hud_layout.setContentsMargins(10, 0, 0, 0)
        self.hud_layout.setSpacing(10)
        self.right_panel.setWidget(self.hud_container)

        self.lbl_header = self._create_html_card()
        self.lbl_intent = self._create_html_card()
        self.lbl_params = self._create_html_card()
        self.lbl_matrix = self._create_html_card()
        self.lbl_decision = self._create_html_card()
        self.hud_layout.addStretch()

        content_layout.addWidget(self.right_panel, 0)

    def _create_html_card(self):
        frame = QFrame()
        frame.setStyleSheet("QFrame { background-color: #1F2937; border-radius: 8px; border: 1px solid #374151; }")
        vbox = QVBoxLayout(frame)
        vbox.setContentsMargins(15, 10, 15, 10)
        lbl = QLabel()
        lbl.setWordWrap(True)
        lbl.setTextFormat(Qt.RichText)
        lbl.setStyleSheet("border: none; background-color: transparent;")
        vbox.addWidget(lbl)
        self.hud_layout.addWidget(frame)
        return lbl

    def render_current(self):
        if self.cid_mouse is not None: self.fig.canvas.mpl_disconnect(self.cid_mouse)
        self.fig.clf()

        current_idx = self.combo_targets.currentIndex()
        if current_idx < 0: return
        target = self.targets[current_idx]
        self.stock_name = target['name']
        self.stock_code = str(target['code']).replace('.0', '').zfill(6)
        days = self.periods[self.combo_period.currentIndex()][1]

        code_col = 'Target_Code' if 'Target_Code' in self.df_full.columns else 'Code'

        safe_code_col = self.df_full[code_col].astype(str).str.replace('.0', '', regex=False).str.zfill(6)
        full_stock_data = self.df_full[safe_code_col == self.stock_code].copy()

        self.df = full_stock_data.tail(days).reset_index(drop=True) if days > 0 else full_stock_data.reset_index(
            drop=True)

        if self.df.empty: return

        self.gs = gridspec.GridSpec(5, 1, figure=self.fig, hspace=0.15)
        self.x_idx = np.arange(len(self.df))
        self.vlines = []
        self.t1_axes, self.t2_axes, self.t3_axes, self.t4_axes, self.t5_axes = [], [], [], [], []

        self.render_ax_base()
        self.render_ax_z()
        self.render_ax_dpos()
        self.render_ax_emo()
        self.render_ax_scissors()

        self.update_hud_native(len(self.df) - 1, None)
        self._setup_interactions()
        self.fig.subplots_adjust(left=0.08, right=0.92, top=0.96, bottom=0.05)
        self.canvas.draw_idle()

    def _hide_spines_and_x(self, ax, hide_x=True):
        ax.set_facecolor(self.panel_color)
        for spine in ax.spines.values():
            spine.set_color(self.mute_color);
            spine.set_linewidth(0.8)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['left'].set_visible(True)
        if hide_x: ax.tick_params(axis='x', which='both', bottom=False, labelbottom=False)

    def _add_crosshair(self, ax):
        vline = ax.axvline(x=0, color='#E5E7EB', linestyle=':', linewidth=1.5, alpha=0.0, zorder=99)
        self.vlines.append(vline)

    def _add_fund_area(self, ax, fund_series, alpha_val):
        ax_twin = ax.twinx()
        self._hide_spines_and_x(ax_twin, hide_x=True)
        ax_twin.spines['left'].set_visible(False)
        ax_twin.spines['right'].set_visible(True)
        ax_twin.spines['right'].set_color('#EF4444')
        ax_twin.fill_between(self.x_idx, 0, np.where(fund_series >= 0, fund_series, 0), color='#EF4444',
                             alpha=alpha_val)
        ax_twin.fill_between(self.x_idx, 0, np.where(fund_series < 0, fund_series, 0), color='#10B981', alpha=alpha_val)
        ax_twin.axhline(0, color='white', ls='-', lw=0.8, alpha=0.3)
        max_abs = max(abs(fund_series.max()), abs(fund_series.min()), 1)
        ax_twin.set_ylim(-max_abs * 1.1, max_abs * 1.1)
        ax_twin.tick_params(axis='y', colors='#EF4444', labelsize=8)
        return ax_twin

    def _render_legend(self, ax, ax_twin):
        lines_1, labels_1 = ax.get_legend_handles_labels()
        lines_2, labels_2 = ax_twin.get_legend_handles_labels()
        if lines_1 or lines_2:
            ax.legend(lines_1 + lines_2, labels_1 + labels_2, loc='upper left', frameon=True,
                      facecolor=self.legend_bg, edgecolor=self.mute_color, fontsize=8,
                      labelcolor=self.text_color, framealpha=0.6, borderpad=0.4, bbox_to_anchor=(0.01, 0.95))

    def render_ax_base(self):
        ax = self.fig.add_subplot(self.gs[0, 0])
        self._hide_spines_and_x(ax, hide_x=True)
        ax.plot(self.x_idx, self.df['HCCYF13'], color='#F59E0B', lw=1.2, label='HCCYF13')
        ax.plot(self.x_idx, self.df['LFS'], color='#3B82F6', lw=2.5, label='LFS(底座)')
        ax.fill_between(self.x_idx, self.df['HCCYF13'], self.df['LFS'], where=(self.df['HCCYF13'] < self.df['LFS']),
                        color='#10B981', alpha=0.15)
        ax.tick_params(axis='y', colors='#3B82F6', labelsize=8)

        ax_price = ax.twinx()
        self._hide_spines_and_x(ax_price, hide_x=True)
        ax_price.plot(self.x_idx, self.df['Close'], color='#FFFFFF', lw=1.2, alpha=0.5, label='Close')
        ax_price.yaxis.tick_left();
        ax_price.spines['left'].set_position(('outward', 45));
        ax_price.spines['left'].set_visible(True)
        ax_price.tick_params(axis='y', colors='#9CA3AF', labelsize=8)

        ax.set_title("维度一：底座阵地 (长短防线 | 资金背景: 半年线)", loc='left', color=self.text_color, pad=4,
                     fontsize=10)
        self._render_legend(ax, ax_price)

        ax_fund = self._add_fund_area(ax, self.df['Sum_132d'], 0.25)
        self._add_crosshair(ax)
        self.t1_axes = [ax, ax_price, ax_fund]

    def render_ax_z(self):
        ax = self.fig.add_subplot(self.gs[1, 0], sharex=self.t1_axes[0])
        self._hide_spines_and_x(ax, hide_x=True)
        z_prime, turnover = self.df['Z_diff1'].values, self.df['Turnover'].values
        colors = ['#FFFFFF' if (z > 10 and t < 5.0) else '#FFD700' if z > 0 else '#10B981' for z, t in
                  zip(z_prime, turnover)]
        ax.bar(self.x_idx, z_prime, color=colors, alpha=0.9, width=0.6, label="Z' 动能")
        ax.axhline(10, color='#FFD700', ls='--', lw=1.2, alpha=0.6)
        ax.tick_params(axis='y', colors='#FFD700', labelsize=8)

        ax_cys = ax.twinx()
        self._hide_spines_and_x(ax_cys, hide_x=True)
        ax_cys.plot(self.x_idx, self.df['CYS34'], color='#38BDF8', lw=1.5, label='CYS34')
        ax_cys.axhline(0, color='#38BDF8', ls=':', lw=1.0, alpha=0.5)
        ax_cys.yaxis.tick_left();
        ax_cys.spines['left'].set_position(('outward', 45));
        ax_cys.spines['left'].set_visible(True)
        ax_cys.tick_params(axis='y', colors='#38BDF8', labelsize=8)

        ax.set_title("维度二：抛压真空 (Z' 透视 | 资金背景: 季线)", loc='left', color=self.text_color, pad=4,
                     fontsize=10)
        self._render_legend(ax, ax_cys)

        ax_fund = self._add_fund_area(ax, self.df['Sum_66d'], 0.18)
        self._add_crosshair(ax)
        self.t2_axes = [ax, ax_cys, ax_fund]

    def render_ax_dpos(self):
        ax = self.fig.add_subplot(self.gs[2, 0], sharex=self.t1_axes[0])
        self._hide_spines_and_x(ax, hide_x=True)
        ax.plot(self.x_idx, self.df['PTR'], color='#F97316', lw=1.5, label='PTR(单日)')
        ax.tick_params(axis='y', colors='#F97316', labelsize=8)

        ax_dpos = ax.twinx()
        self._hide_spines_and_x(ax_dpos, hide_x=True)
        ax_dpos.plot(self.x_idx, self.df['D_Pos'], color='#EC4899', lw=1.5, label='D_Pos')
        ax_dpos.yaxis.tick_left();
        ax_dpos.spines['left'].set_position(('outward', 45));
        ax_dpos.spines['left'].set_visible(True)
        ax_dpos.tick_params(axis='y', colors='#EC4899', labelsize=8)

        ax.set_title("维度三：活筹点火 (单日流速 vs 锁仓 | 资金背景: 月线)", loc='left', color=self.text_color, pad=4,
                     fontsize=10)
        self._render_legend(ax, ax_dpos)

        ax_fund = self._add_fund_area(ax, self.df['Sum_22d'], 0.12)
        self._add_crosshair(ax)
        self.t3_axes = [ax, ax_dpos, ax_fund]

    def render_ax_emo(self):
        ax = self.fig.add_subplot(self.gs[3, 0], sharex=self.t1_axes[0])
        self._hide_spines_and_x(ax, hide_x=True)
        ax.plot(self.x_idx, self.df['Y_Overlap'], color='#A855F7', lw=1.5, label='Y_Overlap')
        ax.axhline(60, color='#A855F7', ls=':', lw=1.0, alpha=0.6)
        ax.tick_params(axis='y', colors='#A855F7', labelsize=8)

        ax_asr = ax.twinx()
        self._hide_spines_and_x(ax_asr, hide_x=True)
        ax_asr.plot(self.x_idx, self.df['ASR'], color='#06B6D4', lw=2.0, label='ASR')
        ax_asr.yaxis.tick_left();
        ax_asr.spines['left'].set_position(('outward', 45));
        ax_asr.spines['left'].set_visible(True)
        ax_asr.tick_params(axis='y', colors='#06B6D4', labelsize=8)

        ax.set_title("维度四：情绪极值 (活筹残量 | 资金背景: 周线)", loc='left', color=self.text_color, pad=4,
                     fontsize=10)
        self._render_legend(ax, ax_asr)

        ax_fund = self._add_fund_area(ax, self.df['Sum_5d'], 0.08)
        self._add_crosshair(ax)
        self.t4_axes = [ax, ax_asr, ax_fund]

    def render_ax_scissors(self):
        ax = self.fig.add_subplot(self.gs[4, 0], sharex=self.t1_axes[0])
        self._hide_spines_and_x(ax, hide_x=False)

        to_idx = self.combo_to_period.currentIndex()
        to_val = self.turnover_periods[to_idx][1]

        ax_ptr = ax.twinx()
        self._hide_spines_and_x(ax_ptr, hide_x=True)
        ax_ptr.spines['left'].set_visible(False)
        ax_ptr.spines['right'].set_visible(True)
        ax_ptr.spines['right'].set_color('#EF4444')
        ax_ptr.tick_params(axis='y', colors='#EF4444', labelsize=8)

        if to_val > 0:
            t_col, p_col = f'Turnover_MA{to_val}', f'PTR_MA{to_val}'
            ax.fill_between(self.x_idx, 0, self.df[t_col], color='#2563EB', alpha=0.3)
            ax.plot(self.x_idx, self.df[t_col], color='#3B82F6', lw=1.5, alpha=0.8, label=f'T_MA{to_val}(大众)')
            ax_ptr.plot(self.x_idx, self.df[p_col], color='#EF4444', lw=1.5, label=f'P_MA{to_val}(活筹)')
            title_suffix = f"单一频率: {to_val}日"
        else:
            ax.fill_between(self.x_idx, 0, self.df['Turnover_MA5'], color='#2563EB', alpha=0.15)
            ax.plot(self.x_idx, self.df['Turnover_MA5'], color='#3B82F6', lw=1.0, alpha=0.8, label='T_MA5(突击)')
            ax_ptr.plot(self.x_idx, self.df['PTR_MA5'], color='#EF4444', lw=1.0, label='P_MA5(突击)')
            ax.plot(self.x_idx, self.df['Turnover_MA20'], color='#60A5FA', lw=2.0, ls='--', alpha=0.9,
                    label='T_MA20(底牌)')
            ax_ptr.plot(self.x_idx, self.df['PTR_MA20'], color='#F87171', lw=2.0, ls='--', alpha=0.9,
                        label='P_MA20(底牌)')
            title_suffix = "多维共振 (5日 vs 20日)"

        ax.set_ylim(bottom=0)
        ax_ptr.set_ylim(bottom=0)

        ax.set_title(f"维度五：量筹剪刀差 [{title_suffix}]", loc='left', color='#FFD700', pad=4, fontsize=10,
                     fontweight='bold')
        self._render_legend(ax, ax_ptr)

        clean_dates = self.df['Date_Disp'].values
        tick_spacing = max(1, len(self.df) // 10)
        ax.set_xticks(self.x_idx[::tick_spacing])
        ax.set_xticklabels(clean_dates[::tick_spacing], rotation=0, ha='center', color=self.mute_color, fontsize=9)

        self._add_crosshair(ax)
        self.t5_axes = [ax, ax_ptr]

    # ==========================================
    # 模块 D：HUD 动态教范数据对接 (V5.2.5 灵魂注入与修复版)
    # ==========================================
    def update_hud_native(self, idx, hover_ax):
        try:
            day = self.df.iloc[idx]
        except IndexError:
            return

        to_idx = self.combo_to_period.currentIndex()
        to_val = self.turnover_periods[to_idx][1]

        # 提取全维核心数据
        scissor = day.get('Scissor', 0)
        vma_3d = day.get('Slope_3d', 0)
        z_prime = day.get('Z_diff1', 0)
        ptr = day.get('PTR', 0)
        cys34 = day.get('CYS34', 0)
        asr = day.get('ASR', 0)
        y_ovp = day.get('Y_Overlap', 0)
        main_pct = day.get('Main_Pct', 0)
        flow_5d = day.get('Flow_5d', 0)

        # 👇 动态维五：时空错位双轨解析
        if to_val == 0:  # [5+20 多维共振模式]
            dim5_html = f"""
            <tr>
                <td style="color:#9CA3AF; vertical-align:middle;">[维五]</td>
                <td><span style="color:#3B82F6; line-height:1.2;">T5: {_fmt(day.get('Turnover_MA5', 0))}<br>T20: {_fmt(day.get('Turnover_MA20', 0))}</span></td>
                <td><span style="color:#EF4444; line-height:1.2;">P5: {_fmt(day.get('PTR_MA5', 0))}<br>P20: {_fmt(day.get('PTR_MA20', 0))}</span></td>
            </tr>
            """
            dyn_t_slope = day.get('Turnover_MA5_slope', 0)
            dyn_p_slope = day.get('PTR_MA5_slope', 0)
        else:  # [单一周期模式]
            dim5_html = f"""
            <tr>
                <td style="color:#9CA3AF;">[维五]</td>
                <td><span style="color:#3B82F6;">T_{to_val}: {_fmt(day.get(f'Turnover_MA{to_val}', 0))}</span></td>
                <td><span style="color:#EF4444;">P_{to_val}: {_fmt(day.get(f'PTR_MA{to_val}', 0))}</span></td>
            </tr>
            """
            dyn_t_slope = day.get(f'Turnover_MA{to_val}_slope', 0)
            dyn_p_slope = day.get(f'PTR_MA{to_val}_slope', 0)

        # ==============================================================
        # 灵魂注入：全景教义解析窗 (已修复 HTML 截断 Bug，全面拓展战术逻辑)
        # ==============================================================
        ax1_list = [getattr(self, 'ax1', None), getattr(self, 'ax1_twin', None)] + getattr(self, 't1_axes', [])
        ax2_list = [getattr(self, 'ax2', None), getattr(self, 'ax2_twin', None)] + getattr(self, 't2_axes', [])
        ax3_list = [getattr(self, 'ax3', None), getattr(self, 'ax3_twin', None)] + getattr(self, 't3_axes', [])
        ax4_list = [getattr(self, 'ax4', None), getattr(self, 'ax4_twin', None)] + getattr(self, 't4_axes', [])
        ax5_list = [getattr(self, 'ax5', None), getattr(self, 'ax5_twin', None)] + getattr(self, 't5_axes', [])

        if hover_ax in ax1_list:
            if vma_3d > 2.0: tier_color = "#FFD700"; tier = "★ 点火级 (绝对主升)"
            elif vma_3d > 0: tier_color = "#10B981"; tier = "■ 滞涨级 (动能衰减)"
            elif vma_3d > -2.0: tier_color = "#F59E0B"; tier = "◆ 松动级 (筹码外泄)"
            else: tier_color = "#EF4444"; tier = "✖ 崩塌级 (恐慌抛售)"

            intent_title = "维度一：底座阵地与护城河"
            intent_color = "#3B82F6"
            intent_text = f"""
            <span style='color:#3B82F6;'>LFS(蓝线)</span>：长线压舱底座。<br>
            <span style='color:#F59E0B;'>VMA(黄线)</span>：短线突击锁定因子。<br>
            <b>[战术联动]</b>：剪刀差(黄线上穿蓝线)决定护城河的物理厚度。VMA_3d(三日斜率)决定短线资金的刺杀加速度。<br>
            <b>[红线纪律]</b>：剪刀差 S档(&gt;20) 允许常规洗盘；跌破零轴 C档(&lt;0) 意味着防线物理崩塌，无条件清仓！<br>
            <br><b>当前实时动能：<span style='color:{tier_color};'>{tier}</span></b>
            """

        elif hover_ax in ax2_list:
            intent_title = "维度二：空间与抛压真空"
            intent_color = "#FFD700"
            intent_text = """
            <span style='color:#FFD700;'>Z'动能柱</span>：获利盘打压动能的一阶导数。它代表向上打穿套牢盘的冲击力。<br>
            <span style='color:#38BDF8;'>CYS34(蓝线)</span>：34日市场盈亏，寻找跌幅情绪极值。<br>
            <b>[战术联动]</b>：<br>
            1. <b>真空爆破</b>：Z' &gt; 10 意味着上方抛压被瞬间打穿，进入无阻力区。<br>
            2. <b>极品无量</b>：若 Z' &gt; 10 且换手 &lt; 5%，定性为“极品无量穿透”，主力迎着抛压强制过峰！<br>
            3. <b>黄金深坑</b>：CYS34 &lt; -15，市场极度超跌，具备左侧伏击价值。
            """

        elif hover_ax in ax3_list:
            intent_title = "维度三：活筹点火与主力流速"
            intent_color = "#EC4899"
            intent_text = """
            <span style='color:#EC4899;'>D_Pos(粉线)</span>：长线机构压舱底仓。<br>
            <span style='color:#F97316;'>PTR(橙线)</span>：单日活筹流速。<br>
            <span style='color:#EF4444;'>Main%(红柱)</span>：真实主力资金占比。<br>
            <b>[战术联动]</b>：寻找 D_Pos 在低位潜伏，同时 PTR 突然放量飙升的启动拐点。如果底层 Main% 和 Flow 共振翻红，定性为【饱和攻击点火】。<br>
            <b>[高位警报]</b>：若 D_Pos &gt; 70 极高且 PTR 爆表，极大概率是游资高频对倒，掩护老庄撤退(击鼓传花)。
            """

        elif hover_ax in ax4_list:
            intent_title = "维度四：情绪极值与沉淀"
            intent_color = "#A855F7"
            intent_text = """
            <span style='color:#A855F7;'>Y_Ovp(紫线)</span>：筹码重合度，代表散户的纠缠与被套程度。<br>
            <span style='color:#06B6D4;'>ASR(青线)</span>：活动筹码残量。<br>
            <b>[战术联动]</b>：<br>
            1. <b>高效沉淀</b>：紫线上行 + 青线下移，浮筹正被物理锁死。<br>
            2. <b>流动性休克</b>：Y_Ovp &gt; 60 且 ASR &lt; 10。场内散户绝望装死，浮筹彻底耗尽，只需极少资金即可点火变盘！
            """

        elif hover_ax in ax5_list:
            intent_title = "维度五：量筹剪刀差"
            intent_color = "#F97316"
            p_label = "P5/20" if to_val == 0 else f"P{to_val}"
            t_label = "T5/20" if to_val == 0 else f"T{to_val}"
            intent_text = f"""
            <span style='color:#3B82F6;'>{t_label}(蓝线)</span>：表象换手率，全市场能看到的虚假繁荣。<br>
            <span style='color:#EF4444;'>{p_label}(红线)</span>：剔除死筹后的真实内驱热度。<br>
            <b>[战术联动 - 透视底牌]</b>：<br>
            1. <b>向下张口(锁仓)</b>：蓝线上升，但红线平缓或下降。主力在大口吞咽活筹转为死筹，极限锁仓主升浪！<br>
            2. <b>向上张口(诱多)</b>：蓝线缩量，但红线疯狂飙升。极少资金高频对倒，制造繁荣假象，隐蔽派发！
            """
        else:
            intent_title = "天眼全景巡航状态"
            intent_color = "#9CA3AF"
            intent_text = "准星切入左侧任意图层，雷达将自动为您调取该维度的底层计算逻辑、判读标准与战术联动教义。"

        # ==============================================================
        # UI 面板组装
        # ==============================================================
        self.lbl_header.setText(f"""
            <div style="color:#9CA3AF; font-size:12px; font-weight:bold; margin-bottom:2px;">【天眼全维作战枢纽】</div>
            <div style="color:#FFD700; font-size:14px; font-weight:bold;">{day.get('Date_Full', '')}</div>
            <div style="color:#FFFFFF; font-size:13px;">切片价: {_fmt(day.get('Close', 0))}</div>""")

        # 战术全息仪：保留最纯粹的数据
        z_color = '#FFFFFF' if (z_prime > 10 and day.get('Turnover', 0) < 5) else '#FFD700'
        self.lbl_params.setText(f"""
            <div style="color: #9CA3AF; font-size: 12px; font-weight: bold; margin-bottom: 4px;">>> 战术全息仪 <<</div>
            <table width="100%" cellpadding="2" cellspacing="0" style="font-size: 11px;">
                <tr>
                    <td style="color:#9CA3AF; width:22%;">[资金]</td>
                    <td><span style="color:#EF4444;">Main: {_fmt(main_pct)}%</span></td>
                    <td><span style="color:#10B981;">Flow: {_fmt(flow_5d)}</span></td>
                </tr>
                <tr>
                    <td style="color:#9CA3AF;">[维一]</td>
                    <td><span style="color:#3B82F6;">LFS: {_fmt(day.get('LFS', 0))}</span></td>
                    <td><span style="color:#F59E0B;">VMA: {_fmt(day.get('HCCYF13', 0))}</span></td>
                </tr>
                <tr>
                    <td style="color:#9CA3AF;">[维二]</td>
                    <td><span style="color:{z_color};">Z': {_fmt(z_prime)}</span></td>
                    <td><span style="color:#38BDF8;">CYS: {_fmt(cys34)}</span></td>
                </tr>
                <tr>
                    <td style="color:#9CA3AF;">[维三]</td>
                    <td><span style="color:#EC4899;">D_Pos:{_fmt(day.get('D_Pos', 0))}</span></td>
                    <td><span style="color:#F97316;">PTR: {_fmt(ptr)}%</span></td>
                </tr>
                <tr>
                    <td style="color:#9CA3AF;">[维四]</td>
                    <td><span style="color:#A855F7;">Y_Ovp:{_fmt(y_ovp)}</span></td>
                    <td><span style="color:#2DD4BF;">ASR: {_fmt(asr)}</span></td>
                </tr>
                {dim5_html}
                <tr><td colspan="3" style="border-top:1px dashed #4B5563; padding-top:4px;"></td></tr>
                <tr>
                    <td style="color:#FFD700; font-weight:bold;">[核心]</td>
                    <td><span style="color:#F59E0B; font-weight:bold;">Sci: {_fmt(scissor)}</span></td>
                    <td><span style="color:#F59E0B; font-weight:bold;">3d: {_fmt(vma_3d, sign=True)}</span></td>
                </tr>
            </table>""")

        # 战术合力透视阵列
        rows_html = ""
        matrix_data = [
            ("当日", day.get('Main_Pct', 0), day.get('Dare_Pct', 0), day.get('Sum_Pct', 0), day.get('Delta_Sum_1d', 0)),
            ("周线", day.get('Main_5d', 0), day.get('Dare_5d', 0), day.get('Sum_5d', 0), day.get('Delta_Sum_5d', 0)),
            ("月线", day.get('Main_22d', 0), day.get('Dare_22d', 0), day.get('Sum_22d', 0), day.get('Delta_Sum_22d', 0)),
            ("季线", day.get('Main_66d', 0), day.get('Dare_66d', 0), day.get('Sum_66d', 0), day.get('Delta_Sum_66d', 0)),
            ("半年", day.get('Main_132d', 0), day.get('Dare_132d', 0), day.get('Sum_132d', 0), day.get('Delta_Sum_132d', 0))
        ]
        month_delta = day.get('Delta_Sum_22d', 0)
        momentum_desc = "<span style='color:#E5E7EB;'>势能胶着，多空弱平衡</span>"
        if month_delta > 1.0: momentum_desc = "<span style='color:#EF4444;'>月线势能加速流入</span>"
        elif month_delta < -1.0: momentum_desc = "<span style='color:#10B981;'>月线势能向下破位</span>"

        for label, m, d, s, delta in matrix_data:
            cm = '#EF4444' if m > 0 else '#10B981'
            cs = '#EF4444' if s > 0 else '#10B981'
            arr = '↑' if delta > 0 else '↓' if delta < 0 else '-'
            c_arr = '#EF4444' if delta > 0 else '#10B981' if delta < 0 else '#9CA3AF'
            rows_html += f"""
            <tr>
                <td style="color:#E5E7EB;">{label}</td>
                <td style="color:{cm};">{_fmt(m, sign=True)}%</td>
                <td style="color:{cs}; font-weight:bold;">{_fmt(s, sign=True)}%</td>
                <td style="color:{c_arr}; font-weight:bold;">{arr} {_fmt(abs(delta))}</td>
            </tr>
            """
        self.lbl_matrix.setText(f"""
        <div style="color: #9CA3AF; font-size: 12px; font-weight: bold; margin-bottom: 4px;">>> X光合力透视 <<</div>
        <table width="100%" cellpadding="2" cellspacing="0" style="font-size: 11px; margin-bottom: 4px;">
            <tr><td style="color:#9CA3AF; border-bottom:1px solid #4B5563;">周期</td><td style="color:#9CA3AF; border-bottom:1px solid #4B5563;">主力</td><td style="color:#9CA3AF; border-bottom:1px solid #4B5563;">合力</td><td style="color:#9CA3AF; border-bottom:1px solid #4B5563;">势能</td></tr>
            {rows_html}
        </table>
        <div style="color: #D1D5DB; font-size: 11px; padding: 4px; background-color: #374151; border-radius: 4px;"><b>判读:</b> {momentum_desc}</div>
        """)

        # 🚀【核心设计：沉浸式教义浮动窗】🚀
        # 独立的内阴影深色卡片设计，让它像悬浮在面板上的“灵魂指导书”
        html_intent = f"""
        <div style="background-color: #111827; padding: 10px; border-radius: 6px; border: 1px solid {intent_color}; box-shadow: inset 0px 0px 8px rgba(0,0,0,0.5);">
            <div style="color: {intent_color}; font-size: 13px; font-weight: bold; border-bottom: 1px dashed #374151; padding-bottom: 4px; margin-bottom: 6px;">
                {intent_title}
            </div>
            <div style="color: #D1D5DB; font-size: 11.5px; line-height: 1.6; white-space: normal;">
                {intent_text}
            </div>
        </div>
        """
        self.lbl_intent.setText(html_intent)

        # 战区定性逻辑
        if scissor > 20: zone = "★ S档：绝对护城河 (满配主升)"; color = "#FFD700"; command = "战术裁决：允许常规洗盘。防线极厚，绝不轻易交出底仓。"
        elif scissor > 0:
            if vma_3d > 0: zone = "■ A档：常规博弈区 (点火上攻)"; color = "#10B981"; command = "战术裁决：动能健康。盯紧流速，跌破零轴前坚定持有。"
            else: zone = "◆ B档：防线松动区 (滞涨预警)"; color = "#F59E0B"; command = "战术裁决：动能衰减。内部筹码松动，随时准备右侧止盈。"
        else: zone = "✖ C档：极寒死叉区 (无条件清算)"; color = "#EF4444"; command = "战术裁决：防线崩塌，右侧杀跌风险极高！立刻清仓！"

        self.lbl_decision.setText(f"""
        <div style="background-color: #374151; padding: 8px; border-radius: 4px; border-left: 4px solid {color}; margin-top: 6px;">
            <div style="color: {color}; font-size: 13px; font-weight: bold; margin-bottom: 4px;">{zone}</div>
            <div style="color: #E5E7EB; font-size: 12px; line-height: 1.4; white-space: normal;">{command}</div>
        </div>
        """)

    def _setup_interactions(self):
        def on_mouse_move(event):
            if event.xdata is None: return
            idx = int(round(event.xdata))
            if 0 <= idx < len(self.df):
                for vline in self.vlines: vline.set_xdata([idx, idx]); vline.set_alpha(0.8)
                self.update_hud_native(idx, event.inaxes)
                self.canvas.draw_idle()

        self.cid_mouse = self.fig.canvas.mpl_connect('motion_notify_event', on_mouse_move)


# ==========================================
# 3. 启动序列 (底层数据引擎双轨分离)
# ==========================================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(script_dir, "data", "stock.csv")

    if not os.path.exists(file_path):
        print(f"致命错误：未找到数据底座 {file_path}")
        sys.exit(1)

    df_raw = pd.read_csv(file_path)

    # 强力清污脱敏
    for col in ['Main_Pct', 'Dare_Pct', 'ASR', 'CYS34', 'LFS', 'Turnover', 'PTR', 'D_Pos', 'Close', 'HCCYF13',
                'Y_Overlap']:
        if col in df_raw.columns:
            if df_raw[col].dtype == object:
                df_raw[col] = df_raw[col].astype(str).str.replace('%', '', regex=False).str.replace(',', '',
                                                                                                    regex=False)
            df_raw[col] = pd.to_numeric(df_raw[col], errors='coerce').fillna(0)

    code_col = 'Target_Code' if 'Target_Code' in df_raw.columns else 'Code'
    df_raw['Sum_Pct'] = df_raw['Main_Pct'] + df_raw['Dare_Pct']
    df_raw['Delta_Sum_1d'] = df_raw.groupby(code_col)['Sum_Pct'].diff(1).fillna(0)

    # [全局轨]：保留 Fibonacci 周期
    for p in [5, 13, 21, 34]:
        df_raw[f'PTR_MA{p}'] = df_raw.groupby(code_col)['PTR'].transform(lambda x: x.rolling(p, min_periods=1).mean())

    # [维五专属轨]：彻底分离的标准均线探测矩阵 (5日, 10日, 20日)
    for p in [5, 10, 20]:
        df_raw[f'Turnover_MA{p}'] = df_raw.groupby(code_col)['Turnover'].transform(
            lambda x: x.rolling(p, min_periods=1).mean())
        df_raw[f'Turnover_MA{p}_slope'] = df_raw.groupby(code_col)[f'Turnover_MA{p}'].diff(1).fillna(0)
        df_raw[f'PTR_MA{p}'] = df_raw.groupby(code_col)['PTR'].transform(lambda x: x.rolling(p, min_periods=1).mean())
        df_raw[f'PTR_MA{p}_slope'] = df_raw.groupby(code_col)[f'PTR_MA{p}'].diff(1).fillna(0)

    # 资金面背景底座运算
    for w in [5, 22, 66, 132]:
        df_raw[f'Main_{w}d'] = df_raw.groupby(code_col)['Main_Pct'].transform(
            lambda x: x.rolling(w, min_periods=1).sum())
        df_raw[f'Dare_{w}d'] = df_raw.groupby(code_col)['Dare_Pct'].transform(
            lambda x: x.rolling(w, min_periods=1).sum())
        df_raw[f'Sum_{w}d'] = df_raw.groupby(code_col)['Sum_Pct'].transform(lambda x: x.rolling(w, min_periods=1).sum())
        df_raw[f'Delta_Sum_{w}d'] = df_raw.groupby(code_col)[f'Sum_{w}d'].diff(1).fillna(0)

    # ==============================================================
    # 【核心新增】：计算四大维度的单日极值加速度(斜率)
    # ==============================================================
    df_raw['LFS_slope'] = df_raw.groupby(code_col)['LFS'].diff(1).fillna(0)
    df_raw['HCCYF13_slope'] = df_raw.groupby(code_col)['HCCYF13'].diff(1).fillna(0)
    df_raw['ASR_slope'] = df_raw.groupby(code_col)['ASR'].diff(1).fillna(0)
    df_raw['Y_Ovp_slope'] = df_raw.groupby(code_col)['Y_Overlap'].diff(1).fillna(0)
    df_raw['PTR_1d_slope'] = df_raw.groupby(code_col)['PTR'].diff(1).fillna(0)
    z_col = 'Z_Profit' if 'Z_Profit' in df_raw.columns else 'Z'
    df_raw['Z_diff1'] = df_raw.groupby(code_col)[z_col].diff(1).fillna(0)

    # ==============================================================
    # 【V2.0 双轨防线引擎新增算式】：物理厚度与动能加速度预处理
    # ==============================================================
    df_raw['Scissor'] = df_raw['HCCYF13'] - df_raw['LFS']
    df_raw['HCCYF13_shift3'] = df_raw.groupby(code_col)['HCCYF13'].shift(3).fillna(df_raw['HCCYF13'])
    df_raw['Slope_3d'] = df_raw['HCCYF13'] - df_raw['HCCYF13_shift3']

    # 👇👇👇 [参谋部补丁：植入 CYS13 战术休克模拟引擎] 👇👇👇
    if 'Close' in df_raw.columns:
        df_raw['MA13'] = df_raw.groupby(code_col)['Close'].transform(
            lambda x: x.rolling(window=13, min_periods=1).mean())
        df_raw['CYS13_Proxy'] = (df_raw['Close'] - df_raw['MA13']) / df_raw['MA13'] * 100
        df_raw.drop(columns=['MA13'], inplace=True)
    # 👆👆👆 ========================================== 👆👆👆

    df_raw['Date_parsed'] = pd.to_datetime(df_raw['Date'].astype(str), format='%Y%m%d', errors='coerce')
    df_raw['Date_Disp'] = df_raw['Date_parsed'].dt.strftime('%m-%d').fillna(df_raw['Date'].astype(str).str[-4:])
    df_raw['Date_Full'] = df_raw['Date_parsed'].dt.strftime('%Y-%m-%d').fillna(df_raw['Date'].astype(str))

    targets_list = []
    json_path = os.path.join(script_dir, "data", "battle_plan.json")
    if os.path.exists(json_path):
        with open(json_path, 'r', encoding='utf-8') as f:
            plan = json.load(f)
            for code_str, name_val in plan.get('stock_names', {}).items():
                targets_list.append({'code': code_str, 'name': name_val})

    if not targets_list:
        targets_list = [{'code': c, 'name': f"标的 {c}"} for c in df_raw[code_col].unique()]

    print("全景引擎启动。V5.2.4 终极重载版就绪！")
    window = RadarV52_PySide6(df_raw, targets_list)
    window.showMaximized()
    sys.exit(app.exec())

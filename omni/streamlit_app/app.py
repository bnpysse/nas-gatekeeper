"""
天眼全息智导系统 V6.0 — Streamlit 主入口

启动: uv run streamlit run streamlit_app/app.py
"""
import sys
from pathlib import Path

ROOT_DIR = str(Path(__file__).parent.parent)
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import streamlit as st

from core.engine import create_engine
from core.models import FIB_PERIODS, DIM5_MA_PERIODS
from streamlit_app.components.radar_chart import build_radar_figure
from streamlit_app.components.crosshair import render_radar_with_hud

# ==========================================
# 页面配置
# ==========================================
st.set_page_config(
    page_title="天眼全息智导系统 V6.0",
    page_icon="🛰️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
[data-testid="collapsedControl"] { display: none; }
.stApp { background-color: #0B0F19; color: #E5E7EB; }
header, #MainMenu, footer { display: none !important; }
.block-container { padding: 0.3rem 0.8rem 0 0.8rem !important; max-width: 100% !important; }

div[data-testid="stSelectbox"],
div[data-testid="stRadio"] { margin: 0 !important; padding: 0 !important; }
div[data-testid="stSelectbox"] label,
div[data-testid="stRadio"] label { display: none !important; }
div[data-testid="stRadio"] > div { flex-direction: row !important; gap: 4px !important; }
div[data-testid="stRadio"] > div > label { display: flex !important; padding: 1px 6px !important; font-size: 0.73rem !important; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 引擎
# ==========================================
@st.cache_resource
def load_engine():
    return create_engine(ROOT_DIR)

engine = load_engine()
targets = engine.get_targets()

# ==========================================
# 顶栏
# ==========================================
t1, t2, t3 = st.columns([2, 1.2, 4], gap="small")

with t1:
    tgt_opts = {f"{t.name} ({t.code})": t.code for t in targets}
    sel_label = st.selectbox("t", list(tgt_opts.keys()), 0, label_visibility="collapsed")
    sel_code = tgt_opts[sel_label]

with t2:
    fib_l = [n for n, _ in FIB_PERIODS]
    fib_v = [v for _, v in FIB_PERIODS]
    fi = st.selectbox("f", range(len(fib_l)), 3,
                      format_func=lambda i: fib_l[i], label_visibility="collapsed")
    sel_days = fib_v[fi]

with t3:
    d5l = [n for n, _ in DIM5_MA_PERIODS]
    d5v = [v for _, v in DIM5_MA_PERIODS]
    d5i = st.radio("d", range(len(d5l)), 3,
                   format_func=lambda i: d5l[i], horizontal=True, label_visibility="collapsed")
    sel_dim5 = d5v[d5i]

# ==========================================
# 数据
# ==========================================
df = engine.get_stock_data(sel_code, days=sel_days)
if df.is_empty():
    st.error(f"⚠️ 未找到 {sel_code}")
    st.stop()

stock_name = next((t.name for t in targets if t.code == sel_code), sel_code)

# ==========================================
# 全 JS 交互组件 (图表 + HUD 一体化，鼠标悬停实时联动)
# ==========================================
fig = build_radar_figure(df, stock_name, dim5_mode=sel_dim5)
render_radar_with_hud(fig, df, stock_name, dim5_mode=sel_dim5, height=800)

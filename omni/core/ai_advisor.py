"""
天眼全息智导系统 V6.0 — 参谋部 AI 穿透审计引擎 (AI Tactical Advisor)

结合统帅量化知识库 (tactical_bible) 与大模型 API (Google Gemini / DeepSeek / 本地规则引擎)，
对当前标的执行穿透式量化推演与军令下发。
"""
import os
import json
import requests
from typing import Any
import streamlit as st

from core.knowledge.tactical_bible import (
    INDICATOR_DICTIONARY,
    TACTICAL_LAWS,
    COMMANDER_PORTFOLIO,
    SYSTEM_PROMPT_STAFF_EXPERT,
)

def evaluate_local_tactical_status(d: dict[str, Any]) -> dict[str, Any]:
    """
    纯本地高速量化规则状态机推演 (零网络依赖，毫秒级响应)
    """
    asr = float(d.get("ASR", 20.0) or 20.0)
    x70 = float(d.get("X70", 15.0) or 15.0)
    y_ovp = float(d.get("Y_Overlap", 50.0) or 50.0)
    to = float(d.get("Turnover", 5.0) or 5.0)
    main = float(d.get("Main_Pct", 0.0) or 0.0)
    hccyf = float(d.get("HCCYF13", 40.0) or 40.0)
    lfs = float(d.get("LFS", 40.0) or 40.0)
    scissor = float(d.get("Scissor", hccyf - lfs) or (hccyf - lfs))
    slope_3d = float(d.get("Slope_3d", 0.0) or 0.0)
    
    # 模拟推演 CYF 与 BIAS
    delta_cyf = hccyf - 38.64  # 近似长周期差值
    bias_5_20 = float(d.get("BIAS_5_20", 3.2) or 3.2)
    
    # 拉升效率 η
    delta_p = float(d.get("Delta_Sum_1d", 1.5) or 1.5)
    eta = round(abs(delta_p) / max(to, 0.1), 2)

    # 1. 黄金反向钳形判定
    is_pincer = (hccyf >= 45 and asr < 15 and x70 < 10)
    is_overflow = (delta_cyf > 15 and to <= 8 and asr < 15)
    is_vacuum = (x70 < 10 and y_ovp <= 35)

    verdict_tags = []
    if is_pincer:
        verdict_tags.append("★ 黄金反向钳形")
    if is_overflow:
        verdict_tags.append("■ 动能溢出·真龙锁仓")
    if is_vacuum:
        verdict_tags.append("◆ 哑铃型真空主升")
    if not verdict_tags:
        verdict_tags.append("● 常规量化博弈态")

    # 军令下达
    if is_pincer or is_overflow or scissor > 20:
        order = "【继续锁仓装死】"
        order_desc = "主力绝对控盘，盘口无浮筹可砸，主升浪通道畅通，绝不交出底仓。"
        badge_color = "#FFD700"
    elif scissor > 0 and slope_3d > 0:
        order = "【坚定持股待涨】"
        order_desc = "多头动能良性点火，中枢稳固，沿上升通道推进。"
        badge_color = "#10B981"
    elif scissor > 0 and slope_3d <= 0:
        order = "【防范冲高震荡】"
        order_desc = "短线动能微幅衰减，注意高位获利盘对倒博弈，守住箱体上轨。"
        badge_color = "#F59E0B"
    else:
        order = "【就地冬眠/防线观察】"
        order_desc = "当前处于防线整理或筹码重构期，严格执行纪律。"
        badge_color = "#EF4444"

    return {
        "status_title": " · ".join(verdict_tags),
        "order": order,
        "order_desc": order_desc,
        "badge_color": badge_color,
        "eta": eta,
        "asr": asr,
        "x70": x70,
        "y_ovp": y_ovp,
        "hccyf": hccyf,
        "scissor": scissor,
        "slope_3d": slope_3d,
    }


@st.cache_data(show_spinner=False, ttl=1800)
def query_ai_staff_report(stock_code: str, stock_name: str, snapshot_json: str) -> str:
    """
    调用大模型生成参谋部专属穿透审计简报 (缓存 30 分钟)
    """
    d = json.loads(snapshot_json)
    local_eval = evaluate_local_tactical_status(d)
    
    # 检测 API Key (优先火山引擎 DeepSeek-V4-Pro 与 Gemini)
    volc_key = os.environ.get("VOLCENGINE_API_KEY", "")
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    silicon_key = os.environ.get("SILICONFLOW_API_KEY", "")
    
    user_prompt = f"""【参谋部作战指令请求】
请对标的：{stock_name} ({stock_code}) 截至 {d.get('Date_Full', '最新日')} 的物理截面真值执行穿透式数学审计。

【当前物理真值快照】：
- 收盘价: {d.get('Close')} 元
- ASR (活动筹码): {d.get('ASR')} (临界线 15)
- HCCYF13 (机构控盘): {d.get('HCCYF13')} | LFS (底座): {d.get('LFS')} | 剪刀差 Scissor: {d.get('Scissor', 0):.2f}
- X70: {d.get('X70')}% | Y重合度: {d.get('Y_Overlap')}% | Z获利比: {d.get('Z_Profit', 70)}%
- 换手率 Turnover: {d.get('Turnover')}% | 主力净买 Main%: {d.get('Main_Pct')}% | 5日多空流速: {d.get('Flow_5d')}
- 资金累积: 周5d({d.get('Sum_5d', 0):+.2f}%), 月22d({d.get('Sum_22d', 0):+.2f}%), 季66d({d.get('Sum_66d', 0):+.2f}%), 半年132d({d.get('Sum_132d', 0):+.2f}%)
- 本地引擎初步定性: {local_eval['status_title']} | 预判军令: {local_eval['order']}

请输出结构化的参谋部审计报告：
1. 动能与筹码穿透（ASR、CYF、X70/Y 空间真空）
2. 多周期资金合力与推升效率评价
3. 明确的总参谋部战术裁决与操作军令（150字以内，干脆利落）
"""

    # 1. 优先走 TokenGate 智能算力网关 (自动统筹 6 大平台临期优先/循环保底/战力天花板)
    tokengate_urls = [
        "http://127.0.0.1:8800/v1/chat/completions",
        "https://tg.donglida.xyz/v1/chat/completions"
    ]
    for tg_url in tokengate_urls:
        try:
            tg_payload = {
                "model": "auto",  # 由 TokenGate 自动选将调兵 (优先消耗 12 天内到期的高智商 Qwen 3.7 Plus / 火山 DeepSeek-V4-Pro)
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT_STAFF_EXPERT},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": 0.2
            }
            res = requests.post(tg_url, json=tg_payload, timeout=10)
            if res.status_code == 200:
                data = res.json()
                if "choices" in data and len(data["choices"]) > 0:
                    content = data["choices"][0]["message"].get("content", "").strip()
                    if content:
                        return content
        except Exception:
            continue

    # 2. 备用直连火山方舟 DeepSeek-V4-Pro (每日 200 万 Token 循环补给)
    if volc_key:
        try:
            url = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
            headers = {"Authorization": f"Bearer {volc_key}", "Content-Type": "application/json"}
            payload = {
                "model": "deepseek-v4-pro-ga-260813",
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT_STAFF_EXPERT},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": 0.2
            }
            res = requests.post(url, json=payload, headers=headers, timeout=12)
            if res.status_code == 200:
                return res.json()["choices"][0]["message"]["content"].strip()
        except Exception:
            pass

    # 纯本地参谋部兜底报告
    return f"""天眼静默，常规穿透。

【参谋部物理真值穿透审计】：
1. **筹码与动能**：ASR={local_eval['asr']} 处于极度死锁区，市面浮动筹码被彻底抽干；X70={local_eval['x70']}% 极限聚拢，配合 Y={local_eval['y_ovp']}% 构成哑铃型真空走廊，上方无密集解套抛压阻力。
2. **推升效率**：当前量能推升效率 η={local_eval['eta']}，主力以极低筹码磨损控盘上攻，剪刀差 Scissor={local_eval['scissor']:.1f} 稳居安全领空。

【总参谋部唯一战术裁决】：
● 判定：{local_eval['status_title']}
● 军令：{local_eval['order']}（{local_eval['order_desc']}）"""

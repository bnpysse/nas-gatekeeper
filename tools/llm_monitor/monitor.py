#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
各大平台免费模型与 Token/余额一键查询看板 (LLM Quota & Token Monitor)
"""

import sys
import json
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

# Import providers
from providers.google import check_google
from providers.deepseek import check_deepseek
from providers.siliconflow import check_siliconflow
from providers.dashscope import check_dashscope
from providers.n100_local import check_n100
from providers.volcengine import check_volcengine
from providers.modelscope import check_modelscope

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.text import Text
    from rich import box
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False


def fetch_all_data():
    tasks = [
        ("google", check_google),
        ("deepseek", check_deepseek),
        ("siliconflow", check_siliconflow),
        ("dashscope", check_dashscope),
        ("n100", check_n100),
        ("volcengine", check_volcengine),
        ("modelscope", check_modelscope),
    ]

    results = {}
    with ThreadPoolExecutor(max_workers=7) as executor:
        futures = {executor.submit(fn): name for name, fn in tasks}
        for future in futures:
            name = futures[future]
            try:
                results[name] = future.result()
            except Exception as e:
                results[name] = {
                    "provider": name,
                    "status": "探测异常",
                    "active": False,
                    "latency_ms": 0,
                    "balance_info": str(e),
                    "free_models": [],
                    "pricing_type": "未知"
                }
    return results


def render_rich_tui(data):
    console = Console()

    # Header Panel
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    header_text = Text()
    header_text.append("📊 多平台大模型免费配额与实时余额监控看板", style="bold cyan")
    header_text.append(f"\n刷新时间: {now_str} | 环境: MacOS Apple Silicon (Fish Shell)", style="dim")

    console.print(Panel(header_text, border_style="cyan", box=box.ROUNDED))

    # Table 1: Provider Status & Balance Summary
    t1 = Table(
        title="🌐 一、 平台状态与实时余额总览",
        box=box.ROUNDED,
        header_style="bold magenta",
        title_style="bold yellow",
        show_lines=True,
        expand=True
    )
    t1.add_column("服务商 (Provider)", style="bold white", ratio=2)
    t1.add_column("连通状态", justify="center", ratio=2)
    t1.add_column("计费模式", justify="center", ratio=2)
    t1.add_column("实时余额 / 免费配额", style="green", ratio=4)

    for key, p in data.items():
        # Status styling
        if "在线" in p.get("status", "") or "就绪" in p.get("status", ""):
            status_text = Text(f"🟢 {p['status']} ({p.get('latency_ms', 0)}ms)", style="bold green")
        elif "拥堵" in p.get("status", ""):
            status_text = Text(f"🟡 {p['status']}", style="bold yellow")
        else:
            status_text = Text(f"🔴 {p['status']}", style="bold red")

        # Pricing type styling
        ptype = p.get("pricing_type", "-")
        if "免费" in ptype or "无限" in ptype:
            ptype_text = Text(ptype, style="bold cyan")
        else:
            ptype_text = Text(ptype, style="dim white")

        t1.add_row(
            p.get("provider", key),
            status_text,
            ptype_text,
            p.get("balance_info", "-")
        )

    console.print(t1)
    console.print()

    # Table 2: Free & High-Value Models Matrix
    t2 = Table(
        title="🎁 二、 重点可用与【0元完全免费】大模型精选对照表",
        box=box.ROUNDED,
        header_style="bold blue",
        title_style="bold yellow",
        show_lines=True,
        expand=True
    )
    t2.add_column("平台", style="bold white", ratio=2)
    t2.add_column("模型名称 (Model Identifier)", style="bold cyan", ratio=4)
    t2.add_column("免费属性", justify="center", ratio=2)
    t2.add_column("上下文", justify="center", ratio=1)
    t2.add_column("定位与计费特性 (Features & Rates)", ratio=4)

    for key, p in data.items():
        p_name = p.get("provider", key).split("(")[0].strip()
        models = p.get("free_models", [])
        if not models:
            continue

        for m in models:
            is_free = m.get("is_free", False)
            if is_free:
                badge = Text("✅ 0元/免费", style="bold green on black")
            elif "按量" in m.get("tier", "") or "¥" in m.get("tier", ""):
                badge = Text("💰 按量扣费", style="yellow")
            else:
                badge = Text("⭐ 官方高阶", style="magenta")

            t2.add_row(
                p_name,
                m.get("name", "-"),
                badge,
                m.get("context_window", "-"),
                m.get("tier", "-")
            )

    console.print(t2)
    console.print()

    # Footer Tips
    footer = Text()
    footer.append("💡 极客调用贴士：\n", style="bold yellow")
    footer.append("• 终端快速体验：在 Fish 终端中输入 ", style="dim")
    footer.append("pi", style="bold cyan")
    footer.append("，敲 ", style="dim")
    footer.append("/model", style="bold green")
    footer.append(" 可直接在上述 Google 免费、DeepSeek R1 与 SiliconFlow 0元模型间秒切。\n", style="dim")
    footer.append("• Neovim 零消耗续航：在 NvChad 中使用 ", style="dim")
    footer.append("<Space>ag", style="bold magenta")
    footer.append(" 直连 Antigravity 官方订阅通道，零消耗 API Key 额度。\n", style="dim")
    footer.append("• 本看板全局调用指令：在任何目录随时输入 ", style="dim")
    footer.append("llm-quota", style="bold yellow")
    footer.append(" 即可即时刷新查看。", style="dim")

    console.print(Panel(footer, border_style="dim", box=box.ROUNDED))


def render_plain_text(data):
    print("=== 多平台大模型免费配额与实时余额监控看板 ===")
    for key, p in data.items():
        print(f"\n[{p.get('provider', key)}]")
        print(f"  状态: {p.get('status')} ({p.get('latency_ms', 0)}ms)")
        print(f"  模式: {p.get('pricing_type')}")
        print(f"  余额: {p.get('balance_info')}")
        for m in p.get("free_models", []):
            tag = "[0元免费]" if m.get("is_free") else "[按量/付费]"
            print(f"    - {tag} {m.get('name')} (上下文: {m.get('context_window')}) -> {m.get('tier')}")


def main():
    parser = argparse.ArgumentParser(description="各大平台免费模型与 Token/余额一键查询看板")
    parser.add_argument("--json", action="store_true", help="输出原始 JSON 格式数据")
    parser.add_argument("--check-only", action="store_true", help="只输出健康检查概览")
    args = parser.parse_args()

    data = fetch_all_data()

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return

    if args.check_only:
        for k, v in data.items():
            print(f"{v.get('provider')}: {v.get('status')} - {v.get('balance_info')}")
        return

    if RICH_AVAILABLE:
        render_rich_tui(data)
    else:
        render_plain_text(data)


if __name__ == "__main__":
    main()

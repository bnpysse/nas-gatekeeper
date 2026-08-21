#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TokenGate 终端命令行看板 (CLI Monitor)
运行方式:
  python -m tokengate.cli
  python -m tokengate.cli --recommend --task coding
"""

import sys
import asyncio
import argparse
from pathlib import Path

# 确保导入路径
parent_dir = str(Path(__file__).resolve().parent.parent)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from tokengate.core.detector import detector
from tokengate.core.router import router as smart_router
from tokengate.core.models import TaskType, StrategyType

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.text import Text
    from rich import box
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False


async def async_main():
    parser = argparse.ArgumentParser(description="TokenGate CLI - 全网免费大模型算力门禁与智能调度网关")
    parser.add_argument("--refresh", action="store_true", help="强制刷新全网探测")
    parser.add_argument("--json", action="store_true", help="以 JSON 格式输出全量数据")
    parser.add_argument("--recommend", action="store_true", help="输出当前最佳模型推荐")
    parser.add_argument("--task", default="general", choices=["general", "coding", "reasoning", "summary", "vision", "embedding", "rerank"], help="任务类型")
    parser.add_argument("--strategy", default="expiring_first", choices=["expiring_first", "daily_first", "max_capability", "fastest"], help="调度策略")

    args = parser.parse_args()

    summary = await detector.detect_all(force_refresh=args.refresh)

    if args.json:
        print(summary.model_dump_json(indent=2))
        return

    if args.recommend:
        rec = await smart_router.recommend(task=TaskType(args.task), strategy=StrategyType(args.strategy))
        if RICH_AVAILABLE:
            console = Console()
            panel = Panel(
                f"[bold green]推荐模型:[/bold green] {rec.recommended_model.name} ([cyan]{rec.recommended_model.id}[/cyan])\n"
                f"[bold yellow]所属平台:[/bold yellow] {rec.recommended_model.provider}\n"
                f"[bold blue]推荐理由:[/bold blue] {rec.reason}",
                title="🎯 TokenGate 智能调度推荐",
                border_style="green"
            )
            console.print(panel)
        else:
            print(f"推荐模型: {rec.recommended_model.name} ({rec.recommended_model.id})")
            print(f"理由: {rec.reason}")
        return

    if not RICH_AVAILABLE:
        print("=== TokenGate 算力看板 ===")
        for p in summary.providers.values():
            print(f"\n[{p.provider_name}] - {p.status} ({p.latency_ms}ms)")
            print(f"  说明: {p.balance_info}")
            for m in p.models:
                expire = f"(剩 {m.days_left} 天)" if m.days_left is not None else "(循环/常驻)"
                print(f"  - {m.name} | {m.id} {expire}")
        return

    console = Console()

    # 顶部统计面板
    header_text = Text()
    header_text.append("🚪 TokenGate ", style="bold white on #059669")
    header_text.append(" 全网免费大模型算力门禁与智能调度看板\n", style="bold white")
    header_text.append(f"⏱️ 更新时间: {summary.updated_at}  |  ", style="dim")
    header_text.append(f"🟢 在线平台: {summary.active_providers}/{summary.total_providers}  |  ", style="green")
    header_text.append(f"🔥 临期预警: {summary.urgent_expiring_models} 个  |  ", style="bold red" if summary.urgent_expiring_models > 0 else "dim")
    header_text.append(f"🔄 每日补给: {summary.daily_replenish_tokens}", style="cyan")

    console.print(Panel(header_text, border_style="cyan", box=box.ROUNDED))

    # 平台与模型表格
    table = Table(box=box.ROUNDED, border_style="bright_black", show_header=True, header_style="bold cyan")
    table.add_column("平台 / 提供商", style="white", width=22)
    table.add_column("模型名称 / ID", style="bright_white", width=34)
    table.add_column("上下文", justify="center", style="dim", width=8)
    table.add_column("到期倒计时", justify="center", width=14)
    table.add_column("剩余额度", justify="right", width=12)
    table.add_column("战术定位与特性", style="dim", width=32)

    for p in summary.providers.values():
        status_color = "green" if p.active else "red"
        p_label = f"[{status_color}]●[/{status_color}] {p.provider_name}\n[dim]{p.masked_key}[/dim]"

        for i, m in enumerate(p.models):
            # 到期状态着色
            if m.days_left is not None:
                if m.days_left <= 15:
                    exp_str = f"[bold red blink]剩 {m.days_left} 天[/bold red blink]"
                elif m.days_left <= 45:
                    exp_str = f"[yellow]剩 {m.days_left} 天[/yellow]"
                else:
                    exp_str = f"[green]剩 {m.days_left} 天[/green]"
            else:
                exp_str = "[cyan]每日循环/0元[/cyan]"

            # 剩余比例
            ratio_pct = int(m.remaining_ratio * 100)
            ratio_color = "red" if ratio_pct <= 20 else ("yellow" if ratio_pct <= 50 else "green")
            ratio_str = f"[{ratio_color}]{ratio_pct}%[/{ratio_color}]"

            m_name_str = f"[bold]{m.name}[/bold]\n[dim cyan]{m.id}[/dim cyan]"

            table.add_row(
                p_label if i == 0 else "",
                m_name_str,
                m.context_window,
                exp_str,
                ratio_str,
                m.tier_desc
            )
        table.add_section()

    console.print(table)


def main():
    asyncio.run(async_main())


if __name__ == "__main__":
    main()

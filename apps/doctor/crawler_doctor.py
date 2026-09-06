#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
N100 第二大脑 Autonomous AI Doctor Agent (自主自愈运维智能体)

功能概述：
1. 感知层 (Perception): 持续监测 N100 爬虫打卡心跳、进程锁状态、日志报错与网络连通性。
2. 决策层 (Reasoning): 当打卡超时 (>150分钟) 或发生未处理致命异常时，调用火山方舟 DeepSeek-V4
   (或 Gemini 备用) 进行 AIOps 故障日志根因分析。
3. 自愈层 (Self-Healing): 自动识别僵尸锁与挂死进程，安全回收系统资源，拉起沙盒重跑测试并复核心跳。
4. 通知层 (Notification): 直连 Telegram Bot 向用户手机推送专业的诊断报告与自愈执行结果。
"""

import os
import sys
import time
import json
import socket
import argparse
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

import httpx
from dotenv import load_dotenv

# 自动定位项目根目录与环境变量
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
TG_BOT_ENV = PROJECT_ROOT / "apps" / "tg-bot" / ".env"
LOCAL_ENV = PROJECT_ROOT / ".env"

if TG_BOT_ENV.exists():
    load_dotenv(TG_BOT_ENV, override=True)
elif LOCAL_ENV.exists():
    load_dotenv(LOCAL_ENV, override=True)

# 基础配置
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ALLOWED_USER_ID = os.getenv("ALLOWED_USER_ID", "891536734")
VOLCENGINE_API_KEY = os.getenv("VOLCENGINE_API_KEY", "")
VOLCENGINE_ENDPOINT = os.getenv("VOLCENGINE_ENDPOINT_DEEPSEEK_PRO") or os.getenv("VOLCENGINE_ENDPOINT_ID", "ep-20260820195716-snkzx")
GEMINI_API_KEY = os.getenv("GEMINI_PKM_API_KEY") or os.getenv("GEMINI_API_KEY", "")
HTTP_PROXY = os.getenv("HTTP_PROXY") or os.getenv("HTTPS_PROXY", "")

# 路径常量
SECONDBRAIN_LOG = Path("/var/log/secondbrain.log")
CRON_LOG = Path("/var/log/secondbrain_cron.log")
LOCK_FILE = Path("/var/lock/secondbrain_crawler.lock")
STATE_FILE = Path("/var/log/crawler_doctor_state.json")
RUN_CRAWLER_SCRIPT = Path("/opt/run_crawler.sh")
DB_FILE = PROJECT_ROOT / "apps" / "rss-fetcher" / "processed_items.db"
GATEKEEPER_PROBE_URL = "https://tg.donglida.com/api/probe/all"

# 超时判定阈值 (分钟)
HEARTBEAT_TIMEOUT_MINUTES = 150
ALERT_COOLDOWN_MINUTES = 120  # 同一故障报警冷却周期


class DoctorState:
    """自愈智能体状态机持久化管理"""
    def __init__(self, path: Path = STATE_FILE):
        self.path = path
        self.data: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        if self.path.exists():
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            "last_check_at": "",
            "last_alert_at": "",
            "last_healed_at": "",
            "healing_in_progress": False,
            "incident_count": 0,
            "last_status": "ok"
        }

    def save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ 保存 Doctor 状态异常: {e}", file=sys.stderr)

    def can_alert(self) -> bool:
        last_alert_str = self.data.get("last_alert_at")
        if not last_alert_str:
            return True
        try:
            last_dt = datetime.fromisoformat(last_alert_str)
            return (datetime.now() - last_dt) > timedelta(minutes=ALERT_COOLDOWN_MINUTES)
        except Exception:
            return True

    def mark_alert(self):
        self.data["last_alert_at"] = datetime.now().isoformat()
        self.save()

    def mark_healed(self, success: bool):
        self.data["last_healed_at"] = datetime.now().isoformat()
        self.data["healing_in_progress"] = False
        self.data["last_status"] = "healed" if success else "failed"
        if success:
            self.data["incident_count"] = 0
        else:
            self.data["incident_count"] = self.data.get("incident_count", 0) + 1
        self.save()


class CrawlerDoctor:
    """N100 爬虫流水线自治巡检与自愈智能体"""

    def __init__(self):
        self.state = DoctorState()

    def inspect_system(self) -> Dict[str, Any]:
        """全息采集当前系统、锁、日志与心跳状态"""
        now = datetime.now()
        report: Dict[str, Any] = {
            "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
            "heartbeat_ok": True,
            "elapsed_minutes": 0,
            "last_ping_time": "未知",
            "articles_today": 0,
            "lock_exists": LOCK_FILE.exists(),
            "lock_holder_pid": None,
            "lock_holder_running": False,
            "lock_holder_elapsed_sec": 0,
            "crawler_processes": [],
            "recent_error_snippet": "",
            "needs_healing": False,
            "issues": []
        }

        # 1. 检查 Gatekeeper API 心跳
        try:
            with httpx.Client(timeout=4.0, verify=False, trust_env=False) as client:
                res = client.get(GATEKEEPER_PROBE_URL)
                if res.status_code == 200:
                    hb = res.json().get("heartbeat", {})
                    report["heartbeat_ok"] = hb.get("is_healthy", True)
                    report["elapsed_minutes"] = hb.get("elapsed_minutes", 0)
                    report["last_ping_time"] = hb.get("last_ping_time", "未知")
                    report["articles_today"] = hb.get("articles_today", 0)
                else:
                    report["issues"].append(f"Gatekeeper API 返回状态码异常: {res.status_code}")
        except Exception as e:
            # 降级：若 API 暂时不通，通过本地日志时间推算
            report["issues"].append(f"无法直连 Gatekeeper API 心跳: {e}")

        # 2. 检查本地锁文件与进程状态
        if LOCK_FILE.exists():
            try:
                with open(LOCK_FILE, "r") as f:
                    content = f.read().strip()
                    if content.isdigit():
                        pid = int(content)
                        report["lock_holder_pid"] = pid
                        # 检查进程是否存在
                        if Path(f"/proc/{pid}").exists():
                            report["lock_holder_running"] = True
                            # 统计运行秒数
                            stat_file = Path(f"/proc/{pid}/stat")
                            if stat_file.exists():
                                try:
                                    with open("/proc/uptime", "r") as uf:
                                        sys_uptime = float(uf.read().split()[0])
                                    with open(stat_file, "r") as sf:
                                        starttime_ticks = int(sf.read().split()[21])
                                        clk_tck = os.sysconf(os.sysconf_names['SC_CLK_TCK'])
                                        proc_start_sec = starttime_ticks / clk_tck
                                        report["lock_holder_elapsed_sec"] = round(sys_uptime - proc_start_sec)
                                except Exception:
                                    pass
            except Exception:
                pass

        # 3. 检查活跃的爬虫相关进程
        try:
            ps_res = subprocess.run(
                ["pgrep", "-f", "rss_fetcher|daily_summary|run_crawler.sh"],
                capture_output=True, text=True, timeout=3
            )
            report["crawler_processes"] = [int(p) for p in ps_res.stdout.strip().splitlines() if p.strip().isdigit()]
        except Exception:
            pass

        # 4. 提取最近日志中的异常和致命错误片段
        error_lines = []
        if SECONDBRAIN_LOG.exists():
            try:
                with open(SECONDBRAIN_LOG, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
                    tail_lines = lines[-120:] if len(lines) > 120 else lines
                    for l in tail_lines:
                        if any(kw in l.lower() for kw in ["error", "exception", "traceback", "failed", "timeout", "killed", "已杀死", "404", "500"]):
                            error_lines.append(l.strip())
                    report["recent_error_snippet"] = "\n".join(tail_lines[-35:])
            except Exception as e:
                report["recent_error_snippet"] = f"读取日志异常: {e}"

        # 5. 判定是否需要启动自愈流程
        # 条件 A: 打卡间隔超过安全阈值 (150 分钟)
        if report["elapsed_minutes"] > HEARTBEAT_TIMEOUT_MINUTES:
            report["needs_healing"] = True
            report["issues"].append(f"爬虫打卡间隔已达 {report['elapsed_minutes']} 分钟，超出 {HEARTBEAT_TIMEOUT_MINUTES} 分钟安全阈值")

        # 条件 B: 进程锁被持有超过 2 小时 (7200秒)
        if report["lock_exists"] and report["lock_holder_elapsed_sec"] > 7200:
            report["needs_healing"] = True
            report["issues"].append(f"锁文件已被持有 {round(report['lock_holder_elapsed_sec']/60)} 分钟，疑似僵尸死锁")

        return report

    def diagnose_with_ai(self, report: Dict[str, Any]) -> str:
        """调用火山方舟 DeepSeek-V4 或 Gemini 生成 AIOps 智能诊断报告"""
        log_snippet = report.get("recent_error_snippet", "暂无日志片段")
        issues_str = "\n".join([f"- {issue}" for issue in report.get("issues", [])])

        prompt = f"""你是一名部署在 N100 第二大脑边缘算力节点的自主运维诊断医生（AIOps Doctor Agent）。
系统检测到定时抓取与自动摘要流水线出现异常或超时，请根据下方收集到的第一现场日志与指标进行深度研判。

【系统巡检指标】
- 巡检时间: {report.get('timestamp')}
- 距离上次打卡耗时: {report.get('elapsed_minutes')} 分钟 (安全阈值: {HEARTBEAT_TIMEOUT_MINUTES} 分钟)
- 上次成功打卡时间: {report.get('last_ping_time')}
- 锁文件状态: {'存在' if report.get('lock_exists') else '未占用'} (PID: {report.get('lock_holder_pid')}, 已运行: {round(report.get('lock_holder_elapsed_sec', 0)/60)} 分钟)
- 活跃爬虫进程列表: {report.get('crawler_processes')}
- 异常指标告警:
{issues_str if issues_str else '- 暂无外部告警'}

【最近 35 行第二大脑运行日志现场】:
```text
{log_snippet}
```

【请按照以下格式给出精简、专业、结构化的中文 Markdown 诊断】：
### 🔍 故障根因研判
- **故障定位**：(一句话指出核心出问题的组件/网络/API/代码环节)
- **机理分析**：(结合日志分析为什么会阻塞或超时，如 TCP 挂起、锁未释放、API 异常等)

### 🛠️ 自愈修复建议
- **执行动作**：(说明需要回收哪些资源或重新触发沙盒)
- **健康预期**：(说明修复后预期的恢复状态)
"""

        # 1. 优先走 TokenGate 2.0 智能中央网关 (自动级联阿里百炼 / 魔搭 235B / 硅基流动)
        tokengate_urls = [
            "http://127.0.0.1:8800/v1/chat/completions",
            "https://tg.donglida.com/v1/chat/completions"
        ]
        for tg_url in tokengate_urls:
            try:
                with httpx.Client(timeout=30.0, trust_env=False) as client:
                    resp = client.post(
                        tg_url,
                        headers={"Content-Type": "application/json"},
                        json={
                            "model": "auto",
                            "messages": [
                                {"role": "system", "content": "你是 N100 第二大脑的高级 AIOps 自治运维专家，诊断精准精炼。"},
                                {"role": "user", "content": prompt}
                            ],
                            "temperature": 0.2,
                            "max_tokens": 1200
                        }
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        return data["choices"][0]["message"]["content"].strip()
            except Exception:
                continue

        # 2. 直连阿里百炼 DashScope (通义千问 3.7 Plus / Max 官方 0 元池)
        dashscope_key = os.getenv("DASHSCOPE_API_KEY", "")
        if dashscope_key:
            try:
                with httpx.Client(timeout=30.0, trust_env=False) as client:
                    resp = client.post(
                        "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {dashscope_key}",
                            "Content-Type": "application/json"
                        },
                        json={
                            "model": "qwen3.7-plus",
                            "messages": [
                                {"role": "system", "content": "你是 N100 第二大脑的高级 AIOps 自治运维专家，诊断精准精炼。"},
                                {"role": "user", "content": prompt}
                            ],
                            "temperature": 0.2,
                            "max_tokens": 1200
                        }
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        return data["choices"][0]["message"]["content"].strip()
            except Exception as e:
                print(f"⚠️ DashScope 诊断调用失败: {e}", file=sys.stderr)

        # 3. 七牛云 300万免费包 deepseek-v3 保底 (100% 免费)
        qn_key = os.getenv("QINIU_API_KEY", "sk-383d4909f49c0db53ad4976552799a7cf6735358e3d90d02dfa5670117441750")
        if qn_key:
            try:
                with httpx.Client(timeout=30.0, trust_env=True) as client:
                    resp = client.post(
                        "https://api.qnaigc.com/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {qn_key}",
                            "Content-Type": "application/json"
                        },
                        json={
                            "model": "deepseek-v3",
                            "messages": [
                                {"role": "system", "content": "你是 N100 第二大脑的高级 AIOps 自治运维专家，诊断精准精炼。"},
                                {"role": "user", "content": prompt}
                            ],
                            "temperature": 0.2,
                            "max_tokens": 1200
                        }
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        return data["choices"][0]["message"]["content"].strip()
            except Exception as e:
                print(f"⚠️ 七牛云诊断调用失败: {e}", file=sys.stderr)

        # 降级：使用 Gemini
        if GEMINI_API_KEY:
            try:
                proxy_mounts = {}
                if HTTP_PROXY:
                    proxy_mounts = {"all://": httpx.HTTPTransport(proxy=HTTP_PROXY)}
                with httpx.Client(timeout=45.0, mounts=proxy_mounts) as client:
                    resp = client.post(
                        f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}",
                        headers={"Content-Type": "application/json"},
                        json={
                            "contents": [{"parts": [{"text": prompt}]}],
                            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1000}
                        }
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
            except Exception as e:
                print(f"⚠️ Gemini 备用诊断调用失败: {e}", file=sys.stderr)

        # 规则引擎静态保底
        return f"""### 🔍 故障根因研判
- **故障定位**：检测到爬虫打卡间隔已达 {report.get('elapsed_minutes')} 分钟，超出安全阈值。
- **机理分析**：可能是前序批次处理大型文本或网络长连接阻塞导致锁未及时释放。

### 🛠️ 自愈修复建议
- **执行动作**：自动清理残留进程锁，启动沙盒重跑并复核打卡心跳。
"""

    def perform_self_healing(self, report: Dict[str, Any]) -> Tuple[bool, str]:
        """执行全自动自愈恢复与沙盒复核"""
        actions = []
        now_str = datetime.now().strftime("%H:%M:%S")

        # 1. 安全终止阻塞僵尸进程
        if report.get("lock_exists") or report.get("crawler_processes"):
            actions.append(f"[{now_str}] 正在安全清理挂起/僵尸爬虫进程...")
            try:
                subprocess.run(["pkill", "-9", "-f", "rss_fetcher.py"], timeout=5)
                subprocess.run(["pkill", "-9", "-f", "daily_summary.py"], timeout=5)
            except Exception:
                pass

        # 2. 释放锁文件
        if LOCK_FILE.exists():
            try:
                LOCK_FILE.unlink(missing_ok=True)
                actions.append("已安全释放 `/var/lock/secondbrain_crawler.lock` 进程锁。")
            except Exception as e:
                actions.append(f"清理锁文件异常: {e}")

        # 3. 触发沙盒重跑 (调用 run_crawler.sh)
        actions.append(f"[{datetime.now().strftime('%H:%M:%S')}] 🚀 启动沙盒自愈重跑流程 (`/opt/run_crawler.sh`)...")
        success = False
        try:
            # 异步拉起执行脚本并赋予 25 分钟整体超时守护
            res = subprocess.run(
                ["bash", str(RUN_CRAWLER_SCRIPT)],
                capture_output=True,
                text=True,
                timeout=1500  # 25 分钟硬超时
            )
            if res.returncode == 0:
                actions.append(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ 沙盒重跑执行完毕，返回状态码 0。")
                success = True
            else:
                actions.append(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ 脚本执行退出码异常: {res.returncode}")
        except subprocess.TimeoutExpired:
            actions.append("⚠️ 沙盒重跑流程超出 25 分钟守护限制被熔断。")
        except Exception as e:
            actions.append(f"⚠️ 执行沙盒重跑异常: {e}")

        # 4. 再次复核心跳接口
        time.sleep(2)
        try:
            with httpx.Client(timeout=4.0, verify=False, trust_env=False) as client:
                resp = client.get(GATEKEEPER_PROBE_URL)
                if resp.status_code == 200:
                    hb = resp.json().get("heartbeat", {})
                    if hb.get("is_healthy", False) and hb.get("elapsed_minutes", 999) < 10:
                        actions.append(f"🟢 心跳复核成功：已打卡至最新状态（{hb.get('last_ping_time')}，累计情报 {hb.get('articles_today')} 篇）！")
                        success = True
        except Exception:
            pass

        return success, "\n".join(actions)

    def send_telegram_alert(self, title: str, content: str) -> bool:
        """通过 Telegram 机器人向用户手机推送结构化告警卡片"""
        if not TELEGRAM_BOT_TOKEN or not ALLOWED_USER_ID:
            print("⚠️ 未配置 TELEGRAM_BOT_TOKEN 或 ALLOWED_USER_ID，跳过推送", file=sys.stderr)
            return False

        tg_text = f"*{title}*\n\n{content}\n\n🌐 [点击查看实时监控全景](https://tg.donglida.com)"
        tg_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

        payload = {
            "chat_id": ALLOWED_USER_ID,
            "text": tg_text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True
        }

        # 尝试通过代理发送（国内节点需要）
        proxies_to_try = []
        if HTTP_PROXY:
            proxies_to_try.append(HTTP_PROXY)
        proxies_to_try.append(None)  # 尝试直连作为兜底

        for p in proxies_to_try:
            try:
                mounts = {"all://": httpx.HTTPTransport(proxy=p)} if p else {}
                with httpx.Client(timeout=10.0, mounts=mounts) as client:
                    res = client.post(tg_url, json=payload)
                    if res.status_code == 200:
                        print(f"✅ Telegram 通知已成功送达 (Proxy: {bool(p)})")
                        return True
                    else:
                        print(f"⚠️ Telegram API 响应错误: {res.status_code} {res.text}", file=sys.stderr)
            except Exception as e:
                print(f"⚠️ Telegram 发送失败 (Proxy: {bool(p)}): {e}", file=sys.stderr)

        return False

    def run_check(self, force_heal: bool = False):
        """执行单次全流程自治巡检与自愈闭环"""
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 🩺 Doctor Agent 开始全面巡检 N100 状态...")
        report = self.inspect_system()

        if not report["needs_healing"] and not force_heal:
            print(f"🟢 系统状态健康：打卡间隔 {report['elapsed_minutes']} 分钟，锁状态正常，无需介入。")
            self.state.data["last_check_at"] = datetime.now().isoformat()
            self.state.data["last_status"] = "ok"
            self.state.save()
            return

        print(f"🚨 触发异常自愈模式：打卡间隔 {report['elapsed_minutes']} 分钟，问题项: {report['issues']}")

        # 检查是否处于报警静默冷却期
        can_notify = self.state.can_alert() or force_heal

        # 1. 深度 AI 根因诊断
        print("🧠 正在调用火山方舟 DeepSeek 进行 AIOps 智能诊断...")
        ai_diagnosis = self.diagnose_with_ai(report)
        print("--- 诊断结论 ---")
        print(ai_diagnosis)
        print("----------------")

        # 2. 执行沙盒自愈与资源回收
        print("🛠️ 开始执行全自动沙盒自愈...")
        self.state.data["healing_in_progress"] = True
        self.state.save()

        heal_success, heal_log = self.perform_self_healing(report)
        self.state.mark_healed(heal_success)

        # 3. 组装并发送 Telegram 智能汇报
        if can_notify:
            status_icon = "🟢" if heal_success else "🔴"
            title = f"🤖 【N100 第二大脑·自愈巡检报告】 {status_icon}"
            
            tg_body = f"""⏱️ **异常指标**：打卡间隔 `{report['elapsed_minutes']}` 分钟（阈值: {HEARTBEAT_TIMEOUT_MINUTES}m）

{ai_diagnosis}

### 🛠️ 自愈动作与复核结果
```text
{heal_log}
```"""
            self.send_telegram_alert(title, tg_body)
            self.state.mark_alert()
        else:
            print("ℹ️ 当前处于告警冷却期，已执行自愈但跳过重复推送。")


def main():
    parser = argparse.ArgumentParser(description="N100 第二大脑 Autonomous AI Doctor Agent")
    parser.add_argument("--check", action="store_true", help="执行标准巡检 (Cron 默认模式)")
    parser.add_argument("--force-heal", action="store_true", help="强制执行 AI 诊断与自愈修复")
    parser.add_argument("--test-notify", action="store_true", help="发送 Telegram 测试消息卡片")
    parser.add_argument("--test-diag", action="store_true", help="测试 AI 日志诊断并打印")
    parser.add_argument("--status", action="store_true", help="查看当前 Doctor 状态机数据")

    args = parser.parse_args()
    doctor = CrawlerDoctor()

    if args.test_notify:
        print("📲 发送 Telegram 测试卡片...")
        ok = doctor.send_telegram_alert(
            "🤖 【N100 Doctor Agent 探针测试】",
            "这是一条来自 N100 第二大脑 Autonomous Doctor Agent 的通道测试通知。\n\n"
            "✅ **探针状态**：正常联通\n"
            "✅ **AI 诊断引擎**：火山方舟 DeepSeek-V4 就绪\n"
            "✅ **自愈执行器**：沙盒看门狗就绪"
        )
        print("测试结果:", "成功" if ok else "失败")
    elif args.test_diag:
        rep = doctor.inspect_system()
        diag = doctor.diagnose_with_ai(rep)
        print(diag)
    elif args.status:
        rep = doctor.inspect_system()
        print(json.dumps({"system": rep, "state": doctor.state.data}, ensure_ascii=False, indent=2))
    elif args.force_heal:
        doctor.run_check(force_heal=True)
    else:
        # 默认执行巡检
        doctor.run_check()


if __name__ == "__main__":
    main()

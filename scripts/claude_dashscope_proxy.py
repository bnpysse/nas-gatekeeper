#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Claude Desktop -> 阿里云百炼 DeepSeek-V4-Pro 超轻量零依赖本地代理网关
无需安装任何三方库，基于 Python 标准库 (http.server + urllib.request) 实现。
功能：
1. 拦截 Claude Desktop 的 /v1/models 探测请求，返回 Claude 标准模型列表 (绕过 404 探测报错)
2. 拦截 Claude Desktop 的 /v1/messages 推理请求，将所有 Claude 模型名 (如 claude-sonnet-4-5) 
   自动重写为 deepseek-v4-pro-0813 并透传至阿里云百炼，支持流式 SSE 极速打字机响应。
"""

import sys
import os
import json
import logging
import urllib.request
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("Claude-DashScope-Proxy")

DASHSCOPE_API_KEY = "sk-ws-H.ELXPIRL.ZmKW.MEUCIDJQOLBMCqUE29GFEP6r6Vn-W-DBO1GbVnAitG7x-ecXAiEAvY68YEXkKJJ4CXbqqF90yJxsUxnZ4zWgdjH9DNiEME8"
TARGET_MODEL = "deepseek-v4-pro-0813"
UPSTREAM_URL = "https://dashscope.aliyuncs.com/apps/anthropic/v1/messages"
PORT = 15722

MODELS_RESPONSE = {
    "data": [
        {"id": "claude-sonnet-4-5", "object": "model", "created": 1778000000, "owned_by": "anthropic"},
        {"id": "claude-3-7-sonnet-20250219", "object": "model", "created": 1778000000, "owned_by": "anthropic"},
        {"id": "claude-3-5-sonnet-20241022", "object": "model", "created": 1778000000, "owned_by": "anthropic"},
        {"id": "claude-haiku-4-5-20251001", "object": "model", "created": 1778000000, "owned_by": "anthropic"},
        {"id": "deepseek-v4-pro-0813", "object": "model", "created": 1778000000, "owned_by": "dashscope"}
    ]
}

class ProxyHandler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def do_GET(self):
        # 响应 /v1/models 探测
        if "models" in self.path:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(MODELS_RESPONSE).encode("utf-8"))
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "running", "target_model": TARGET_MODEL}).encode("utf-8"))

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        req_body = self.rfile.read(content_length)

        try:
            payload = json.loads(req_body.decode("utf-8"))
        except Exception:
            payload = {}

        incoming_model = payload.get("model", "")
        # 将任何请求模型强制映射为百炼支持的 deepseek-v4-pro-0813
        payload["model"] = TARGET_MODEL
        logger.info(f"🔄 收到推理请求: 模型 [{incoming_model}] ➔ 重写映射为 [{TARGET_MODEL}] (流式: {payload.get('stream', False)})")

        modified_body = json.dumps(payload).encode("utf-8")

        req = urllib.request.Request(
            UPSTREAM_URL,
            data=modified_body,
            headers={
                "x-api-key": DASHSCOPE_API_KEY,
                "anthropic-version": self.headers.get("anthropic-version", "2023-06-01"),
                "Content-Type": "application/json"
            },
            method="POST"
        )

        try:
            # 禁用环境变量代理，直连阿里云百炼
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(req, timeout=120) as resp:
                self.send_response(resp.status)
                for k, v in resp.headers.items():
                    if k.lower() in ("content-type", "cache-control", "connection"):
                        self.send_header(k, v)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                while True:
                    chunk = resp.read(1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
        except urllib.error.HTTPError as e:
            logger.error(f"❌ 上游百炼 HTTP 报错: {e.code} - {e.reason}")
            self.send_response(e.code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(e.read())
        except Exception as e:
            logger.error(f"❌ 请求失败: {e}")
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))

def run():
    server = HTTPServer(("127.0.0.1", PORT), ProxyHandler)
    logger.info(f"🚀 Claude Desktop -> 阿里云百炼 DeepSeek-V4-Pro 代理网关已启动: http://127.0.0.1:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()

if __name__ == "__main__":
    run()

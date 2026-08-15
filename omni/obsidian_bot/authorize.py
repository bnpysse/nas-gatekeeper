#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Google Drive OAuth 2.0 一键授权工具
只需运行一次，即可在本地生成永久自动刷新的 token.json 文件！
将 token.json 部署到 N100 后，N100 即可 24/7 直传你的 5TB 个人 Google Drive 云盘！
"""

import sys
from pathlib import Path

parent_dir = str(Path(__file__).resolve().parent)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

SCOPES = [
    'https://www.googleapis.com/auth/drive.file',
    'https://www.googleapis.com/auth/drive'
]

def main():
    base_dir = Path(__file__).resolve().parent
    client_secret_file = base_dir / "client_secret.json"

    if not client_secret_file.exists():
        # 尝试查找任何 client_secret_*.json
        json_files = list(base_dir.glob("client_secret_*.json"))
        if json_files:
            client_secret_file = json_files[0]
        else:
            print(f"❌ 错误：未找到凭证文件 {client_secret_file.name}！")
            print("请先在 Google Cloud Console 下载 OAuth 客户端 JSON 凭据，重命名为 client_secret.json 放到当前目录。")
            sys.exit(1)

    print(f"🔑 正在读取凭证文件: {client_secret_file.name}...")

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow

        flow = InstalledAppFlow.from_client_secrets_file(
            str(client_secret_file), SCOPES
        )
        print("🌐 正在启动本地临时授权服务器，浏览器将自动打开进行一次性授权...")
        creds = flow.run_local_server(port=0)

        token_file = base_dir / "token.json"
        with open(token_file, "w", encoding="utf-8") as f:
            f.write(creds.to_json())

        print(f"\n🎉 授权成功！永久令牌已保存至: {token_file}")
        print("现在你可以将 token.json 部署到 N100，程序将具备 24/7 直传你的个人 5TB 云盘能力！")

    except Exception as e:
        print(f"❌ 授权失败: {e}")

if __name__ == "__main__":
    main()

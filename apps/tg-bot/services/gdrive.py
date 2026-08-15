#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Google Drive API v3 客户端服务
支持使用 OAuth 2.0 刷新令牌 (token.json) 或服务账号 (service_account.json)
实现 24/7 脱离本地桌面客户端的网络直连云端上报
"""

import os
import sys
import logging
from pathlib import Path

parent_dir = str(Path(__file__).resolve().parent.parent)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from config import Config

logger = logging.getLogger(__name__)

SCOPES = ['https://www.googleapis.com/auth/drive.file', 'https://www.googleapis.com/auth/drive']

def get_credentials():
    """
    自动按优先级加载 Google API 凭证
    1. token.json (OAuth 2.0 用户身份凭证，首选，直接写入个人 5TB 云盘)
    2. service_account.json (服务账号凭证)
    """
    base_dir = Path(__file__).resolve().parent.parent  # /app/src or repo root/src

    token_candidates = [
        base_dir.parent / "token.json",     # /app/token.json
        Path("/app/token.json"),
        base_dir / "token.json",            # /app/src/token.json
        Path("/app/config/token.json"),
        Path("/etc/secondbrain/token.json"),
        Path.home() / ".config/secondbrain/token.json",
    ]

    for cand in token_candidates:
        if cand.exists():
            try:
                from google.oauth2.credentials import Credentials
                from google.auth.transport.requests import Request

                creds = Credentials.from_authorized_user_file(str(cand), SCOPES)
                if creds and creds.expired and creds.refresh_token:
                    logger.info("token.json 访问令牌已过期，正在自动刷新...")
                    creds.refresh(Request())
                    try:
                        with open(cand, 'w', encoding='utf-8') as f:
                            f.write(creds.to_json())
                        logger.info("token.json 访问令牌自动刷新保存成功！")
                    except Exception as write_err:
                        logger.warning(f"写入刷新后的 token.json 失败 (如只读挂载)，但在内存中已成功刷新可正常使用: {write_err}")
                return creds, "oauth_token"
            except Exception as e:
                logger.warning(f"加载 token.json 凭证失败: {e}")

    sa_candidates = [
        base_dir.parent / "service_account.json", # /app/service_account.json
        Path("/app/service_account.json"),
        base_dir / "service_account.json",        # /app/src/service_account.json
        Path("/app/config/service_account.json"),
        Path("/etc/secondbrain/service_account.json"),
        Path.home() / ".config/secondbrain/service_account.json",
    ]

    for cand in sa_candidates:
        if cand.exists():
            try:
                from google.oauth2 import service_account
                creds = service_account.Credentials.from_service_account_file(
                    str(cand), scopes=SCOPES
                )
                return creds, "service_account"
            except Exception as e:
                logger.warning(f"加载 service_account.json 凭证失败: {e}")

    return None, None

def upload_file_to_gdrive_api(local_file: Path, target_folder_name: str = "Inbox") -> str | None:
    """
    通过 Google Drive API (v3) 直接上传本地文件至云端指定文件夹
    使用 AuthorizedSession (基于 requests)，天然完美支持 HTTP_PROXY 代理

    Args:
        local_file: 本地文件路径
        target_folder_name: 云盘目标文件夹名称 (默认 "Stock")

    Returns:
        str: 云端文件访问链接 (webViewLink)
    """
    creds, cred_type = get_credentials()
    if not creds:
        logger.warning("⚠️ 未找到 Google API 凭证 (token.json / service_account.json)，跳过云端直传。")
        return None

    try:
        import json
        from google.auth.transport.requests import AuthorizedSession

        logger.info(f"使用凭证类型 [{cred_type}] 初始化 Google Drive API (AuthorizedSession)...")
        session = AuthorizedSession(creds)

        # Step 1: 搜索目标文件夹 ID
        q = f"name = '{target_folder_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        res = session.get(
            "https://www.googleapis.com/drive/v3/files",
            params={"q": q, "fields": "files(id, name)"},
            timeout=30
        )
        res.raise_for_status()
        files = res.json().get("files", [])

        if files:
            folder_id = files[0]["id"]
            logger.info(f"在云端找到已有目标文件夹 [{target_folder_name}], ID: {folder_id}")
        else:
            create_res = session.post(
                "https://www.googleapis.com/drive/v3/files",
                json={
                    "name": target_folder_name,
                    "mimeType": "application/vnd.google-apps.folder"
                },
                params={"fields": "id"},
                timeout=30
            )
            create_res.raise_for_status()
            folder_id = create_res.json().get("id")
            logger.info(f"在云端自动新建目标文件夹 [{target_folder_name}], ID: {folder_id}")

        # Step 2: Multipart 上传 Markdown 文件与元数据
        mime_type = "text/markdown" if local_file.suffix in [".md", ".markdown"] else "text/plain"
        metadata = {
            "name": local_file.name,
            "parents": [folder_id]
        }

        with open(local_file, "rb") as f:
            file_bytes = f.read()

        files_payload = {
            "data": ("metadata", json.dumps(metadata), "application/json; charset=UTF-8"),
            "file": (local_file.name, file_bytes, mime_type)
        }

        logger.info(f"正在通过代理直传文件至 Google Drive: {local_file.name}...")
        upload_res = session.post(
            "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id,webViewLink",
            files=files_payload,
            timeout=60
        )
        upload_res.raise_for_status()
        res_data = upload_res.json()
        web_link = res_data.get("webViewLink")
        file_id = res_data.get("id")

        logger.info(f"🎉 文件已成功直接打入 Google Drive 云端！ID: {file_id}, 链接: {web_link}")
        return web_link

    except Exception as e:
        logger.error(f"Google Drive API 直传失败: {e}", exc_info=True)
        return None

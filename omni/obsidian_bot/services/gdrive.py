#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Google Drive API v3 客户端服务
支持 OAuth 2.0 用户授权 (token.json) 直传个人 5TB 云盘，无需管理共享文件夹
完美支持 24/7 无人值守直连云端上传
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
    自动获取 Google Drive API 凭证。
    优先顺序：
    1. token.json (OAuth 2.0 用户身份凭证，无配额限制，直接写入个人云盘)
    2. service_account.json (服务账号凭证)
    """
    base_dir = Path(__file__).resolve().parent.parent

    # 1. 检查 token.json
    token_candidates = [
        base_dir / "token.json",
        Path("/etc/nas-gatekeeper/token.json"),
        Path.home() / ".config/nas-gatekeeper/token.json",
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
                    with open(cand, 'w', encoding='utf-8') as f:
                        f.write(creds.to_json())
                    logger.info("token.json 自动刷新完成并更保存！")
                return creds, "oauth_token"
            except Exception as e:
                logger.warning(f"加载 token.json 失败: {e}")

    # 2. 检查 service_account.json
    sa_candidates = [
        base_dir / "service_account.json",
        Path("/etc/nas-gatekeeper/service_account.json"),
        Path.home() / ".config/nas-gatekeeper/service_account.json",
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
                logger.warning(f"加载 service_account.json 失败: {e}")

    return None, None

def upload_file_to_gdrive_api(local_file: Path, target_folder_name: str = "Stock") -> str | None:
    """
    通过 Google Drive API (v3) 直接上传本地文件至云端指定文件夹

    Args:
        local_file: 本地文件路径
        target_folder_name: Google 云盘中的目标文件夹名称 (默认 "Stock")

    Returns:
        str: 上传成功后的云端文件 webViewLink，若失败返回 None
    """
    creds, cred_type = get_credentials()
    if not creds:
        logger.debug("未找到 Google API 授权凭证 (token.json / service_account.json)，跳过云端直传。")
        return None

    try:
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload

        logger.info(f"使用凭证类型 [{cred_type}] 初始化 Google Drive API v3...")
        drive_service = build('drive', 'v3', credentials=creds, cache_discovery=False)

        # Step 1: 搜索目标文件夹 ID
        query = f"name = '{target_folder_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        results = drive_service.files().list(
            q=query,
            fields="files(id, name)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True
        ).execute()
        folders = results.get('files', [])

        folder_id = None
        if folders:
            folder_id = folders[0]['id']
            logger.info(f"在云端找到已有目标文件夹 [{target_folder_name}], ID: {folder_id}")
        else:
            # 不存在则自动新建文件夹
            folder_metadata = {
                'name': target_folder_name,
                'mimeType': 'application/vnd.google-apps.folder'
            }
            folder = drive_service.files().create(body=folder_metadata, fields='id', supportsAllDrives=True).execute()
            folder_id = folder.get('id')
            logger.info(f"在云端自动新建目标文件夹 [{target_folder_name}], ID: {folder_id}")

        # Step 2: 上传文件
        file_metadata = {
            'name': local_file.name,
            'parents': [folder_id]
        }

        mime_type = "text/markdown" if local_file.suffix in [".md", ".markdown"] else "text/plain"
        media = MediaFileUpload(str(local_file), mimetype=mime_type, resumable=True)

        logger.info(f"正在直接上报文件至 Google Drive 云端: {local_file.name}...")
        uploaded_file = drive_service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, webViewLink',
            supportsAllDrives=True
        ).execute()

        web_link = uploaded_file.get('webViewLink')
        file_id = uploaded_file.get('id')
        logger.info(f"🎉 文件已成功直传塞入 Google Drive 云端！ID: {file_id}, 链接: {web_link}")
        return web_link

    except Exception as e:
        logger.error(f"Google Drive API 直传失败: {e}", exc_info=True)
        return None

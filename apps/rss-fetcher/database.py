import os
import libsql_client
from dotenv import load_dotenv

load_dotenv(override=True)

def get_client():
    """获取 Turso 同步客户端实例"""
    url = os.environ.get("TURSO_DATABASE_URL")
    auth_token = os.environ.get("TURSO_AUTH_TOKEN")
    if not url or not auth_token:
        raise ValueError("Missing TURSO_DATABASE_URL or TURSO_AUTH_TOKEN in .env")
    return libsql_client.create_client_sync(url=url, auth_token=auth_token)

def init_db():
    """初始化数据库和表结构"""
    client = get_client()
    # 创建一个表来存储已处理的 URL 或标识符
    client.execute('''
        CREATE TABLE IF NOT EXISTS processed_items (
            id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    client.close()

def is_processed(item_id: str) -> bool:
    """检查某个项目是否已经处理过"""
    client = get_client()
    result = client.execute('SELECT 1 FROM processed_items WHERE id = ?', [item_id])
    client.close()
    return len(result.rows) > 0

def mark_processed(item_id: str, source: str):
    """将项目标记为已处理"""
    client = get_client()
    client.execute('INSERT OR IGNORE INTO processed_items (id, source) VALUES (?, ?)', [item_id, source])
    client.close()

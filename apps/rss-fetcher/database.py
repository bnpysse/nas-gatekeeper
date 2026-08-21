import os
import sqlite3
from pathlib import Path

def get_db_path() -> Path:
    """获取 SQLite 数据库存储路径，存放在应用独立目录中以避免被同步工具误删"""
    n100_db = Path("/opt/nas-gatekeeper/apps/rss-fetcher/processed_items.db")
    if n100_db.parent.exists():
        return n100_db
        
    return Path(__file__).parent / "processed_items.db"

def get_connection():
    """获取本地 SQLite 数据库连接"""
    db_path = get_db_path()
    conn = sqlite3.connect(str(db_path), timeout=10.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn

def init_db():
    """初始化数据库和表结构"""
    with get_connection() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS processed_items (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()

def is_processed(item_id: str) -> bool:
    """检查某个项目是否已经处理过"""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT 1 FROM processed_items WHERE id = ? LIMIT 1', (item_id,))
            row = cursor.fetchone()
            return row is not None
    except Exception as e:
        print(f"⚠️ 查询已处理状态异常 (自动降级为未处理): {e}")
        return False

def mark_processed(item_id: str, source: str):
    """将项目标记为已处理"""
    try:
        with get_connection() as conn:
            conn.execute('INSERT OR IGNORE INTO processed_items (id, source) VALUES (?, ?)', (item_id, source))
            conn.commit()
    except Exception as e:
        print(f"⚠️ 标记已处理状态异常: {e}")

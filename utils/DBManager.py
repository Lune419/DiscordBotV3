"""
db_manager.py - SQLite 資料庫管理程式
功能說明：
  1. 使用 aiosqlite 提供非同步操作，適用於 Discord Bot 或其他 asyncio 應用
  2. 提供 AsyncDBManager 類別，可由其他程式直接 import
  3. CLI 僅在直接執行時啟動，透過 asyncio.run

範例（匯入模組）：
    from db_manager import AsyncDBManager
    import asyncio

    async def run():
        db = AsyncDBManager('bot.db')
        await db.init_db()
        await db.add_punishment(guild_id=1, user_id=42, punished_at=1654567890,
                                 ptype='warn', reason='不當發言')
    asyncio.run(run())

CLI 用法：
  python db_manager.py init-db --db bot.db
  python db_manager.py add-punishment --db bot.db --guild 1 --user 2 --time 1654567890 --type warn --reason "測試"
"""

__all__ = ['DBManager']

import aiosqlite
import argparse
import asyncio
import sys
import os
import dotenv
from typing import Optional, List, Any

class DBManager:
    """非同步資料庫管理類別"""
    def __init__(self, db_path: str):
        self.db_path = os.getenv('database', db_path)
        self.conn: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        """建立連線並設定 row_factory"""
        if self.conn is None:
            self.conn = await aiosqlite.connect(self.db_path)
            self.conn.row_factory = aiosqlite.Row

    async def init_db(self) -> None:
        """初始化資料表與索引"""
        await self.connect()
        async with self.conn.cursor() as cur:
            await cur.execute(
                """
                CREATE TABLE IF NOT EXISTS punishments (
                    punish_id    INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id     INTEGER NOT NULL,
                    user_id      INTEGER NOT NULL,
                    punished_at  INTEGER NOT NULL,
                    type         TEXT    NOT NULL,
                    reason       TEXT
                )
                """
            )
            await cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_punishments_guild_user ON punishments(guild_id, user_id)"
            )
            await cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_punishments_time ON punishments(punished_at)"
            )
            await cur.execute(
                """
                CREATE TABLE IF NOT EXISTS server_events (
                    event_id    INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id    INTEGER NOT NULL,
                    user_id     INTEGER,
                    event_type  TEXT    NOT NULL,
                    event_time  INTEGER NOT NULL
                )
                """
            )
            await cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_guild ON server_events(guild_id)"
            )
            await cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_user ON server_events(user_id)"
            )
            await cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_time ON server_events(event_time)"
            )
            await cur.execute(
                """
                CREATE TABLE IF NOT EXISTS server_settings (
                    guild_id              INTEGER PRIMARY KEY,
                    notify_channel        INTEGER,
                    voice_log_channel     INTEGER,
                    member_log_channel    INTEGER,
                    message_log_channel   INTEGER,
                    anti_dive_channel     INTEGER
                )
                """
            )
        await self.conn.commit()

    # --------- punishments CRUD ---------
    async def add_punishment(
        self, guild_id: int, user_id: int, punished_at: int,
        ptype: str, reason: Optional[str]
    ) -> None:
        """新增處分紀錄"""
        await self.connect()
        await self.conn.execute(
            "INSERT INTO punishments (guild_id, user_id, punished_at, type, reason) VALUES (?, ?, ?, ?, ?)",
            (guild_id, user_id, punished_at, ptype, reason)
        )
        await self.conn.commit()

    async def list_punishments(
        self, guild_id: int, user_id: Optional[int] = None,
        limit: int = 100
    ) -> List[aiosqlite.Row]:
        """查詢處分紀錄"""
        await self.connect()
        if user_id is not None:
            cursor = await self.conn.execute(
                "SELECT * FROM punishments WHERE guild_id = ? AND user_id = ? ORDER BY punished_at DESC LIMIT ?",
                (guild_id, user_id, limit)
            )
        else:
            cursor = await self.conn.execute(
                "SELECT * FROM punishments WHERE guild_id = ? ORDER BY punished_at DESC LIMIT ?",
                (guild_id, limit)
            )
        rows = await cursor.fetchall()
        return rows

    # --------- server_events CRUD ---------
    async def add_event(
        self, guild_id: int, event_type: str, event_time: int,
        user_id: Optional[int] = None
    ) -> None:
        """新增伺服器事件"""
        await self.connect()
        await self.conn.execute(
            "INSERT INTO server_events (guild_id, user_id, event_type, event_time) VALUES (?, ?, ?, ?)",
            (guild_id, user_id, event_type, event_time)
        )
        await self.conn.commit()

    async def list_events(
        self, guild_id: int, user_id: Optional[int] = None,
        limit: int = 100
    ) -> List[aiosqlite.Row]:
        """查詢伺服器事件"""
        await self.connect()
        if user_id is not None:
            cursor = await self.conn.execute(
                "SELECT * FROM server_events WHERE guild_id = ? AND user_id = ? ORDER BY event_time DESC LIMIT ?",
                (guild_id, user_id, limit)
            )
        else:
            cursor = await self.conn.execute(
                "SELECT * FROM server_events WHERE guild_id = ? ORDER BY event_time DESC LIMIT ?",
                (guild_id, limit)
            )
        return await cursor.fetchall()

    # --------- server_settings CRUD ---------
    async def set_settings(
        self, guild_id: int, notify_channel: Optional[int] = None,
        voice_log_channel: Optional[int] = None,
        member_log_channel: Optional[int] = None,
        message_log_channel: Optional[int] = None,
        anti_dive_channel: Optional[int] = None
    ) -> None:
        """設定或更新伺服器配置"""
        await self.connect()
        cursor = await self.conn.execute(
            "SELECT 1 FROM server_settings WHERE guild_id = ?", (guild_id,)
        )
        exists = await cursor.fetchone()
        if exists:
            fields: List[str] = []
            params: List[Any] = []
            for key, val in [
                ("notify_channel", notify_channel),
                ("voice_log_channel", voice_log_channel),
                ("member_log_channel", member_log_channel),
                ("message_log_channel", message_log_channel),
                ("anti_dive_channel", anti_dive_channel)
            ]:
                if val is not None:
                    fields.append(f"{key} = ?")
                    params.append(val)
            if fields:
                params.append(guild_id)
                await self.conn.execute(
                    f"UPDATE server_settings SET {', '.join(fields)} WHERE guild_id = ?",
                    tuple(params)
                )
        else:
            await self.conn.execute(
                "INSERT INTO server_settings (guild_id, notify_channel, voice_log_channel, member_log_channel, message_log_channel, anti_dive_channel) VALUES (?, ?, ?, ?, ?, ?)",
                (guild_id, notify_channel, voice_log_channel, member_log_channel, message_log_channel, anti_dive_channel)
            )
        await self.conn.commit()

    async def get_settings(self, guild_id: int) -> Optional[aiosqlite.Row]:
        """取得伺服器配置"""
        await self.connect()
        cursor = await self.conn.execute(
            "SELECT * FROM server_settings WHERE guild_id = ?", (guild_id,)
        )
        return await cursor.fetchone()

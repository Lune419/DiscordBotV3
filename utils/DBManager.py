import aiosqlite
import argparse
import asyncio
import sys
import os
import dotenv
from typing import Optional, List, Any

class DBManager:
    """
    非同步資料庫管理類別。
    用於管理 Discord Bot 所需的 SQLite 資料表，包含處分紀錄、伺服器事件、伺服器設定等 CRUD 操作。
    實例僅適用於單一資料庫檔案，非多執行緒安全。
    """
    def __init__(self, db_path: str):
        """
        初始化 DBManager 實例。
        參數:
            db_path: 資料庫檔案路徑。
        若環境變數 'database' 存在則優先使用。
        """
        self.db_path = os.getenv('database', db_path)
        self.conn: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        """
        建立與 SQLite 資料庫的非同步連線，並設定 row_factory 以便回傳 dict-like row。
        僅於尚未連線時執行。
        """
        if self.conn is None:
            self.conn = await aiosqlite.connect(self.db_path)
            self.conn.row_factory = aiosqlite.Row

    async def init_db(self) -> None:
        """
        初始化所有資料表與索引。
        若資料表不存在則建立。
        僅需於資料庫首次建立時呼叫。
        """
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
                    admin_id     INTEGER NOT NULL,
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
        self, *,guild_id: int, user_id: int, punished_at: int,
        ptype: str, reason: Optional[str],admin_id:int
    ) -> None:
        """
        新增一筆處分紀錄。
        參數:
            guild_id: 伺服器 ID
            user_id: 被處分用戶 ID
            punished_at: 處分時間 (UNIX timestamp)
            ptype: 處分類型
            reason: 處分原因 (可為 None)
            admin_id: 處分管理員 ID
        """
        await self.connect()
        await self.conn.execute(
            "INSERT INTO punishments (guild_id, user_id, punished_at, type, reason, admin_id) VALUES (?, ?, ?, ?, ?, ?)",
            (guild_id, user_id, punished_at, ptype, reason, admin_id)
        )
        await self.conn.commit()

    async def list_punishments(
        self,
        *,
        guild_id: int,
        user_id: Optional[int] = None,
        ptype: Optional[str] = None,
        start_ts: Optional[int] = None,  # UNIX 時間戳，單位秒
        limit: int = 100
    ) -> List[aiosqlite.Row]:
        """
        查詢處分紀錄。
        可依 guild_id、user_id、處分類型 ptype、起始 UNIX 時間戳 start_ts 篩選。
        參數:
            guild_id: 伺服器 ID (必填)
            user_id: 用戶 ID (可選)
            ptype: 處分類型 (可選)
            start_ts: 起始時間 (可選)
            limit: 回傳筆數上限 (預設 100)
        回傳:
            aiosqlite.Row 組成的 list。
        """
        await self.connect()

        # 1. 動態組裝 WHERE 子句和參數
        conditions = ["guild_id = ?"]
        params = [guild_id]

        if user_id is not None:
            conditions.append("user_id = ?")
            params.append(user_id)

        if ptype is not None:
            conditions.append("type = ?")
            params.append(ptype)

        if start_ts is not None:
            # 直接比較 punished_at（假設為 INTEGER UNIX 時間戳）
            conditions.append("punished_at >= ?")
            params.append(start_ts)

        # 2. 合併 SQL
        where_clause = " AND ".join(conditions)
        sql = f"""
            SELECT *
            FROM punishments
            WHERE {where_clause}
            ORDER BY punished_at DESC
            LIMIT ?
        """
        params.append(limit)

        # 3. 執行並回傳
        cursor = await self.conn.execute(sql, params)
        rows = await cursor.fetchall()
        return rows


    # --------- server_events CRUD ---------
    async def add_event(
        self, guild_id: int, event_type: str, event_time: int,
        user_id: Optional[int] = None
    ) -> None:
        """
        新增一筆伺服器事件。
        參數:
            guild_id: 伺服器 ID
            event_type: 事件類型
            event_time: 事件發生時間 (UNIX timestamp)
            user_id: 相關用戶 ID (可為 None)
        """
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
        """
        查詢伺服器事件。
        參數:
            guild_id: 伺服器 ID
            user_id: 用戶 ID (可選)
            limit: 回傳筆數上限 (預設 100)
        回傳:
            aiosqlite.Row 組成的 list。
        """
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
        """
        設定或更新伺服器配置。
        參數:
            guild_id: 伺服器 ID
            notify_channel: 通知頻道 ID (可選)
            voice_log_channel: 語音紀錄頻道 ID (可選)
            member_log_channel: 成員紀錄頻道 ID (可選)
            message_log_channel: 訊息紀錄頻道 ID (可選)
            anti_dive_channel: 反潛水頻道 ID (可選)
        若該 guild_id 已存在則更新，否則新增。
        """
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
        """
        取得指定伺服器的設定。
        參數:
            guild_id: 伺服器 ID
        回傳:
            aiosqlite.Row 或 None。
        """
        await self.connect()
        cursor = await self.conn.execute(
            "SELECT * FROM server_settings WHERE guild_id = ?", (guild_id,)
        )
        return await cursor.fetchone()

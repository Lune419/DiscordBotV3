import os
import aiosqlite
import logging
import time
from typing import Optional

log = logging.getLogger(__name__)

class TempVoiceDatabase:
    def __init__(self, dbpath) -> None:
        self.dbpath = os.getenv("VOICEDATABASE", dbpath)
        self.conn: Optional[aiosqlite.Connection] = None
        
    async def connect(self):
        if self.conn is None:
            self.conn = await aiosqlite.connect(self.dbpath)
            self.conn.row_factory = aiosqlite.Row
            
    async def initdb(self):
        await self.connect()
        
        # 創建母頻道表
        await self.conn.execute('''
        CREATE TABLE IF NOT EXISTS parent_channels (
            guild_id INTEGER NOT NULL,
            channel_id INTEGER PRIMARY KEY NOT NULL,
            category_id INTEGER,
            template TEXT,
            created_at INTEGER DEFAULT (unixepoch()),
            UNIQUE(guild_id, channel_id)
        )
        ''')
        
        # 為母頻道表創建索引
        await self.conn.execute('CREATE INDEX IF NOT EXISTS idx_parent_guild ON parent_channels(guild_id)')
        
        # 創建母頻道身分組關聯表 (多對多關係)
        await self.conn.execute('''
        CREATE TABLE IF NOT EXISTS parent_channel_roles (
            channel_id INTEGER NOT NULL,
            role_id INTEGER NOT NULL,
            PRIMARY KEY (channel_id, role_id),
            FOREIGN KEY (channel_id) REFERENCES parent_channels(channel_id) ON DELETE CASCADE
        )
        ''')
        
        # 為母頻道身分組表創建索引
        await self.conn.execute('CREATE INDEX IF NOT EXISTS idx_parent_roles_channel ON parent_channel_roles(channel_id)')
        
        # 創建子頻道表
        await self.conn.execute('''
        CREATE TABLE IF NOT EXISTS child_channels (
            guild_id INTEGER NOT NULL,
            parent_channel_id INTEGER NOT NULL,
            channel_id INTEGER PRIMARY KEY NOT NULL,
            owner_id INTEGER NOT NULL,
            control_message_id INTEGER,
            created_at INTEGER DEFAULT (unixepoch()),
            UNIQUE(guild_id, channel_id),
            FOREIGN KEY (parent_channel_id) REFERENCES parent_channels(channel_id) ON DELETE CASCADE
        )
        ''')
        
        # 為子頻道表創建索引
        await self.conn.execute('CREATE INDEX IF NOT EXISTS idx_child_guild ON child_channels(guild_id)')
        await self.conn.execute('CREATE INDEX IF NOT EXISTS idx_child_parent ON child_channels(parent_channel_id)')
        await self.conn.execute('CREATE INDEX IF NOT EXISTS idx_child_owner ON child_channels(owner_id)')
        
        # 提交更改
        await self.conn.commit()
        
        # 執行數據遷移（將舊的時間戳格式轉換為 UNIX 時間戳）
        await self._migrate_timestamps()
        
        log.info("已初始化臨時語音頻道資料庫")
        
    async def _migrate_timestamps(self):
        """遷移舊的時間戳格式為 UNIX 時間戳"""
        try:
            # 檢查是否需要遷移子頻道表
            async with self.conn.execute("SELECT created_at FROM child_channels LIMIT 1") as cursor:
                row = await cursor.fetchone()
                if row and row['created_at']:
                    # 檢查是否為字符串格式（需要遷移）
                    created_at = row['created_at']
                    if isinstance(created_at, str) and not created_at.isdigit():
                        log.info("開始遷移子頻道時間戳...")
                        # 更新所有字符串格式的時間戳
                        await self.conn.execute("""
                            UPDATE child_channels 
                            SET created_at = cast(unixepoch(created_at) as integer)
                            WHERE typeof(created_at) = 'text' AND created_at NOT GLOB '[0-9]*'
                        """)
                        
                        # 處理無效的時間戳，設為當前時間
                        await self.conn.execute("""
                            UPDATE child_channels 
                            SET created_at = cast(unixepoch() as integer)
                            WHERE created_at IS NULL OR created_at = 0
                        """)
                        
                        await self.conn.commit()
                        log.info("子頻道時間戳遷移完成")
                        
            # 檢查是否需要遷移母頻道表
            async with self.conn.execute("SELECT created_at FROM parent_channels LIMIT 1") as cursor:
                row = await cursor.fetchone()
                if row and row['created_at']:
                    created_at = row['created_at']
                    if isinstance(created_at, str) and not created_at.isdigit():
                        log.info("開始遷移母頻道時間戳...")
                        # 更新所有字符串格式的時間戳
                        await self.conn.execute("""
                            UPDATE parent_channels 
                            SET created_at = cast(unixepoch(created_at) as integer)
                            WHERE typeof(created_at) = 'text' AND created_at NOT GLOB '[0-9]*'
                        """)
                        
                        # 處理無效的時間戳，設為當前時間
                        await self.conn.execute("""
                            UPDATE parent_channels 
                            SET created_at = cast(unixepoch() as integer)
                            WHERE created_at IS NULL OR created_at = 0
                        """)
                        
                        await self.conn.commit()
                        log.info("母頻道時間戳遷移完成")
                        
        except Exception as e:
            log.warning(f"時間戳遷移過程中發生錯誤: {e}")
            # 即使遷移失敗，也不影響正常功能
        
    async def close(self):
        """關閉資料庫連線"""
        if self.conn:
            await self.conn.close()
            self.conn = None
            
    # 母頻道相關操作
    
    async def add_parent_channel(self, guild_id: int, channel_id: int, category_id: Optional[int] = None, template: Optional[str] = None):
        """新增一個母頻道"""
        await self.connect()
        
        query = '''
        INSERT INTO parent_channels (guild_id, channel_id, category_id, template)
        VALUES (?, ?, ?, ?)
        '''
        await self.conn.execute(query, (guild_id, channel_id, category_id, template))
        await self.conn.commit()
        
    async def get_parent_channel(self, channel_id: int):
        """根據頻道ID獲取母頻道信息"""
        await self.connect()
        
        query = 'SELECT * FROM parent_channels WHERE channel_id = ?'
        async with self.conn.execute(query, (channel_id,)) as cursor:
            return await cursor.fetchone()
    
    async def get_parent_channels_by_guild(self, guild_id: int):
        """獲取伺服器的所有母頻道"""
        await self.connect()
        
        query = 'SELECT * FROM parent_channels WHERE guild_id = ?'
        async with self.conn.execute(query, (guild_id,)) as cursor:
            return await cursor.fetchall()
            
    async def update_parent_channel(self, channel_id: int, category_id: Optional[int] = None, template: Optional[str] = None):
        """更新母頻道信息"""
        await self.connect()
        
        updates = []
        params = []
        
        if category_id is not None:
            updates.append('category_id = ?')
            params.append(category_id)
        
        if template is not None:
            updates.append('template = ?')
            params.append(template)
            
        if not updates:
            return
            
        query = f'''
        UPDATE parent_channels
        SET {', '.join(updates)}
        WHERE channel_id = ?
        '''
        params.append(channel_id)
        
        await self.conn.execute(query, params)
        await self.conn.commit()
        
    async def delete_parent_channel(self, channel_id: int):
        """刪除一個母頻道及其所有相關數據"""
        await self.connect()
        
        # 由於使用了ON DELETE CASCADE，刪除母頻道時會自動刪除相關的身分組和子頻道記錄
        query = 'DELETE FROM parent_channels WHERE channel_id = ?'
        await self.conn.execute(query, (channel_id,))
        await self.conn.commit()
        
    # 母頻道身分組相關操作
    
    async def add_parent_channel_role(self, channel_id: int, role_id: int):
        """為母頻道添加一個默認身分組"""
        await self.connect()
        
        query = '''
        INSERT OR IGNORE INTO parent_channel_roles (channel_id, role_id)
        VALUES (?, ?)
        '''
        await self.conn.execute(query, (channel_id, role_id))
        await self.conn.commit()
        
    async def remove_parent_channel_role(self, channel_id: int, role_id: int):
        """從母頻道移除一個默認身分組"""
        await self.connect()
        
        query = '''
        DELETE FROM parent_channel_roles
        WHERE channel_id = ? AND role_id = ?
        '''
        await self.conn.execute(query, (channel_id, role_id))
        await self.conn.commit()
        
    async def get_parent_channel_roles(self, channel_id: int):
        """獲取母頻道的所有默認身分組"""
        await self.connect()
        
        query = 'SELECT role_id FROM parent_channel_roles WHERE channel_id = ?'
        async with self.conn.execute(query, (channel_id,)) as cursor:
            rows = await cursor.fetchall()
            return [row['role_id'] for row in rows]
    
    # 子頻道相關操作
    
    async def add_child_channel(self, guild_id: int, parent_channel_id: int, channel_id: int, 
                               owner_id: int, control_message_id: Optional[int] = None):
        """新增一個子頻道"""
        await self.connect()
        
        # 使用當前的 UNIX 時間戳
        current_timestamp = int(time.time())
        
        query = '''
        INSERT INTO child_channels 
        (guild_id, parent_channel_id, channel_id, owner_id, control_message_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        '''
        await self.conn.execute(query, (guild_id, parent_channel_id, channel_id, owner_id, control_message_id, current_timestamp))
        await self.conn.commit()
        
    async def get_child_channel(self, channel_id: int):
        """根據頻道ID獲取子頻道信息"""
        await self.connect()
        
        query = 'SELECT * FROM child_channels WHERE channel_id = ?'
        async with self.conn.execute(query, (channel_id,)) as cursor:
            return await cursor.fetchone()
    
    async def get_child_channels_by_parent(self, parent_channel_id: int):
        """獲取指定母頻道的所有子頻道"""
        await self.connect()
        
        query = 'SELECT * FROM child_channels WHERE parent_channel_id = ?'
        async with self.conn.execute(query, (parent_channel_id,)) as cursor:
            return await cursor.fetchall()
    
    async def get_child_channels_by_owner(self, owner_id: int):
        """獲取用戶所擁有的所有子頻道"""
        await self.connect()
        
        query = 'SELECT * FROM child_channels WHERE owner_id = ?'
        async with self.conn.execute(query, (owner_id,)) as cursor:
            return await cursor.fetchall()
            
    async def get_child_channels_by_guild(self, guild_id: int):
        """獲取伺服器的所有子頻道"""
        await self.connect()
        
        query = 'SELECT * FROM child_channels WHERE guild_id = ?'
        async with self.conn.execute(query, (guild_id,)) as cursor:
            return await cursor.fetchall()
    
    async def update_child_channel_owner(self, channel_id: int, new_owner_id: int):
        """更新子頻道擁有者"""
        await self.connect()
        
        query = 'UPDATE child_channels SET owner_id = ? WHERE channel_id = ?'
        await self.conn.execute(query, (new_owner_id, channel_id))
        await self.conn.commit()
        
    async def update_control_message(self, channel_id: int, message_id: int):
        """更新子頻道的控制面板訊息ID"""
        await self.connect()
        
        query = 'UPDATE child_channels SET control_message_id = ? WHERE channel_id = ?'
        await self.conn.execute(query, (message_id, channel_id))
        await self.conn.commit()
        
    async def delete_child_channel(self, channel_id: int):
        """刪除一個子頻道"""
        await self.connect()
        
        query = 'DELETE FROM child_channels WHERE channel_id = ?'
        await self.conn.execute(query, (channel_id,))
        await self.conn.commit()
        
    # 進階查詢操作
    
    async def get_child_channel_with_parent_info(self, channel_id: int):
        """獲取子頻道信息，包含母頻道信息"""
        await self.connect()
        
        query = '''
        SELECT c.*, p.template, p.category_id
        FROM child_channels c
        JOIN parent_channels p ON c.parent_channel_id = p.channel_id
        WHERE c.channel_id = ?
        '''
        async with self.conn.execute(query, (channel_id,)) as cursor:
            return await cursor.fetchone()
            
    async def is_parent_channel(self, channel_id: int) -> bool:
        """檢查頻道是否為母頻道"""
        await self.connect()
        
        query = 'SELECT 1 FROM parent_channels WHERE channel_id = ?'
        async with self.conn.execute(query, (channel_id,)) as cursor:
            result = await cursor.fetchone()
            return result is not None
            
    async def is_child_channel(self, channel_id: int) -> bool:
        """檢查頻道是否為子頻道"""
        await self.connect()
        
        query = 'SELECT 1 FROM child_channels WHERE channel_id = ?'
        async with self.conn.execute(query, (channel_id,)) as cursor:
            result = await cursor.fetchone()
            return result is not None
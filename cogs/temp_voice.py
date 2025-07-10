import re
import discord
import os
from discord.ext import commands
from discord import app_commands
from typing import Optional
import aiosqlite
import asyncio
import json
import logging

log = logging.getLogger(__name__)

with open("config.json", "r", encoding="utf-8") as f:
    cfg = json.load(f)


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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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
        
        log.info("已初始化臨時語音頻道資料庫")
        
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
        
        query = '''
        INSERT INTO child_channels 
        (guild_id, parent_channel_id, channel_id, owner_id, control_message_id)
        VALUES (?, ?, ?, ?, ?)
        '''
        await self.conn.execute(query, (guild_id, parent_channel_id, channel_id, owner_id, control_message_id))
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
        
class TemplateFormatter:
    """處理語音頻道名稱模板的格式化"""
    
    @staticmethod
    def format_template(template: str, member: discord.Member, **extra_vars) -> str:
        """
        格式化頻道名稱模板
        
        可用的預設變數:
        - {user}: 使用者的名稱 (不含標籤)
        - {user_displayname}: 使用者的顯示名稱
        
        額外變數可透過 extra_vars 參數傳入
        """
        if not template:
            return f"{member.display_name} 的頻道"
            
        # 準備基本變數
        variables = {
            "user": member.name,
            "user_displayname": member.display_name
        }
        
        # 添加額外變數
        variables.update(extra_vars)
        
        # 使用正則表達式尋找並替換所有變數
        def replace_var(match):
            var_name = match.group(1)
            if var_name in variables:
                return str(variables[var_name])
            return match.group(0)  # 如果找不到變數，保留原始文本
            
        # 替換變數
        result = re.sub(r'\{([a-zA-Z0-9_]+)\}', replace_var, template)
        
        # 確保頻道名稱不超過100個字元 (Discord 限制)
        if len(result) > 100:
            result = result[:97] + "..."
            
        return result
    
class TempVoice(commands.Cog):
    """臨時語音頻道"""
    def __init__(self, bot: commands.Bot, db_path):
        self.bot = bot
        self.TemplateFormatter = TemplateFormatter
        self.TempVoiceDatabase = TempVoiceDatabase(db_path)
        
    async def create_child_channel(self, *, parent_channel: discord.VoiceChannel, member: discord.Member) -> discord.VoiceChannel:
        """創建一個新的子頻道"""
        parent_channel_info = await self.TempVoiceDatabase.get_parent_channel(parent_channel.id)
        if not parent_channel_info:
            pass
        
        template = parent_channel_info['template'] if parent_channel_info['template'] else None
        category_id = parent_channel_info['category_id'] if parent_channel_info['category_id'] else None
        
        # 獲取類別對象
        category = None
        if category_id:
            category = parent_channel.guild.get_channel(category_id)
        
        # 格式化頻道名稱
        channel_name = self.TemplateFormatter.format_template(template, member)
        
        # 複製母頻道的權限設定
        overwrites = parent_channel.overwrites.copy()
        
        # 給頻道創建者添加管理權限
        if member not in overwrites:
            overwrites[member] = discord.PermissionOverwrite()
        
        overwrites[member].connect = True
        overwrites[member].mute_members = True
        overwrites[member].deafen_members = True
        overwrites[member].move_members = True
        overwrites[member].manage_channels = True
        
        # 創建新頻道
        new_channel = await parent_channel.guild.create_voice_channel(
            name=channel_name,
            category=category or parent_channel.category,  # 如果沒有指定類別，使用與母頻道相同的類別
            overwrites=overwrites,
            bitrate=parent_channel.bitrate,
            user_limit=parent_channel.user_limit,
            rtc_region=parent_channel.rtc_region,
            video_quality_mode=parent_channel.video_quality_mode,
        )
        
        # 將子頻道添加到資料庫
        await self.TempVoiceDatabase.add_child_channel(
            guild_id=parent_channel.guild.id,
            parent_channel_id=parent_channel.id,
            channel_id=new_channel.id,
            owner_id=member.id
        )
        
        # 如果用戶當前在母頻道中，將他移動到新建立的子頻道
        if member.voice and member.voice.channel and member.voice.channel.id == parent_channel.id:
            try:
                await member.move_to(new_channel)
            except discord.HTTPException:
                # 如果移動失敗，記錄但不中斷流程
                log.warning(f"無法將用戶 {member.display_name} 移動到新建立的子頻道")
        
        return new_channel
    
    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        """監聽語音狀態更新事件"""
        # 如果用戶進入了母頻道，則創建子頻道
        if after.channel and before.channel != after.channel:
            await self.create_child_channel(parent_channel=after.channel, member=member)
            
    
async def setup(bot):
    """載入擴充"""
    # 設定資料庫路徑
    db_path = os.getenv("VOICEDATABASE", "temp_voice.db")
    
    # 建立資料庫連接並初始化
    db = TempVoiceDatabase(db_path)
    await db.initdb()
    
    # 將 cog 添加到機器人
    await bot.add_cog(TempVoice(bot, db_path))
    log.info("已載入臨時語音頻道擴充")


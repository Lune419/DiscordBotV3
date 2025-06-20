import json
import logging

import discord
from discord import app_commands, utils
from discord.ext import commands

from utils.time_utils import now_with_unix

with open("config.json", "r", encoding="utf-8") as fp:
    cfg = json.load(fp)

log = logging.getLogger(__name__)

class VoiceLogger(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db_manager = bot.db_manager
        self.guild_id = cfg["guild_id"]
        self.timezone = cfg["timezone"]
        

    @commands.Cog.listener()
    async def on_voice_state_update(self,
                                    member: discord.Member,
                                    before: discord.VoiceState,
                                    after: discord.VoiceState,
                                    ) -> None:
        """
        當成員的語音狀態更新時觸發。
        記錄成員進入或離開語音頻道的時間。
        """
        
        # 忽略機器人
        if member.bot:
            return
        
        now, ts = now_with_unix(self.timezone)
        # 加入語音頻道
        if before.channel is None and after.channel is not None:
            return
        # 離開語音頻道
        elif before.channel is not None and after.channel is None:
            return
        # 切換語音頻道
        elif before.channel and after.channel and before.channel.id != after.channel.id:
            return
        # 靜音
        # 被靜音
        # 拒聽
        # 被拒聽
        # 取消靜音
        # 被取消靜音
        # 取消拒聽
        # 被取消拒聽
        # 開啟直播
        # 關閉直播
        # 開鏡頭
        # 關鏡頭
        


    
    # 監聽語音頻道創建事件
    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.VoiceChannel) -> None:
        """
        當語音頻道被創建時觸發。
        在頻道被創建時將其加入資料庫。
        """
        if not isinstance(channel, discord.VoiceChannel):
            return
        
        now, ts = now_with_unix(self.timezone)
        
        try:
            await self.db_manager.add_voice_event(
                guild_id = channel.guild.id,
                channel_id = channel.id,
                channel_name = channel.name,
                timestamp = ts,
                event_type = "channel_create",
            )
        except Exception as _:
            log.exception(f"記錄語音頻道創建事件時發生錯誤: {channel.name} ({channel.id})")
            
    # 監聽語音頻道刪除事件
    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.VoiceChannel) -> None:
        """
        當語音頻道被刪除時觸發。
        在頻道被刪除時將其將入資料庫。
        """
        if not isinstance(channel, discord.VoiceChannel):
            return
        
        now, ts = now_with_unix(self.timezone)
        
        try:
            await self.db_manager.add_voice_event(
                guild_id = channel.guild.id if channel.guild else channel.guild_id,
                channel_id = channel.id,
                channel_name = channel.name,
                timestamp = ts,
                event_type = "channel_delete",
            )
        except Exception as _:
            log.exception(f"記錄語音頻道刪除事件時發生錯誤: {channel.name} ({channel.id})")
    
import json
import logging
from typing import List

import discord
from discord import app_commands
from discord.ext import commands

from utils.time_utils import now_with_unix


with open("config.json", "r", encoding="utf-8") as fp:
    cfg = json.load(fp)
    
log = logging.getLogger(__name__)


class ServerSetting(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_manager = bot.db_manager
        self.guild_id = cfg["guild_id"]
        self.timezone = cfg["timezone"]
        
    def get_log_description(self, type: str) -> str:
        
        descriptions = {
            "notify_channel": "重大通知",
            "voice_log_channel": "語音紀錄頻道",
            "member_log_channel": "成員頻道紀錄",
            "message_log_channel": "訊息紀錄頻道",
            "anti_dive_channel": "防潛水頻道"
        }
        return descriptions.get(type, "未知日誌類型")
        
    @app_commands.guilds(discord.Object(id=cfg["guild_id"]))
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.command(name="set_log_channel", description="設定日誌頻道")
    async def set_log_channel(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        type: str, 
    ):
        
        channel_type = type
        
        # 設定日誌頻道到資料庫
        # 使用 set_settings 方法，只更新特定類型的頻道
        kwargs = {channel_type: channel.id, "guild_id": self.guild_id}
        await self.db_manager.set_settings(**kwargs)
        
        # 取得友善的頻道類型描述
        type_description = self.get_log_description(channel_type)
        
        now, _ = now_with_unix(self.timezone)
        
        # 回應互動
        embed = discord.Embed(
            title="日誌頻道設定",
            description=f"已將 **{type_description}** 設定為 {channel.mention}",
            color=discord.Color.green(),
            timestamp=now
        )
        
        
        await interaction.response.send_message(embed=embed)
        
    @set_log_channel.autocomplete("type")
    async def type_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str
    ) -> List[app_commands.Choice[str]]:
        options = [
            app_commands.Choice(name="重大通知", value="notify_channel"),
            app_commands.Choice(name="語音紀錄頻道", value="voice_log_channel"),
            app_commands.Choice(name="成員頻道紀錄", value="member_log_channel"),
            app_commands.Choice(name="訊息紀錄頻道", value="message_log_channel"),
            app_commands.Choice(name="防潛水頻道", value="anti_dive_channel"),
        ]
        
        # 如果使用者輸入了搜尋文字，則過濾選項
        if current:
            filtered_options = [
                option for option in options 
                if current.lower() in option.name.lower() or current.lower() in option.value.lower()
            ]
            return filtered_options
        
        # 如果沒有輸入，返回所有選項
        return options

async def setup(bot):
    await bot.add_cog(ServerSetting(bot))
    log.info("ServerSetting 擴充已載入")
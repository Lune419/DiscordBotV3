import json
import logging
import datetime
from typing import List

import discord
from discord import app_commands
from discord.ext import commands

from utils.time_utils import now_with_unix

with open("config.json", "r", encoding="utf-8") as fp:
    cfg = json.load(fp)
    
log = logging.getLogger(__name__)

class MessageLogger(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_manager = bot.db_manager
        self.guild_id = cfg["guild_id"]
        self.timezone = cfg["timezone"]
        
    async def get_log_channel(self, guild_id: int) -> discord.TextChannel | None:
        """獲取日誌頻道"""
        settings = await self.bot.db_manager.get_settings(guild_id)
        if not settings or settings["message_log_channel"] is None:
            return None
        
        log_channel = self.bot.get_channel(settings["message_log_channel"])
        if not log_channel or not isinstance(log_channel, discord.TextChannel):
            return None
        
        return log_channel

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if before.author.bot:
            return
        
        if before.content == after.content:
            return
        
        log_channel = await self.get_log_channel(before.guild.id)
        
        now, ts = now_with_unix(self.timezone)
        
        embed = discord.Embed(
            title="訊息編輯紀錄",
            color=discord.Color.yellow(),
            description=f"{before.author.mention} (`{before.author.id}`) 編輯了訊息\n[跳轉到訊息]({after.jump_url})",
            timestamp=now
        )
        embed.add_field(
            name="原始訊息",
            value=before.content[:1024],
            inline=False
        )
        embed.add_field(
            name="新訊息",
            value=after.content[:1024],
            inline=False
        )
        embed.set_author(name=before.author.display_name, icon_url=before.author.display_avatar.url)
        await log_channel.send(embed=embed)
        
    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
    
        if message.author.bot:
            return
        
        log_channel = await self.get_log_channel(message.guild.id)
        if not log_channel:
            return
            
        now, ts = now_with_unix(self.timezone)
        
        embed = discord.Embed(
            title="訊息刪除紀錄",
            color=discord.Color.red(),
            description=f"{message.author.mention} (`{message.author.id}`) 的訊息被刪除",
            timestamp=now
        )
        if message.content:
            embed.add_field(
                name="原始訊息",
                value=message.content[:1024],
                inline=False
            )
        
        if message.attachments:
            attachments = "\n".join([f"- {attachment.filename}" for attachment in message.attachments])
            embed.add_field(
                name="附件",
                value=attachments,
                inline=False
            )
            
        # 獲取附近訊息的連結 - 只找最近的一條
        channel = message.channel
        try:
            # 嘗試獲取被刪除訊息之前的一條非機器人訊息
            nearby_message = None
            async for msg in channel.history(limit=10, before=message.created_at):
                if not msg.author.bot:  # 排除機器人訊息
                    nearby_message = msg
                    break
                    
            if nearby_message:
                # 顯示簡短的訊息預覽
                link = f"[跳至附近訊息]({nearby_message.jump_url})"
                
                embed.add_field(
                    name="附近訊息連結",
                    value=link,
                    inline=False
                )
            else:
                embed.add_field(
                    name="附近訊息連結",
                    value="無法獲取附近訊息",
                    inline=False
                )
        except Exception as e:
            log.error(f"獲取附近訊息時發生錯誤: {e}")
            embed.add_field(
                name="附近訊息連結",
                value=f"獲取附近訊息時出錯: {e}",
                inline=False
            )
            
        # 添加頻道資訊
        embed.add_field(
            name="頻道資訊",
            value=f"{message.channel.mention} (`{message.channel.id}`)",
            inline=False
        )
        
        embed.set_author(name=message.author.display_name, icon_url=message.author.display_avatar.url)
        await log_channel.send(embed=embed)
        
        
async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MessageLogger(bot))
    log.info("MessageLogger 擴充已載入")

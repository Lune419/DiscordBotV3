import json
import logging

import discord
from discord import app_commands, utils
from discord.ext import commands

from utils.time_utils import now_with_unix

with open("config.json", "r", encoding="utf-8") as fp:
    cfg = json.load(fp)

log = logging.getLogger(__name__)

class _VoiceLoggerSendToChannel():
    def __init__(self, bot: commands.Bot,):
        self.bot = bot
        self.db_manager = bot.db_manager
        self.guild_id = cfg["guild_id"]
        self.timezone = cfg["timezone"]
        
    def get_event_description(self, event_type: str) -> str:
        """根據事件類型返回描述"""
        descriptions = {
            "join": "加入語音頻道",
            "leave": "離開語音頻道",
            "self_mute": "靜音",
            "self_unmute": "取消靜音",
            "server_mute": "被伺服器靜音",
            "server_unmute": "被伺服器取消靜音",
            "self_deaf": "拒聽",
            "self_undeaf": "取消拒聽",
            "server_deaf": "被伺服器拒聽",
            "server_undeaf": "被伺服器取消拒聽",
            "stream_on": "開始直播",
            "stream_off": "停止直播",
            "video_on": "開啟鏡頭",
            "video_off": "關閉鏡頭",
            "channel_create": "創建語音頻道",
            "channel_delete": "刪除語音頻道"
        }
        return descriptions.get(event_type, event_type)
    
    def get_embed_color(self, event_type: str) -> discord.Color:
        """根據事件類型返回顏色"""
        colors = {
            "join": 0x00ff00,  # 綠色
            "leave": 0xff0000,  # 紅色
            "self_mute": 0xffa500,  # 橙色
            "self_unmute": 0x00ff00,  # 綠色
            "server_mute": 0xff0000,  # 紅色
            "server_unmute": 0x00ff00,  # 綠色
            "self_deaf": 0xffa500,  # 橙色
            "self_undeaf": 0x00ff00,  # 綠色
            "server_deaf": 0xff0000,  # 紅色
            "server_undeaf": 0x00ff00,  # 綠色
            "stream_on": 0x9932cc,  # 紫色
            "stream_off": 0x1e90ff,  # 藍色
            "video_on": 0x9932cc,  # 紫色
            "video_off": 0x1e90ff,  # 藍色
            "channel_create": 0xff8c00,  # 黃色
            "channel_delete": 0xff4500,  # 橙紅色
        }
        return colors.get(event_type, discord.Color.default())
    
    async def get_log_channel(self, guild_id: int) -> discord.TextChannel | None:
        """獲取日誌頻道"""
        settings = await self.bot.db_manager.get_settings(guild_id)
        if not settings or not settings.get("voice_log_channel"):
            return None
        
        log_channel = self.bot.get_channel(settings["voice_log_channel"])
        if not log_channel or not isinstance(log_channel, discord.TextChannel):
            return None
        
        return log_channel
    
    async def send_voice_event(self, member: discord.Member, channel: discord.VoiceChannel, event_type: str) -> None:
        try:
            log_channel = await self.get_log_channel(channel.guild.id)
            if not log_channel:
                return
            if not channel:
                return
            
            now, ts = now_with_unix(self.timezone)

            if event_type in ["join", "leave"]:
                embed = discord.Embed(
                    title="語音頻道紀錄",
                    description=f"{self.get_event_description(event_type)} {channel.mention}({channel.name})",
                    color=self.get_embed_color(event_type),
                    timestamp=now
                )
                embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
            elif event_type in ["channel_create", "channel_delete"]:
                embed = discord.Embed(
                    title="語音頻道創建刪除紀錄",
                    description=f"{self.get_event_description(event_type)} {channel.name}({channel.id})",
                    color=self.get_embed_color(event_type),
                    timestamp=now
                )
                embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
            else:
                embed = discord.Embed(
                    title="語音頻道紀錄",
                    description=f"在{channel.mention}({channel.name})中{self.get_event_description(event_type)}",
                    color=self.get_embed_color(event_type),
                    timestamp=now
                )
                embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
        
            await log_channel.send(embed=embed)
        except Exception as _:
            log.exception(f"發送語音事件到頻道時發生錯誤: {member.name} ({member.id}) 在 {channel.name} ({channel.id})")
                 

class VoiceLogger(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db_manager = bot.db_manager
        self.guild_id = cfg["guild_id"]
        self.timezone = cfg["timezone"]
        self._voice_sender = _VoiceLoggerSendToChannel(bot)
        
    async def log_voice_event(self, member: discord.Member, channel: discord.VoiceChannel, event_type: str) -> None:
        """紀錄語音事件到資料庫"""
        now, ts = now_with_unix(self.timezone)
        try:
            await self.db_manager.add_voice_event(
                guild_id = channel.guild.id if channel.guild else channel.guild_id,
                user_id = member.id,
                channel_id = channel.id,
                channel_name = channel.name,
                timestamp = ts,
                event_type = event_type,
            )
        except Exception as _:
            log.exception(f"記錄語音事件時發生錯誤: {member.name} ({member.id}) 在 {channel.name} ({channel.id})")
            

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
            await self.log_voice_event(member, after.channel, "join")
            await self._voice_sender.send_voice_event(
                member, after.channel, "join"
            )
        # 離開語音頻道
        elif before.channel is not None and after.channel is None:
            await self.log_voice_event(member, before.channel, "leave")
            await self._voice_sender.send_voice_event(
                member, before.channel, "leave"
            )
        # 切換語音頻道
        elif before.channel and after.channel and before.channel.id != after.channel.id:
            await self.log_voice_event(member, before.channel, "leave")
            await self.log_voice_event(member, after.channel, "join")
            log_channel = await self._voice_sender.get_log_channel(member.guild.id)
            if log_channel:
                embed = discord.Embed(
                    title="語音頻道紀錄",
                    description=f"從{before.channel.mention}({before.channel.name}) 移動到到 {after.channel.mention}({after.channel.name})",
                    color=discord.Color.blue(),
                    timestamp=now
                )
                embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
                await log_channel.send(embed=embed)
        # 靜音
        if before.self_mute != after.self_mute:
            if after.self_mute:
                await self.log_voice_event(member, after.channel, "self_mute")
                await self._voice_sender.send_voice_event(
                    member, after.channel, "self_mute"
                )
            else:
                await self.log_voice_event(member, after.channel, "self_unmute")
                await self._voice_sender.send_voice_event(
                    member, after.channel, "self_unmute"
                )
        # 伺服器靜音
        if before.mute != after.mute:
            if after.mute:
                await self.log_voice_event(member, after.channel, "server_mute")
                await self._voice_sender.send_voice_event(
                    member, after.channel, "server_mute"
                )
            else:
                await self.log_voice_event(member, after.channel, "server_unmute")
                await self._voice_sender.send_voice_event(
                    member, after.channel, "server_unmute"
                )
        # 拒聽
        if before.self_deaf != after.self_deaf:
            if after.self_deaf:
                await self.log_voice_event(member, after.channel, "self_deaf")
                await self._voice_sender.send_voice_event(
                    member, after.channel, "self_deaf"
                )
            else:
                await self.log_voice_event(member, after.channel, "self_undeaf")
                await self._voice_sender.send_voice_event(
                    member, after.channel, "self_undeaf"
                )
        # 伺服器拒聽
        if before.deaf != after.deaf:
            if after.deaf:
                await self.log_voice_event(member, after.channel, "server_deaf")
                await self._voice_sender.send_voice_event(
                    member, after.channel, "server_deaf"
                )
            else:
                await self.log_voice_event(member, after.channel, "server_undeaf")
                await self._voice_sender.send_voice_event(
                    member, after.channel, "server_undeaf"
                )
        # 直播狀態        
        if before.self_stream != after.self_stream:
            if after.self_stream:
                await self.log_voice_event(member, after.channel, "stream_on")
                await self._voice_sender.send_voice_event(
                    member, after.channel, "stream_on"
                )
            else:
                await self.log_voice_event(member, after.channel, "stream_off")
                await self._voice_sender.send_voice_event(
                    member, after.channel, "stream_off"
                )
        # 鏡頭狀態        
        if before.self_video != after.self_video:
            if after.self_video:
                await self.log_voice_event(member, after.channel, "video_on")
                await self._voice_sender.send_voice_event(
                    member, after.channel, "video_on"
                )
            else:
                await self.log_voice_event(member, after.channel, "video_off")
                await self._voice_sender.send_voice_event(
                    member, after.channel, "video_off"
                )


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
                user_id = 12315,
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
        在頻道被刪除時將其計入資料庫。
        """
        if not isinstance(channel, discord.VoiceChannel):
            return
        
        now, ts = now_with_unix(self.timezone)
        
        try:
            await self.db_manager.add_voice_event(
                guild_id = channel.guild.id if channel.guild else channel.guild_id,
                user_id = 12315,
                channel_id = channel.id,
                channel_name = channel.name,
                timestamp = ts,
                event_type = "channel_delete",
            )
        except Exception as _:
            log.exception(f"記錄語音頻道刪除事件時發生錯誤: {channel.name} ({channel.id})")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VoiceLogger(bot))
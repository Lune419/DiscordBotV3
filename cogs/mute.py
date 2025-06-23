import json
import logging
from datetime import timedelta
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import List

import discord
from discord import app_commands, utils
from discord.ext import commands
from utils.Paginator import Paginator
from utils.TimeFormat import format_seconds
from utils.time_utils import now_with_unix




with open("config.json", "r", encoding="utf-8") as fp:
    cfg = json.load(fp)

log = logging.getLogger(__name__)



class Mute(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.DBManager = bot.db_manager
        self.timezone = cfg["timezone"]


    @app_commands.guilds(discord.Object(id=cfg["guild_id"]))
    @app_commands.command(name="mute", description="禁言指定成員")
    @app_commands.describe(
        user="要禁言的成員",
        days="禁言幾日",
        hours="禁言幾小時",
        minutes="禁言幾分鐘",
        reason="禁言原因",
    )
    @app_commands.checks.has_permissions(manage_messages=True)
    async def mute(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        days: int = 0,
        hours: int = 0,
        minutes: int = 0,
        reason: str = None
    ):
        """ 禁言 """
        try:
            _, UNIXNOW = now_with_unix(self.timezone)
            durations = timedelta(days=days, hours=hours, minutes=minutes)
            durations_seconds = durations.total_seconds()
            durations_str = format_seconds(durations_seconds)

            if user.id == interaction.user.id:
                await interaction.response.send_message(
                    "你不能禁言自己。", ephemeral=True
                )
                return

            if user.bot:
                await interaction.response.send_message(
                    "你不能禁言機器人。", ephemeral=True
                )
                return

            if durations_seconds <= 0:
                embed = discord.Embed(
                    title       = f"禁言{user.display_name}失敗!!",
                    description = "禁言時間必須為正數!", 
                    color       = discord.Color.orange()
                )
                await interaction.response.send_message(embed=embed, ephemeral=False)
                return

            else:
                await user.timeout(durations, reason=reason)

                await self.DBManager.add_punishment(
                    guild_id=interaction.guild.id,
                    user_id=user.id,
                    punished_at=UNIXNOW,
                    ptype="mute",
                    duration=durations_seconds,
                    reason=reason,
                    admin_id=interaction.user.id,
                )

                embed = discord.Embed(
                    title = f"禁言成功!!", 
                    description = f"{interaction.user.mention} 將 {user.mention} 禁言 {durations_str}\n原因: {reason}",
                    color = discord.Color.green()
                )                
            await interaction.response.send_message(embed=embed, ephemeral=False) 

        except Exception as e:
            log.exception("指令執行時發生錯誤:")
            embed = discord.Embed(title= f"禁言 {user.display_name} 失敗!!", description= f"執行時失敗:{e}", color=discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)



    @app_commands.guilds(discord.Object(id=cfg["guild_id"]))
    @app_commands.command(name="unmute", description="解除禁言指定成員")
    @app_commands.describe(
        user="要解除禁言的成員",
        reason="解除禁言原因"
    )
    @app_commands.checks.has_permissions(manage_messages=True)
    async def unmute(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        reason: str = None
    ):
        """ 解除禁言 """
        try:
            _, UNIXNOW = now_with_unix(self.timezone)

            if not user.timed_out_until:
                embed = discord.Embed(
                    title = f"{user.display_name} 沒有被禁言!!", 
                    color = discord.Color.orange()
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)

            else:
                await user.timeout(None, reason=reason)

                await self.DBManager.add_punishment(
                    guild_id=interaction.guild.id,
                    user_id=user.id,
                    punished_at=UNIXNOW,
                    ptype="unmute",
                    reason=reason,
                    admin_id=interaction.user.id,
                )

                embed = discord.Embed(
                    title = f"解除禁言成功!!", 
                    description = f"{interaction.user.mention} 解除了 {user.mention} 的禁言\n原因: {reason}",
                    color = discord.Color.green()
                )                
                await interaction.response.send_message(embed=embed, ephemeral=False)

        except Exception as e:
            log.exception("指令執行時發生錯誤:")
            embed = discord.Embed(title= f"解除禁言 {user.display_name} 失敗!!", description= f"執行時失敗:{e}", color= discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)


    @app_commands.guilds(discord.Object(id=cfg["guild_id"]))
    @app_commands.command(name="mutes", description="查詢所有的禁言紀錄")
    @app_commands.describe(
        user="要查詢的用戶(預設輸出所有紀錄)",
        recently="是否只查詢最近30天的警告紀錄(預設是)",
    )
    @app_commands.checks.has_permissions(manage_messages=True)
    async def mutes(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        recently: bool=True,
    ):
        """ 查詢禁言紀錄 """
        await interaction.response.defer(thinking = True)
        now, ts = now_with_unix(self.timezone)
        since = ts - 30 * 24 * 3600 if recently else None
        try:
            records = await self.DBManager.list_punishments(
                guild_id = interaction.guild_id,
                user_id = user.id,
                ptype = ["mute", "unmute"],
                start_ts = since,
                limit = None if recently else 100
            )

            if not records:
                embed = discord.Embed(
                    description = "沒有禁言紀錄",
                    colour = discord.Colour.green(),
                    timestamp = now
                )

            embeds: List[discord.Embed] = []
            page_size = 5
            for i in range(0, len(records), page_size):
                chunk = records[i : i + page_size]
                title = (
                    f"{user.display_name}({user.id}) "
                    + ("最近30天的禁言紀錄" if recently else "的全部禁言紀錄")
                )
                emb = discord.Embed(title=title, colour=discord.Colour.orange(), timestamp=now)
                for r in chunk:
                    dt = datetime.fromtimestamp(r["punished_at"], ZoneInfo(self.timezone))
                    time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
                    reason = utils.escape_markdown(r["reason"] or "(無原因)")
                    duration = r["duration"]
                    if duration:
                        duration_str = format_seconds(duration)
                        value = f"禁言時長: {duration_str}\n原因: {reason}"
                    else:
                        value = f"解除禁言\n原因: {reason}"
                    emb.add_field(name=time_str, value=value, inline=False)
                embeds.append(emb)
            
            paginator = Paginator(embeds)
            msg = await interaction.followup.send(embed=embeds[0], view=paginator, ephemeral=True)
            paginator.message = msg

        except Exception as e:
            embed = discord.Embed(title=f"查詢失敗!!", description=f"執行時失敗:{e}", color=discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    try:
        await bot.add_cog(Mute(bot))
    except Exception:
        log.exception("無法載入 mute cog")
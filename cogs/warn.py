import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands

with open("config.json", "r", encoding="utf-8") as fp:
    cfg = json.load(fp)

log = logging.getLogger(__name__)


class Warn(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.DBManager = bot.db_manager

    @app_commands.guilds(discord.Object(id=cfg["guild_id"]))
    @app_commands.has_permissions(administrator=True, manage_messages=True)
    @app_commands.command(name="warn", description="發送並記錄警告")
    @app_commands.describe(
        user="要警告的用戶", reason="警告原因", sendmessage="是否發送私訊給被警告的用戶"
    )
    async def warn(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        reason: str = None,
        send_message: bool = True,
    ):

        now = datetime.now(ZoneInfo(cfg["timezone"]))
        UNIXNOW = int(now.timestamp())

        try:
            if user.id == interaction.user.id:
                await interaction.response.send_message(
                    "你不能警告自己。", ephemeral=True
                )
                return

            if user.bot:
                await interaction.response.send_message(
                    "你不能警告機器人。", ephemeral=True
                )
                return

            await interaction.response.defer(thinking=True)

            await self.DBManager.add_punishment(
                guild_id=interaction.guild.id,
                user_id=user.id,
                punished_at=UNIXNOW,
                ptype="warn",
                reason=reason,
                admin_id=interaction.user.id,
            )

            embed = discord.Embed(
                title="警告通知",
                description=f"{interaction.user.mention} 已對 {user.mention} 發出警告 \n > 原因：{reason or '無原因'}",
                colour=0xFF0000,
                timestamp=now,
            )

            await interaction.followup.send(embed=embed, ephemeral=False)

            if send_message:
                try:
                    embed = discord.Embed(
                        title=f"你已被伺服器管理員 {interaction.user.display_name} 警告",
                        description=f"> 原因：{reason or '無原因'}",
                        colour=0xFF0000,
                        timestamp=now,
                    )
                    embed.set_footer(text=f"{interaction.guild}")
                    await user.send(embed=embed)

                except (discord.Forbidden, discord.HTTPException):
                    await interaction.followup.send(
                        f"無法發送私訊給 {user.mention}，可能是因為他們的隱私設定或伺服器設定。",
                        ephemeral=True,
                    )

                except Exception as e:
                    log.exception(f"發送私訊給 {user.mention} 時發生錯誤:")
                    await interaction.followup.send(
                        f"發送私訊給 {user.mention} 時發生錯誤: {e}，請回報作者",
                        ephemeral=True,
                    )

        except Exception as e:
            log.exception("給予警告時發生錯誤")
            await interaction.followup.send(
                f"給予警告時發生錯誤: {e}，請回報作者", ephemeral=True
            )

    @app_commands.guilds(discord.Object(id=cfg["guild_id"]))
    @app_commands.has_permissions(administrator=True, manage_messages=True)
    @app_commands.command(name="warns", description="查詢用戶的警告紀錄")
    @app_commands.describe(user="要查詢的用戶", recently="是否只查詢最近30天的警告紀錄")
    async def warns(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        recently: bool = False,
    ):

        now = datetime.now(ZoneInfo(cfg["timezone"]))
        UNIXNOW = int(now.timestamp())

        try:
            await interaction.response.defer(ephemeral=True, thinking=True)
            if recently:
                Warns = await self.DBManager.list_punishments(
                    guild_id=interaction.guild.id,
                    user_id=user.id,
                    ptype="warn",
                    start_ts=UNIXNOW - 2592000,
                )
                title = f"{user.display_name}({user.id}) 在過去30天內的警告紀錄"

            else:
                Warns = await self.DBManager.list_punishments(
                    guild_id=interaction.guild.id,
                    user_id=user.id,
                    ptype="warn",
                    start_ts=None,
                    limit=100,
                )
                title = f"{user.display_name}({user.id}) 的警告紀錄"

            if Warns:
                embed = discord.Embed(title=title, color=discord.Color.orange())
                for i in Warns:
                    dt = datetime.fromtimestamp(
                        i["punished_at"], ZoneInfo(cfg["timezone"])
                    )
                    time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
                    embed.add_field(
                        name=f"時間: {time_str}",
                        value=i["reason"] or "(無原因)",
                        inline=False,
                    )
                await interaction.followup.send(embed=embed)

            else:
                embed = discord.Embed(
                    description="沒有警告紀錄", color=discord.Color.green()
                )
                await interaction.followup.send(embed=embed)

        except Exception as e:
            log.exception("指令執行時發生錯誤:")
            await interaction.followup.send(
                f"執行指令時發生錯誤 {e}，請回報作者", ephemeral=True
            )


async def setup(bot):
    try:
        await bot.add_cog(Warn(bot))
        log.info("已載入 Warn cog")

    except Exception:
        log.exception("無法載入 Warn cog")

import json
import logging

import discord
from discord import app_commands, utils
from discord.ext import commands

from utils.time_utils import now_with_unix

with open("config.json", "r", encoding="utf-8") as fp:
    cfg = json.load(fp)

log = logging.getLogger(__name__)


class Ban(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_manager = bot.db_manager
        self.guild_id = cfg["guild_id"]
        self.timezone = cfg["timezone"]

    @app_commands.guilds(discord.Object(id=cfg["guild_id"]))
    @app_commands.checks.has_permissions(ban_members=True)
    @app_commands.checks.bot_has_permissions(ban_members=True)
    @app_commands.command(name="ban", description="Ban 指定的使用者")
    @app_commands.describe(
        user="要 Ban 的使用者", 
        reason="Ban 的原因",
        delete_message_days="刪除使用者的訊息天數 (0-7, 預設為 0)",
        send_message="是否發送私訊給被 Ban 的使用者 (預設為 True, 但如果沒有權限則不發送)"
    )
    async def ban(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        reason: str = None,
        delete_message_days: int = 0,
        send_message: bool = True
    ):
        
        now, ts = now_with_unix(self.timezone)
        # 檢查非法輸入
        if user.id == interaction.user.id:
            return await interaction.response.send_message("你不能封禁自己。", ephemeral=True)
        if user.bot:
            return await interaction.response.send_message("你不能封禁機器人。", ephemeral=True)
        if reason and len(reason) > 200:
            return await interaction.response.send_message("原因文字長度不得超過200字。", ephemeral=True)        
        if delete_message_days < 0 or delete_message_days > 7:
            return await interaction.response.send_message("刪除訊息天數必須在 0 到 7 天之間。", ephemeral=True)

        await interaction.response.defer(thinking=True)
        
        # 檢查使用者是否已經被封禁
        try:
            ban_list = [entry.user.id async for entry in interaction.guild.bans()]
            if user.id in ban_list:
                return await interaction.followup.send("該使用者已經被封禁。", ephemeral=True)
        except discord.Forbidden:
            return await interaction.followup.send("無法檢查封禁列表，請確認機器人有足夠的權限。", ephemeral=True)
        except discord.HTTPException:
            log.exception("檢查封禁列表時發生 HTTP 錯誤")
            return await interaction.followup.send("檢查封禁列表失敗，請稍後再試。", ephemeral=True)
        except Exception as e:
            log.exception("檢查封禁列表時發生錯誤")
            return await interaction.followup.send(f"檢查封禁列表失敗: {e}", ephemeral=True)
        
        # 嘗試發送私訊給被封禁者
        if send_message:
            try:
                dm = discord.Embed(
                    title=f"你已被伺服器管理員 {interaction.user.display_name} 封禁",
                    description=f"> 原因：{utils.escape_markdown(reason or '無原因')}",
                    colour=discord.Colour.red(),
                    timestamp=now,
                )
                dm.set_footer(text=interaction.guild.name)
                dm.set_author(name=f'{interaction.guild.name}封禁通知', icon_url=interaction.guild.icon.url if interaction.guild.icon else None)
            except Exception:
                log.exception("建立私訊 Embed 時發生錯誤")
                return await interaction.followup.send(
                    "建立私訊內容時發生錯誤，請回報作者。", ephemeral=True
                )
                
            # 嘗試發送私訊
            try:
                await user.send(embed=dm)
                await interaction.followup.send(
                    f"已向 {user.mention} 發送封禁私訊。", ephemeral=True
                )
            except (discord.Forbidden, discord.HTTPException):
                await interaction.followup.send(
                    f"無法發送私訊給 {user.mention}，可能隱私設定阻擋。", ephemeral=True
                )
            except Exception:
                log.exception("發送私訊時發生錯誤")
                await interaction.followup.send("發送私訊時發生錯誤，請回報作者。", ephemeral=True)
        
        # 嘗試封禁使用者
        try:
            await interaction.guild.ban(user, reason=reason, delete_message_days=delete_message_days)
        except discord.NotFound:
            return await interaction.followup.send("無法封禁該使用者，可能已經不存在或不在此伺服器中。", ephemeral=True)
        except discord.Forbidden:
            return await interaction.followup.send("無法封禁該使用者，請確認機器人有足夠的權限。", ephemeral=True)
        except discord.HTTPException:
            log.exception("封禁使用者時發生 HTTP 錯誤")
            return await interaction.followup.send("封禁失敗，請稍後再試。", ephemeral=True)
        except Exception as e:
            log.exception("封禁失敗")
            await interaction.followup.send(f"封禁失敗: {e}")
        
        # 嘗試加入資料庫
        try:
            await self.db_manager.add_punishment(
                guild_id=interaction.guild.id,
                user_id=user.id,
                punished_at=ts,
                ptype="ban",
                admin_id=interaction.user.id,
                reason=reason
            )
        except Exception as e:
            log.exception("加入封禁紀錄到資料庫失敗")
            return await interaction.followup.send(f"封禁成功，但無法記錄到資料庫: {e}", ephemeral=True)
        
        # 嘗試發送訊息到頻道
        desc = f"{interaction.user.mention} 已封禁 {user.mention} \n> 原因：{utils.escape_markdown(reason or '無原因')}"
        embed = discord.Embed(
            title="封禁通知",
            description=desc,
            colour=discord.Colour.red(),
            timestamp=now,
        )
        await interaction.followup.send(embed=embed, ephemeral=False)
        

async def setup(bot):
    try:
        await bot.add_cog(Ban(bot))
        log.info("Ban 擴充已載入")
    except Exception:
        log.exception("載入 Ban 擴充時發生錯誤")

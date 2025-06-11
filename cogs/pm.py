import json
import logging

import discord
from discord import app_commands
from discord.ext import commands

with open("config.json", "r", encoding="utf-8") as fp:
    cfg = json.load(fp)

log = logging.getLogger(__name__)

class PM(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.guilds(discord.Object(id=cfg["guild_id"]))
    @app_commands.command(name="pm", description="私訊指定用戶")
    @app_commands.describe(
        user="要私訊的用戶", message="要發送的訊息", anonymous="是否匿名（預設否）"
    )
    async def pm(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        message: str,
        anonymous: bool = False,
    ):
        """ 發送訊息給指定用戶(可選擇匿名) """
        sender = interaction.user

        try:
            if anonymous:
                title = "你收到一則匿名訊息"
                desc = message
            else:
                title = f"你收到來自 {sender.display_name} 的私訊"
                desc = message

            embed = discord.Embed(title=title, description=desc, color=discord.Color.blue())    
            await user.send(embed=embed)
            sender_title = f"已私訊 {user.display_name}!"
            sender_embed = discord.Embed(title=sender_title, description=desc, color=discord.Color.blue())
            await interaction.response.send_message(
                embed=sender_embed, ephemeral=True
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "無法私訊該用戶（可能關閉了私訊）", ephemeral=True
            )
        except Exception:
            logging.exception("執行指令時發生錯誤")


async def setup(bot):
    await bot.add_cog(PM(bot))

import discord
import json
from discord.ext import commands
from discord import app_commands

with open("config.json", "r", encoding="utf-8") as fp:
    cfg = json.load(fp)

class PM(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.guilds(discord.Object(id=cfg["guild_id"]))
    @app_commands.command(name="pm", description="私訊指定用戶")
    @app_commands.describe(user="要私訊的用戶", message="要發送的訊息", anonymous="是否匿名（預設否）")
    async def pm(self, interaction: discord.Interaction, user: discord.User, message: str, anonymous: bool = False):
        """ 發送訊息給指定用戶(可選擇匿名) """
        try:
            if anonymous:
                dm_content = f"你收到一則匿名訊息：\n{message}"
            else:
                sender = interaction.user
                dm_content = f"你收到來自 {sender.mention} 的私訊：\n{message}"
            await user.send(dm_content)
            await interaction.response.send_message(f"已私訊 {user.mention}!: \n{message}", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("無法私訊該用戶（可能關閉了私訊）", ephemeral=True)

async def setup(bot):
    await bot.add_cog(PM(bot))
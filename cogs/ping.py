import discord
import json
from discord.ext import commands
from discord import app_commands
import time

with open("config.json", "r", encoding="utf-8") as fp:
    cfg = json.load(fp)

class Ping(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.guilds(discord.Object(id=cfg["guild_id"]))
    @app_commands.command(name="ping", description="顯示機器人的延遲")
    async def ping(self, interaction: discord.Interaction):
        """顯示機器人與Discord之間的延遲"""
        # 計算延遲開始時間
        start_time = time.time()
        
        # 先回應互動以避免超時
        await interaction.response.defer(thinking=True)
        
        # 計算API延遲
        end_time = time.time()
        api_latency = round((end_time - start_time) * 1000)
        
        # 獲取Websocket延遲
        ws_latency = round(self.bot.latency * 1000)
        
        # 創建嵌入訊息
        embed = discord.Embed(title="🏓 Pong!", color=discord.Color.green())
        embed.add_field(name="API 延遲", value=f"`{api_latency} ms`", inline=True)
        embed.add_field(name="Websocket 延遲", value=f"`{ws_latency} ms`", inline=True)
          # 回覆互動
        await interaction.followup.send(embed=embed)

async def setup(bot):
    await bot.add_cog(Ping(bot))
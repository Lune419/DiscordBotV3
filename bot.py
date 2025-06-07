import os
import json
from discord.ext import commands
from discord import Intents
from dotenv import load_dotenv
import time

load_dotenv()

intents = Intents.all()

with open('config.json', 'r',encoding="utf-8") as config:
    config = json.load(config)

bot = commands.Bot(command_prefix='!', intents=intents)

for filename in os.listdir("./cogs"):
    try:
        if filename.endswith(".py"):
            bot.load_extension(f"cogs.{filename[:-3]}")
    except Exception as e:
        print(f"無法載入 {filename}: {e}")
        
@bot.event
async def on_ready():
    print(f'以下身份登入: {bot.user.name} - {bot.user.id}')
    synced = await bot.tree.sync()
    print(f"同步了 {len(synced)} 個指令:")
    for command in synced:
        print(f"- {command.name}")

if __name__ == "__main__": 
    try:
        bot.run(os.getenv('TOKEN'))
    except Exception as e:
        print(f"啟動時發生錯誤: {e}")

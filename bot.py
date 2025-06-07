import os
import json
from discord.ext import commands
from discord import Intents,Object
from dotenv import load_dotenv
from datetime import datetime, timezone, timedelta

load_dotenv()

with open('config.json', 'r',encoding="utf-8") as f:
    config = json.load(f)

intents = Intents.all()
    
class Bot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix=config['prefix'], intents=intents, help_command=None)

    async def load_extensions(self):
        for filename in os.listdir("./cogs"):
            try:
                if filename.endswith(".py"):
                    await self.load_extension(f"cogs.{filename[:-3]}")
                    # print(f"已載入 {filename}")
            except Exception as e:
                print(f"無法載入 {filename}: {e}")
        
    async def setup_hook(self):
        await self.load_extensions()
        try:
            await self.tree.sync(guild=Object(config['guild_id']))  # 同步到特定伺服器
            """
            synced = await self.tree.sync()
            print(f"已同步 {len(synced)} 個指令")
            for command in synced:
                print(f"- {command.name}")
            """
        except Exception as e:
            print(f"同步時發生錯誤: {e}")
    
    async def on_ready(self):
        current_time = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
        print(f'現在時間:{current_time} - 以下身份登入: {self.user.name} - {self.user.id}')
        command_list = await self.tree.fetch_commands()
        print(f"已註冊 {len(command_list)} 個指令:")
        for command in command_list:
            print(f"- {command.name} (ID: {command.id})")
            
bot = Bot()

if __name__ == "__main__": 
    try:
        bot.run(os.getenv('TOKEN'))
    except Exception as e:
        print(f"啟動時發生錯誤: {e}")

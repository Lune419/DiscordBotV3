import asyncio, os, json, logging, discord
from discord.ext import commands
from zoneinfo import ZoneInfo
from datetime import datetime
from utils.DBManager import DBManager

with open("config.json", "r", encoding="utf-8") as fp:
    cfg = json.load(fp)

intents = discord.Intents.all()

class Bot(commands.Bot):
    def __init__(self) -> None:
        super().__init__(command_prefix=cfg["prefix"],intents=intents,help_command=None)
        self.db_manager = DBManager(os.getenv('database', 'bot.db'))

    async def setup_hook(self) -> None:
        # 清掉垃圾(已刪除或不需要的命令)
        # self.tree.clear_commands(guild=guild)
        # 載入擴充
        for f in os.listdir("./cogs"):
            if f.endswith(".py") and not f.startswith("_"):
                try:
                    await self.load_extension(f"cogs.{f[:-3]}")
                    print(f"✅ 已載入擴充: {f[:-3]}")
                except Exception as e:
                    print(f"❌ 無法載入擴充 {f[:-3]}: {e}")
                    continue
        print("✅ 擴充載入完畢")

        # 初始化資料庫
        await self.db_manager.init_db()

        guild= discord.Object(id=cfg["guild_id"])
        # 同步指令
        synced = await self.tree.sync(guild=guild)
        print(f'已同步{len(synced)}個指令')

    async def on_ready(self) -> None:
        now = datetime.now(ZoneInfo(cfg['timezone'])).strftime("%F %T")
        print(f"{now} | 登入為 {self.user} ({self.user.id})")

async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    discord.utils.setup_logging()
    async with Bot() as bot:
        await bot.start(os.getenv("TOKEN"))

if __name__ == "__main__":
    asyncio.run(main())
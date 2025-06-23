import asyncio
import json
import logging
import os
from pathlib import Path

import discord
from discord.ext import commands

from utils.DBManager import DBManager

with open("config.json", "r", encoding="utf-8") as fp:
    cfg = json.load(fp)

intents = discord.Intents.all()
log = logging.getLogger("main_bot")


class Bot(commands.Bot):
    def __init__(self) -> None:
        super().__init__(
            command_prefix=cfg["prefix"], intents=intents, help_command=None
        )
        self.db_manager = DBManager(os.getenv("database", "bot.db"))

    async def setup_hook(self) -> None:
        # 清掉垃圾(已刪除或不需要的命令)
        # self.tree.clear_commands(guild=guild)
        # 載入擴充
        for p in Path("cogs").glob("*.py"):
            if p.name.startswith("_"):
                continue
            try:
                await self.load_extension(f"cogs.{p.stem}")
            except Exception:
                log.exception(f"載入擴充 {p.stem} 時發生錯誤")
        log.info("載入擴充完畢")

        # 初始化資料庫
        try:
            await self.db_manager.init_db()
        except Exception as _:
            log.exception("初始化一般資料庫時發生錯誤")
        try:
            await self.db_manager.init_voice_db()
        except Exception as _:
            log.exception("初始化語音資料庫時發生錯誤")

        # 同步指令
        guild = discord.Object(id=cfg["guild_id"])
        synced = await self.tree.sync(guild=guild)
        log.info(f"已同步{len(synced)}個指令")

    async def on_ready(self) -> None:
        log.info(f"登入為 {self.user} ({self.user.id})")


async def main() -> None:
    discord.utils.setup_logging()

    async with Bot() as bot:
        await bot.start(os.getenv("TOKEN"))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Bot 已被手動停止")
        os.system("pause")
    except Exception as e:
        log.exception(f"Bot 啟動時發生錯誤: {e}")

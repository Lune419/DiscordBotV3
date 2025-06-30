import discord
import os
from discord.ext import commands
from discord import app_commands
from typing import Optional
import aiosqlite
import asyncio
import json
import logging

log = logging.getLogger(__name__)

with open("config.json", "r", encoding="utf-8") as f:
    cfg = json.load(f)


class TempVoiceDatabase:
    def __init__(self, dbpath) -> None:
        self.dbpath = os.getenv("VOICEDATABASE", dbpath)
        self.conn: Optional[aiosqlite.Connection] = None
        
    async def connect(self):
        if self.conn is None:
            self.conn = await aiosqlite.connect(self.dbpath)
            self.conn.row_factory = aiosqlite.Row
            
    async def initdb(self):
        
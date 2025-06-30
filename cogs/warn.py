import json
import logging
from typing import Optional, Any, List

import discord
from discord import app_commands, utils
from discord.ext import commands
from discord.ui import View, button

from utils.time_utils import now_with_unix
from zoneinfo import ZoneInfo
from datetime import datetime

with open("config.json", "r", encoding="utf-8") as fp:
    cfg = json.load(fp)

log = logging.getLogger(__name__)

class WarnsPaginator(View):
    def __init__(self, embeds: List[discord.Embed]):
        super().__init__(timeout=120)
        self.embeds = embeds
        self.current = 0
        # 頁面資訊（例如：1/3）
        total = len(embeds)
        self.page_indicator = discord.ui.Button(
            label=f"{self.current+1}/{total}", style=discord.ButtonStyle.secondary, disabled=True
        )
        self.add_item(self.page_indicator)

    @button(label="◀️", style=discord.ButtonStyle.primary, disabled=True)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current -= 1
        await self._update(interaction)

    @button(label="▶️", style=discord.ButtonStyle.primary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current += 1
        await self._update(interaction)

    async def _update(self, interaction: discord.Interaction):
        total = len(self.embeds)
        # 更新按鈕狀態
        self.previous.disabled = (self.current == 0)
        self.next.disabled = (self.current == total - 1)
        # 更新頁面指示
        self.page_indicator.label = f"{self.current+1}/{total}"
        await interaction.response.edit_message(embed=self.embeds[self.current], view=self)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        # 編輯訊息，將所有按鈕停用
        try:
            await self.message.edit(view=self)
        except:
            pass

class Warn(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db_manager
        self.guild_id = cfg["guild_id"]
        self.timezone = cfg["timezone"]

    @app_commands.guilds(discord.Object(id=cfg["guild_id"]))
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.command(name="warn", description="發送並記錄警告")
    @app_commands.describe(
        user="要警告的用戶",
        reason="警告原因（最多200字）",
        send_message="是否發送私訊給被警告的用戶",
    )
    async def warn(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        reason: Optional[str] = None,
        send_message: bool = True,
    ):
        # 檢查不合理輸入
        if user.id == interaction.user.id:
            return await interaction.response.send_message("你不能警告自己。", ephemeral=True)
        if user.bot:
            return await interaction.response.send_message("你不能警告機器人。", ephemeral=True)
        if reason and len(reason) > 200:
            return await interaction.response.send_message("原因文字長度不得超過200字。", ephemeral=True)

        now, ts = now_with_unix(self.timezone)
        await interaction.response.defer(thinking=True)

        # 記錄到資料庫
        try:
            await self.db.add_punishment(
                guild_id=interaction.guild_id,
                user_id=user.id,
                punished_at=ts,
                ptype="warn",
                reason=reason,
                admin_id=interaction.user.id,
            )
        except Exception:
            log.exception("添加警告到資料庫時發生錯誤")
            return await interaction.followup.send("記錄警告時發生錯誤，請稍後重試。", ephemeral=True)

        # 在頻道中回覆
        desc = f"{interaction.user.mention} 已對 {user.mention} 發出警告\n> 原因：{utils.escape_markdown(reason or '無原因')}"
        embed = discord.Embed(
            title="警告通知",
            description=desc,
            colour=discord.Colour.red(),
            timestamp=now,
        )
        await interaction.followup.send(embed=embed, ephemeral=False)

        # 私訊被警告者
        if send_message:
        # 建立私訊內容
            try:
                dm = discord.Embed(
                    title=f"你已被伺服器管理員 {interaction.user.display_name} 警告",
                    description=f"> 原因：{utils.escape_markdown(reason or '無原因')}",
                    colour=discord.Colour.red(),
                    timestamp=now,
                )
                dm.set_footer(text=interaction.guild.name)
                dm.set_author(name=f'{interaction.guild.name}警告通知',
                              icon_url=interaction.guild.icon.url if interaction.guild.icon else None)
            except Exception:
                log.exception("建立私訊 Embed 時發生錯誤")
                return await interaction.followup.send(
                    "建立私訊內容時發生錯誤，請回報作者。", ephemeral=True
                )
        # 嘗試發送私訊
            try:
                await user.send(embed=dm)
                await interaction.followup.send(
                    f"已向 {user.mention} 發送警告私訊。", ephemeral=True
                )
            except (discord.Forbidden, discord.HTTPException):
                await interaction.followup.send(
                    f"無法發送私訊給 {user.mention}，可能隱私設定阻擋。", ephemeral=True
                )
            except Exception:
                log.exception("Unexpected error on DM warn")
                await interaction.followup.send("發送私訊時發生錯誤，請回報作者。", ephemeral=True)

    @app_commands.guilds(discord.Object(id=cfg["guild_id"]))
    @app_commands.checks.has_permissions(administrator=True, manage_messages=True)
    @app_commands.command(name="warns", description="查詢用戶的警告紀錄")
    @app_commands.describe(
        user="要查詢的用戶",
        recently="是否只查詢最近30天的警告紀錄",
    )
    async def warns(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        recently: bool = False,
    ):
        now, ts = now_with_unix(self.timezone)
        await interaction.response.defer(thinking=True, ephemeral=True)

        # 擷取資料
        since = ts - 30 * 24 * 3600 if recently else None
        records = await self.db.list_punishments(
            guild_id=interaction.guild_id,
            user_id=user.id,
            ptype="warn",
            start_ts=since,
            limit=None if recently else 100,
        )

        if not records:
            embed = discord.Embed(
                description="沒有警告紀錄",
                colour=discord.Colour.green(),
                timestamp=now,
            )
            return await interaction.followup.send(embed=embed, ephemeral=True)

        # 建立多個分頁 embed（每頁最多 5 項）
        embeds: List[discord.Embed] = []
        page_size = 5
        for i in range(0, len(records), page_size):
            chunk = records[i : i + page_size]
            title = (
                f"{user.display_name}({user.id}) "
                + ("最近30天的警告紀錄" if recently else "的全部警告紀錄")
            )
            emb = discord.Embed(title=title, colour=discord.Colour.orange(), timestamp=now)
            for r in chunk:
                dt = datetime.fromtimestamp(r["punished_at"], ZoneInfo(self.timezone))
                time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
                reason = utils.escape_markdown(r["reason"] or "(無原因)")
                emb.add_field(name=time_str, value=reason, inline=False)
            embeds.append(emb)

        # 啟動分頁 View
        paginator = WarnsPaginator(embeds)
        # 存下 message 以供 on_timeout 編輯
        msg = await interaction.followup.send(embed=embeds[0], view=paginator, ephemeral=True)
        paginator.message = msg  # type: ignore


async def setup(bot: commands.Bot):
    try:
        await bot.add_cog(Warn(bot))
        log.info("Warn 擴充已載入")
    except Exception:
        log.exception("無法載入 Warn cog")
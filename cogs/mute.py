import json
import logging
from typing import List
from datetime import timedelta
from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import View, button

with open("config.json", "r", encoding="utf-8") as fp:
    cfg = json.load(fp)

log = logging.getLogger(__name__)

from typing import List

class MutesPaginator(View):
    def __init__(self, embeds: List[discord.Embed]):
        super().__init__(timeout=120)
        self.embeds = embeds
        self.current = 0
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
        self.previous.disabled = (self.current == 0)
        self.next.disabled = (self.current == total - 1)
        self.page_indicator.label = f"{self.current+1}/{total}"
        await interaction.response.edit_message(embed=self.embeds[self.current], view=self)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        try:
            if hasattr(self, "message"):
                await self.message.edit(view=self)
        except:
            pass

class Mute(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.DBManager = bot.db_manager


    @app_commands.guilds(discord.Object(id=cfg["guild_id"]))
    @app_commands.command(name="mute", description="禁言指定成員")
    @app_commands.describe(
        user="要禁言的成員",
        days="禁言幾日",
        hours="禁言幾小時",
        minutes="禁言幾分鐘",
        reason="禁言原因",
    )
    @app_commands.checks.has_permissions(administrator=True, manage_messages=True)
    async def mute(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        days: int = 0,
        hours: int = 0,
        minutes: int = 0,
        reason: str = None
    ):
        """ 禁言 """
        try:
            now = datetime.now(ZoneInfo(cfg["timezone"]))
            UNIXNOW = int(now.timestamp())
            durations = timedelta(days=days, hours=hours, minutes=minutes)
            durations_seconds = durations.total_seconds()

            if user.id == interaction.user.id:
                await interaction.response.send_message(
                    "你不能禁言自己。", ephemeral=True
                )
                return

            if user.bot:
                await interaction.response.send_message(
                    "你不能禁言機器人。", ephemeral=True
                )
                return

            if durations_seconds <= 0:
                embed = discord.Embed(
                    title       = f"禁言{user.display_name}失敗!!",
                    description = "禁言時間必須為正數!", 
                    color       = discord.Color.orange()
                )
                await interaction.response.send_message(embed=embed, ephemeral=False)
                return

            else:
                await user.timeout(durations, reason=reason)

                await self.DBManager.add_punishment(
                    guild_id=interaction.guild.id,
                    user_id=user.id,
                    punished_at=UNIXNOW,
                    ptype="mute",
                    duration=durations_seconds,
                    reason=reason,
                    admin_id=interaction.user.id,
                )

                durations_str = self.get_durations_str(durations_seconds)
                embed = discord.Embed(
                    title       = f"禁言成功!!", 
                    description = f"{interaction.user.mention} 將 {user.mention} 禁言 {durations_str}\n原因: {reason}",
                    color       = discord.Color.green()
                )                
            await interaction.response.send_message(embed=embed, ephemeral=False) 

        except Exception as e:
            log.exception("指令執行時發生錯誤:")
            embed = discord.Embed(title= f"禁言 {user.display_name} 失敗!!", description= f"執行時失敗:{e}", color=discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)



    @app_commands.guilds(discord.Object(id=cfg["guild_id"]))
    @app_commands.command(name="unmute", description="解除禁言指定成員")
    @app_commands.describe(
        user="要解除禁言的成員",
        reason="解除禁言原因"
    )
    @app_commands.checks.has_permissions(administrator=True, manage_messages=True)
    async def unmute(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        reason: str = None
    ):
        """ 解除禁言 """
        try:
            now = datetime.now(ZoneInfo(cfg["timezone"]))
            UNIXNOW = int(now.timestamp())

            if not user.timed_out_until:
                embed = discord.Embed(
                    title = f"{user.display_name} 沒有被禁言!!", 
                    color = discord.Color.orange()
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)

            else:
                await user.timeout(None, reason=reason)

                await self.DBManager.add_punishment(
                    guild_id=interaction.guild.id,
                    user_id=user.id,
                    punished_at=UNIXNOW,
                    ptype="mute",
                    duration=0,
                    reason=reason,
                    admin_id=interaction.user.id,
                )

                embed = discord.Embed(
                    title       = f"解除禁言成功!!", 
                    description = f"{interaction.user.mention} 解除了 {user.mention} 的禁言\n原因: {reason}",
                    color       = discord.Color.green()
                )                
                await interaction.response.send_message(embed=embed, ephemeral=False)

        except Exception as e:
            log.exception("指令執行時發生錯誤:")
            embed = discord.Embed(title= f"解除禁言 {user.display_name} 失敗!!", description= f"執行時失敗:{e}", color= discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)



    @app_commands.guilds(discord.Object(id=cfg["guild_id"]))
    @app_commands.command(name="muting", description="查詢正處於禁言狀態的用戶")
    @app_commands.describe(
        user="要查詢的用戶(預設全部處於禁言狀態的用戶)",
        n="禁言紀錄筆數(預設1, 最多100; 全部用戶鎖定為1)",
        include_unmute="是否包含解除禁言的紀錄(預設否)"
    )
    @app_commands.checks.has_permissions(administrator=True, manage_messages=True)
    async def muting(
        self,
        interaction: discord.Interaction,
        user: discord.Member = None,
        n: int = 1,
        include_unmute: bool = False
    ):
        """ 查詢 正處於禁言狀態 的用戶  """
        try:
            guild = interaction.guild

            # 檢查有無被禁言的成員
            muted_members = [
                m for m in guild.members
                if m.timed_out_until and m.timed_out_until > discord.utils.utcnow()
            ]
            if not muted_members:
                embed = discord.Embed(title="沒有正在被禁言的成員!!")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # 檢查n值
            if n < 1:
                embed = discord.Embed(title="n 必須為正整數!!", color= discord.Color.orange())
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            elif n > 100:
                embed = discord.Embed(title="n 必須小於或等於 100!!", color= discord.Color.orange())
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
               
            # 若user輸入 -> 輸出該成員資訊
            if user:
                if not user.timed_out_until or user.timed_out_until <= discord.utils.utcnow():
                    embed = discord.Embed(
                        title=f"{user.display_name} 並非處於禁言狀態!!",
                        color=discord.Color.orange()
                    )
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    return

                until = user.timed_out_until.strftime("%Y-%m-%d %H:%M:%S")
                embeds = await self.search_mute_from_db(
                    interaction=interaction,
                    guild_id=guild.id,
                    user_id=user.id,
                    limit=n,
                    include_unmute=include_unmute,
                    mode="user",
                    recently=False,
                    mute_until=until
                )

                paginator = MutesPaginator(embeds)
                await interaction.response.send_message(embed=embeds[0], view=paginator, ephemeral=True)
                paginator.message = await interaction.original_response()
                return
            
            # 若user未輸入 -> 查詢所有被禁言成員
            # 1. 收集所有被禁言成員的 user_id 及禁言到時間
            mute_until_dict = {m.id: m.timed_out_until.strftime("%Y-%m-%d %H:%M:%S") for m in muted_members}
            # 2. 查詢所有這些成員的禁言紀錄
            embeds = await self.search_mute_from_db(
                interaction=interaction,
                guild_id=guild.id,
                limit= 1,
                include_unmute=include_unmute,
                mode="all",
                recently=False,
                mute_until=mute_until_dict  # 傳 dict
            )

            paginator = MutesPaginator(embeds)
            await interaction.response.send_message(embed=embeds[0], view=paginator, ephemeral=True)
            paginator.message = await interaction.original_response()

        except Exception as e:
            embed = discord.Embed(title=f"查詢禁言失敗!!", description=f"執行時失敗:{e}", color=discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)


    @app_commands.guilds(discord.Object(id=cfg["guild_id"]))
    @app_commands.command(name="mutes", description="查詢所有的禁言紀錄")
    @app_commands.describe(
        user="要查詢的用戶(預設輸出所有紀錄)",
        recently="是否只查詢最近30天的警告紀錄(預設是)",
        include_unmute="是否包含解除禁言的紀錄(預設否)"
    )
    @app_commands.checks.has_permissions(administrator=True, manage_messages=True)
    async def mutes(
        self,
        interaction: discord.Interaction,
        user: discord.Member = None,
        recently: bool=True,
        include_unmute: bool = False
    ):
        """ 查詢禁言紀錄 """
        try:
            await interaction.response.defer(ephemeral=True)
            embeds = await self.search_mute_from_db(
                interaction=interaction,
                guild_id=interaction.guild.id,
                user_id=user.id if user else None,  # 若user未輸入 -> 輸出所有禁言紀錄
                limit=100,
                include_unmute=include_unmute,
                mode="user" if user else "all",
                recently=recently,
            )

            if not embeds:
                embed = discord.Embed(title="查無紀錄", color=discord.Color.orange())
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            paginator = MutesPaginator(embeds)
            msg = await interaction.followup.send(embed=embeds[0], view=paginator, ephemeral=True)
            paginator.message = msg 

        except Exception as e:
            embed = discord.Embed(title=f"查詢失敗!!", description=f"執行時失敗:{e}", color=discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)



    
    async def search_mute_from_db(
        self,
        interaction: discord.Interaction,
        guild_id: int,
        limit: int,
        include_unmute: bool,
        mode: str,
        recently: bool,
        user_id: int = None,
        mute_until = None
    ) -> list:
        """ 
        從資料庫查詢禁言紀錄

        回傳:   
            {何時}: 
            {誰}  因  {甚麼原因}  被  {哪個管理員}  禁言  {多久}
        """
        try:
            now = datetime.now(ZoneInfo(cfg["timezone"]))
            UNIXNOW = int(now.timestamp())

            # 組裝查詢參數
            query = {
                "guild_id": guild_id,
                "ptype": "mute"
            }
            if mode == "user" and user_id:
                query["user_id"] = user_id
            if recently:
                query["start_ts"] = UNIXNOW - 2592000
            else:
                query["limit"] = limit

            punishments = await self.bot.db_manager.list_punishments(**query)  # 把 query 這個字典裡的所有鍵值對，當作參數傳給 list_punishments

            # embed 組裝
            def make_embed(chunk):
                if mode == "user":
                    member = interaction.guild.get_member(user_id)
                    title = f"{member.display_name}({member.id}) " + ("最近30天的禁言紀錄" if recently else "的全部禁言紀錄")
                else:
                    title = "所有用戶的禁言紀錄"
                embed = discord.Embed(
                    title=title,
                    colour=discord.Colour.orange(),
                    timestamp=now,
                    description=f"🚫 禁言到：{mute_until}" if mute_until and mode == "user" else None
                )
                for p in chunk:
                    dt = datetime.fromtimestamp(p["punished_at"], ZoneInfo(cfg["timezone"])).strftime("%Y-%m-%d %H:%M:%S")
                    reason = p["reason"] or "(無原因)"
                    duration = p["duration"]
                    admin_id = p["admin_id"]
                    admin_member = interaction.guild.get_member(admin_id)
                    admin = admin_member.display_name if admin_member else f"ID: {admin_id}"
                    u_id = p["user_id"]
                    u_member = interaction.guild.get_member(u_id)
                    user_str = f"\n{u_member.display_name}  " if mode == "all" and u_member else ""

                    until_str = ""
                    if mode == "all" and isinstance(mute_until, dict):
                        until_str = f"🚫 禁言到：{mute_until.get(u_id, '未知')}"
                        user_str = ""
                    
                    if duration > 0:
                        duration_str = self.get_durations_str(second=duration)
                        value = f"{user_str}  被  {admin}  禁言了  {duration_str}\n原因: {reason}"
                    elif include_unmute and duration == 0:
                        value = f"{user_str}  被  {admin}  解除禁言\n原因: {reason}"
                    else:
                        continue

                    if mute_until and mode == "all":
                        embed.add_field(name=f"{u_member.display_name}   {until_str}", value=f"{dt}\n"+value, inline=False)
                    else:
                        embed.add_field(name=f"{dt}", value=value, inline=False)

                if not chunk:
                    embed.add_field(name="查無紀錄", value=" ", inline=False)
                return embed
            
            # 分頁
            page_size = 5
            embeds = [make_embed(punishments[i:i+page_size]) for i in range(0, len(punishments), page_size)]

            if not embeds:
                embed = discord.Embed(title="查無紀錄", color=discord.Color.orange())
                embeds = [embed]
            return embeds

        except Exception:
            log.exception("查詢禁言紀錄失敗!!")
            embed = discord.Embed(title="查詢失敗", description="查詢禁言紀錄時發生錯誤", color=discord.Color.red())
            return [embed]

   
    def get_durations_str(self, second: int) -> str:
        try:
            """ 將 秒 轉換為日、時、分 """
            days = second // 86400
            hours = (second % 86400) // 3600
            minutes = (second % 3600) // 60
            days_str = f"{int(days)}日" if days > 0 else ""
            hours_str = f"{int(hours)}小時" if hours > 0 else ""
            minutes_str = f"{int(minutes)}分鐘" if minutes > 0 else ""
            duration_str = days_str + hours_str + minutes_str
            return duration_str
        
        except Exception:
            log.exception("時間轉字串失敗!!")
            return ""

async def setup(bot):
    try:
        await bot.add_cog(Mute(bot))
    except Exception:
        log.exception("無法載入 mute cog")
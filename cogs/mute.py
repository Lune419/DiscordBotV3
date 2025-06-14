import json
import logging
from datetime import timedelta
from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands

with open("config.json", "r", encoding="utf-8") as fp:
    cfg = json.load(fp)

log = logging.getLogger(__name__)

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
        reason: str = "沒有原因"
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
    @app_commands.command(name="muting", description="查詢正在被禁言的用戶")
    @app_commands.describe(
        user="要查詢的用戶(預設全部被禁言的用戶)",
        n="指定回傳最近的 n 筆禁言紀錄(預設1, 最多100)",
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
        """ 
            查詢 正處於禁言狀態 的用戶 

            參數:
            user: 要查詢的用戶 (沒填 -> 所有處於禁言狀態的用戶)
            n:    要查詢的筆數 (沒填 -> 最近的 1 筆; 最多100)
            include_unmute: 查詢的資料是否包含解除禁言的紀錄 (預設: False)
        """
        try:
            guild = interaction.guild

            # 檢查有沒有被禁成員
            muted_member = [
                m for m in guild.members
                if m.timed_out_until and m.timed_out_until > discord.utils.utcnow()
            ]
            if not muted_member:
                embed = discord.Embed(title="沒有正在被禁言的成員!!")
            else:   
                # 若user未輸入 -> 輸出所有被禁成員
                if user is None:
                    embed = discord.Embed(title="所有正在被禁言的成員")
                    
                    for member in muted_member:
                        until = member.timed_out_until.strftime("%Y-%m-%d %H:%M:%S")
                        results = await self.find_punishments_from_db(
                            interaction= interaction, 
                            guild_id= guild.id, 
                            user_id= member.id,  
                            limit= n,
                            include_unmute= include_unmute,
                            mode= "user",
                            recently= False
                        )
                        embed.add_field(
                            name= member.display_name,
                            value= f"禁言到 {until}\n最近的禁言處分:\n" + "\n".join(results),
                            inline=False
                        )

                else:
                    until = user.timed_out_until.strftime("%Y-%m-%d %H:%M:%S")
                    results = await self.find_punishments_from_db(
                            interaction= interaction, 
                            guild_id= guild.id, 
                            user_id= user.id, 
                            limit= n,
                            include_unmute= include_unmute,
                            mode= "user",
                            recently= False
                        )
                    embed = discord.Embed(title="查詢正在被禁言的用戶成功!!")
                    embed.add_field(
                            name= user.display_name,
                            value= f"禁言到 {until}\n最近的禁言處分:\n" + "\n".join(results),
                            inline=False
                        )
            await interaction.response.send_message(embed=embed, ephemeral=True)

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
            guild = interaction.guild
            
            # 若user未輸入 -> 輸出所有禁言紀錄
            if user is None:
                if recently:
                    embed = discord.Embed(title="30天內的所有禁言紀錄")
                else:
                    embed = discord.Embed(title="最近100筆禁言紀錄")
                
                results = await self.find_punishments_from_db(
                    interaction= interaction, 
                    guild_id= guild.id, 
                    user_id= None, 
                    include_unmute= include_unmute,
                    mode= "all",
                    limit=100,
                    recently=recently,
                )
                embed.add_field(
                    name= "",
                    value= "\n".join(results),
                    inline=False
                )

            else:
                if recently:
                    embed = discord.Embed(title=f"30天內 {user.display_name} 的禁言紀錄")
                else:
                    embed = discord.Embed(title=f"最近100筆 {user.display_name} 的禁言紀錄")

                results = await self.find_punishments_from_db(
                        interaction= interaction, 
                        guild_id= guild.id, 
                        user_id= user.id, 
                        include_unmute= include_unmute,
                        mode= "user",
                        limit=100,
                        recently=recently,
                    )
                
                embed.add_field(
                        name= user.display_name,
                        value= "\n".join(results),
                        inline=False
                    )
            await interaction.response.send_message(embed=embed, ephemeral=True)

        except Exception as e:
            embed = discord.Embed(title=f"查詢失敗!!", description=f"執行時失敗:{e}", color=discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)



    
    async def find_punishments_from_db(
        self,
        interaction: discord.Interaction,
        guild_id: int,
        user_id: int,
        limit: int,
        include_unmute: bool,
        mode: str,
        recently: bool
    ) -> list:
        """ 
        從資料庫查詢禁言紀錄
           
        回傳:  f"{何時}: 因 {甚麼原因}  被  {哪個管理員}  禁言  {多久}" 
        """
        results = []
        try:
            now = datetime.now(ZoneInfo(cfg["timezone"]))
            UNIXNOW = int(now.timestamp())

            if mode == "user":  # 會根據指定用戶查詢
                if recently:
                    punishments = await self.bot.db_manager.list_punishments(
                        guild_id=guild_id,
                        user_id=user_id,
                        ptype="mute",
                        start_ts=UNIXNOW - 2592000
                    )
                else:
                    punishments = await self.bot.db_manager.list_punishments(
                        guild_id=guild_id,
                        user_id=user_id,
                        ptype="mute",
                        limit=limit
                    )
            else: # 查詢所有用戶紀錄
                if recently:
                    punishments = await self.bot.db_manager.list_punishments(
                        guild_id=guild_id,
                        ptype="mute",
                        start_ts=UNIXNOW - 2592000
                    )
                else:
                    punishments = await self.bot.db_manager.list_punishments(
                        guild_id=guild_id,
                        ptype="mute",
                        limit=limit
                    )


            for p in punishments:
                punished_at = p["punished_at"]
                dt = datetime.fromtimestamp(punished_at, ZoneInfo(cfg["timezone"])).strftime("%Y-%m-%d %H:%M:%S")
                reason = p["reason"]
                duration = p["duration"]
                admin_id = p["admin_id"]
                admin_member = interaction.guild.get_member(admin_id)
                user_id = p["user_id"]
                user = interaction.guild.get_member(user_id)
                user_str = f"\n⮑{user.display_name}" if mode == "all" else ""
                
                if admin_member:
                    admin = admin_member.display_name
                else:
                    admin = f"ID: {admin_id}"

                if duration > 0:
                    duration_str = self.get_durations_str(second=duration)
                    results.append(f"{dt}: {user_str} 因  {reason}  被  {admin}  禁言了  {duration_str}")
                elif include_unmute and duration == 0:
                    results.append(f"{dt}: {user_str} 因  {reason}  被  {admin}  解除禁言")                
                else:
                    continue

            return results

        except Exception:
            log.exception("查詢禁言紀錄失敗!!")
            return []

   
    def get_durations_str(self, second: int) -> str:
        try:
            # 將 int 秒數轉換為天、時、分
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
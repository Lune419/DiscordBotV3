import json
import logging
from typing import Optional, Any, List

import discord
from discord import app_commands
from discord.ext import commands, tasks

from utils.time_utils import now_with_unix
from zoneinfo import ZoneInfo
from datetime import datetime, time


log = logging.getLogger(__name__)

with open("config.json", "r", encoding="utf-8") as fp:
    cfg = json.load(fp)

class AntiDive(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db_manager = bot.db_manager
        self.guild_id = cfg["guild_id"]
        self.timezone = cfg["timezone"]
        self.daily_check_dive.start()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        if not message.guild:
            return

        _ , ts = now_with_unix(self.timezone)
        
        try:
            await self.db_manager.update_user_activity(
                guild_id=message.guild.id,
                user_id=message.author.id,
                message_time=ts
            )
            
        except Exception as _:
            log.exception(f"更新用戶活動時發生錯誤")
            
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return

        if not member.guild:
            return
        
        try:
            await self.db_manager.update_user_activity(
                guild_id=member.guild.id,
                user_id=member.id,
                message_time=0,
                voice_time=0,
            )
        except Exception as _:
            log.exception(f"更新用戶活動時發生錯誤")
            
    
    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState
    ):
        if member.bot:
            return

        if not member.guild:
            return

        _ , ts = now_with_unix(self.timezone)
        
        if before.channel is None and after.channel is not None:
            try:
                await self.db_manager.update_user_activity(
                    guild_id=member.guild.id,
                    user_id=member.id,
                    voice_time=ts
                )
            except Exception as _:
                log.exception(f"更新用戶活動時發生錯誤")
                
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.command(name="check_dive", description="列出所有潛水仔")
    async def check_dive(
        self,
        interaction: discord.Interaction,
        time: Optional[int] = None
    ) -> None:
        """列出所有潛水仔"""
        await interaction.response.defer(ephemeral=True)
    
        now, ts = now_with_unix(self.timezone)
        
        embed = discord.Embed(
            title="潛水仔列表",
            color=discord.Color.blue(),
            timestamp=now
        )
        
        search_time = ts - time if time else ts - 259200  # 如果沒有指定時間，預設為3天
        
        try:
            dive_users = await self.db_manager.get_inactive_users(
                guild_id=interaction.guild.id,
                message_threshold=search_time,
                voice_threshold=search_time,
                require_both=True
                )
            
            if not dive_users:
                embed.description = "目前沒有潛水仔"
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

            else:
                # 獲取伺服器成員信息，以便顯示用戶名
                guild = self.bot.get_guild(interaction.guild.id)
                
                # 建立描述文字
                description_lines = [f"找到 **{len(dive_users)}** 名潛水仔（超過 {time // 86400 if time else 3} 天未活動）：\n"]
                
                # 按照最後活動時間排序（最久沒活動的在最上面）
                dive_users_sorted = sorted(dive_users, key=lambda user: max(user["last_message_time"] or 0, user["last_voice_time"] or 0))
                
                for user in dive_users_sorted:
                    user_id = user["user_id"]
                    member = guild.get_member(user_id) if guild else None
                    
                    # 計算最後活動時間 (取最近的訊息或語音時間)
                    last_message = user["last_message_time"] or 0
                    last_voice = user["last_voice_time"] or 0
                    last_activity = max(last_message, last_voice)
                    
                    # 格式化用戶資料 - 如果是初始值1則顯示沒有聊天紀錄
                    activity_text = "沒有聊天紀錄" if last_activity == 1 else f"<t:{last_activity}:R>"
                    
                    if member:
                        user_line = f"• <@{user_id}> ({member.display_name}) - 最後活動: {activity_text}"
                    else:
                        user_line = f"• <@{user_id}> (已離開伺服器) - 最後活動: {activity_text}"
                    
                    description_lines.append(user_line)
                
                # 當潛水仔太多，可能會超過 Discord 的 description 長度限制 (4096 字元)
                # 因此需要分割成多個 embed
                full_description = "\n".join(description_lines)
                
                # 檢查是否超過單一 embed description 上限
                if len(full_description) <= 4000:
                    embed.description = full_description
                    await interaction.followup.send(embed=embed, ephemeral=True)
                else:
                    # 如果太長，分割成多個 embed
                    chunks = []
                    current_chunk = description_lines[0]  # 開頭描述
                    
                    for line in description_lines[1:]:
                        if len(current_chunk) + len(line) + 1 > 4000:  # +1 是換行符
                            chunks.append(current_chunk)
                            current_chunk = line
                        else:
                            current_chunk += "\n" + line
                    
                    if current_chunk:
                        chunks.append(current_chunk)
                    
                    # 發送第一個 embed
                    embed.description = chunks[0]
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    
                    # 發送其他 embed (如果有的話)
                    for i, chunk in enumerate(chunks[1:], 1):
                        follow_embed = discord.Embed(
                            title=f"潛水仔列表 (續 {i})",
                            description=chunk,
                            color=discord.Color.blue(),
                            timestamp=now
                        )
                        await interaction.followup.send(embed=follow_embed, ephemeral=True)
                
        except Exception as e:
            log.exception(f"獲取潛水仔時發生錯誤: {e}")
            embed.description = f"獲取潛水仔時發生錯誤: {e}"
            await interaction.followup.send(embed=embed, ephemeral=True)
                
    @check_dive.autocomplete("time")
    async def check_dive_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str
    ) -> List[app_commands.Choice[int]]:
        options = [
            app_commands.Choice(name="3天", value=259200),
            app_commands.Choice(name="5天", value=432000),
            app_commands.Choice(name="7天", value=604800),
            app_commands.Choice(name="14天", value=1209600),
            app_commands.Choice(name="30天", value=2592000),
        ]
        
        # 如果使用者輸入了搜尋文字，則過濾選項
        if current:
            filtered_options = [
                option for option in options 
                if current.lower() in option.name.lower() or current.lower() in str(option.value)
            ]
            return filtered_options
        
        # 如果沒有輸入，返回所有選項
        return options
    
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.command(name="check_last_message", description="查詢最後發言時間")
    async def check_last_message(
        self,
        interaction: discord.Interaction,
        user: discord.User
    ) -> None:
        """查詢指定用戶的最後發言時間"""
        await interaction.response.defer(ephemeral=True)
        
        now, ts = now_with_unix(self.timezone)
        
        try:
            # 從資料庫獲取用戶活動記錄
            activities = await self.db_manager.get_user_activity(
                guild_id=interaction.guild.id,
                user_id=user.id
            )
            
            embed = discord.Embed(
                title=f"用戶活動記錄",
                color=discord.Color.blue(),
                timestamp=now
            )
            embed.set_author(name=user.display_name, icon_url=user.display_avatar.url)
            embed.set_thumbnail(url=user.display_avatar.url)
            
            if not activities:
                embed.description = f"找不到 {user.mention} 的活動記錄"
                embed.color = discord.Color.red()
            else:
                activity = activities[0]  # 由於按用戶ID查詢，應該只有一條記錄
                
                # 取得最後訊息和語音時間
                last_message_time = activity["last_message_time"]
                last_voice_time = activity["last_voice_time"]
                
                # 計算最後活動時間 (取訊息和語音中較近的一個)
                last_activity_time = max(
                    last_message_time or 0,
                    last_voice_time or 0
                )
                
                # 添加用戶基本信息
                member = interaction.guild.get_member(user.id)
                user_since = int(user.created_at.timestamp())
                
                embed.add_field(
                    name="用戶資料",
                    value=f"**ID:** {user.id}\n**建立於:** <t:{user_since}:F> (<t:{user_since}:R>)",
                    inline=False
                )
                
                if member:
                    joined_at = int(member.joined_at.timestamp()) if member.joined_at else None
                    if joined_at:
                        embed.add_field(
                            name="伺服器資料",
                            value=f"**加入於:** <t:{joined_at}:F> (<t:{joined_at}:R>)",
                            inline=False
                        )
                
                # 顯示各種活動時間
                activity_details = []
                
                if last_message_time and last_message_time != 1:
                    activity_details.append(f"**最後發言:** <t:{last_message_time}:F> (<t:{last_message_time}:R>)")
                elif last_message_time == 1:
                    activity_details.append("**最後發言:** 沒有聊天紀錄")
                else:
                    activity_details.append("**最後發言:** 無紀錄")
                    
                if last_voice_time and last_voice_time != 1:
                    activity_details.append(f"**最後語音:** <t:{last_voice_time}:F> (<t:{last_voice_time}:R>)")
                elif last_voice_time == 1:
                    activity_details.append("**最後語音:** 沒有聊天紀錄")
                else:
                    activity_details.append("**最後語音:** 無紀錄")
                    
                if last_activity_time > 1:  # 大於1才顯示時間戳
                    activity_details.append(f"**最後活動:** <t:{last_activity_time}:F> (<t:{last_activity_time}:R>)")
                    
                    # 計算不活躍天數
                    inactive_days = (ts - last_activity_time) // 86400
                    if inactive_days > 0:
                        activity_details.append(f"**已不活躍:** {inactive_days} 天")
                        
                        # 根據不活躍時間設置顏色
                        if inactive_days >= 30:
                            embed.color = discord.Color.red()
                        elif inactive_days >= 14:
                            embed.color = discord.Color.orange()
                        elif inactive_days >= 7:
                            embed.color = discord.Color.yellow()
                elif last_activity_time == 1:
                    activity_details.append("**最後活動:** 沒有聊天紀錄")
                    embed.color = discord.Color.dark_gray()
                else:
                    activity_details.append("**最後活動:** 無紀錄")
                    embed.color = discord.Color.dark_gray()
                    
                embed.add_field(
                    name="活動資料",
                    value="\n".join(activity_details),
                    inline=False
                )
                    
            await interaction.followup.send(embed=embed, ephemeral=True)
                
        except Exception as e:
            log.exception(f"獲取用戶活動記錄時發生錯誤: {e}")
            embed = discord.Embed(
                title="錯誤",
                description=f"獲取用戶活動記錄時發生錯誤: {e}",
                color=discord.Color.red(),
                timestamp=now
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            
    @tasks.loop(time=time(hour=15,minute=29, tzinfo=ZoneInfo(cfg["timezone"])))
    async def daily_check_dive(self):
        """每日自動檢查潛水仔"""
        now, ts = now_with_unix(self.timezone)
        
        try:
            # 遍歷機器人所在的所有伺服器
            for guild in self.bot.guilds:
                try:
                    # 獲取每個伺服器的設定
                    settings = await self.db_manager.get_settings(guild.id)
                    
                    # 如果沒有設定或沒有設定反潛水頻道，則跳過該伺服器
                    if not settings or not settings["anti_dive_channel"]:
                        log.info(f"伺服器 {guild.name} ({guild.id}) 未設定反潛水頻道，跳過")
                        continue
                        
                    # 獲取反潛水通知頻道
                    anti_dive_channel = guild.get_channel(settings["anti_dive_channel"])
                    if not anti_dive_channel or not isinstance(anti_dive_channel, discord.TextChannel):
                        log.error(f"伺服器 {guild.name} ({guild.id}) 找不到反潛水頻道或權限不足: {settings['anti_dive_channel']}")
                        continue
                        
                    # 預設檢查 3 天未活動的用戶
                    search_time = ts - 259200  # 3天
                    
                    # 獲取潛水仔列表
                    dive_users = await self.db_manager.get_inactive_users(
                        guild_id=guild.id,
                        message_threshold=search_time,
                        voice_threshold=search_time,
                        require_both=True
                    )
                    
                    if not dive_users:
                        # 如果沒有潛水仔，發送簡單通知
                        embed = discord.Embed(
                            title="每日潛水仔報告",
                            description="今日沒有發現潛水仔",
                            color=discord.Color.green(),
                            timestamp=now
                        )
                        embed.set_footer(text=f"伺服器: {guild.name} | ID: {guild.id}")
                        await anti_dive_channel.send(embed=embed)
                        log.info(f"伺服器 {guild.name} ({guild.id}) 今日沒有潛水仔")
                        continue
                        
                    log.info(f"伺服器 {guild.name} ({guild.id}) 今日發現 {len(dive_users)} 名潛水仔")
                    
                    # 準備潛水仔報告
                    embed = discord.Embed(
                        title="每日潛水仔報告",
                        color=discord.Color.blue(),
                        timestamp=now
                    )
                    embed.set_footer(text=f"伺服器: {guild.name} | ID: {guild.id}")
                    
                    # 建立描述文字
                    description_lines = [f"發現 **{len(dive_users)}** 名潛水仔（超過 3 天未活動）：\n"]
                    
                    # 按照最後活動時間排序（最久沒活動的在最上面）
                    dive_users_sorted = sorted(dive_users, key=lambda user: max(user["last_message_time"] or 0, user["last_voice_time"] or 0))
                    
                    for user in dive_users_sorted:
                        user_id = user["user_id"]
                        member = guild.get_member(user_id)
                        
                        # 計算最後活動時間 (取最近的訊息或語音時間)
                        last_message = user["last_message_time"] or 0
                        last_voice = user["last_voice_time"] or 0
                        last_activity = max(last_message, last_voice)
                        
                        # 格式化用戶資料 - 如果是初始值1則顯示沒有聊天紀錄
                        activity_text = "沒有聊天紀錄" if last_activity == 1 else f"<t:{last_activity}:R>"
                        
                        if member:
                            user_line = f"• <@{user_id}> ({member.display_name}) - 最後活動: {activity_text}"
                        else:
                            user_line = f"• <@{user_id}> (已離開伺服器) - 最後活動: {activity_text}"
                        
                        description_lines.append(user_line)
                    
                    # 當潛水仔太多，可能會超過 Discord 的 description 長度限制 (4096 字元)
                    # 因此需要分割成多個 embed
                    full_description = "\n".join(description_lines)
                    
                    # 檢查是否超過單一 embed description 上限
                    if len(full_description) <= 4000:
                        embed.description = full_description
                        await anti_dive_channel.send(embed=embed)
                    else:
                        # 如果太長，分割成多個 embed
                        chunks = []
                        current_chunk = description_lines[0]  # 開頭描述
                        
                        for line in description_lines[1:]:
                            if len(current_chunk) + len(line) + 1 > 4000:  # +1 是換行符
                                chunks.append(current_chunk)
                                current_chunk = line
                            else:
                                current_chunk += "\n" + line
                        
                        if current_chunk:
                            chunks.append(current_chunk)
                        
                        # 發送第一個 embed
                        embed.description = chunks[0]
                        await anti_dive_channel.send(embed=embed)
                        
                        # 發送其他 embed (如果有的話)
                        for i, chunk in enumerate(chunks[1:], 1):
                            follow_embed = discord.Embed(
                                title=f"每日潛水仔報告 (續 {i})",
                                description=chunk,
                                color=discord.Color.blue(),
                                timestamp=now
                            )
                            follow_embed.set_footer(text=f"伺服器: {guild.name} | ID: {guild.id}")
                            await anti_dive_channel.send(embed=follow_embed)
                
                except Exception as e:
                    log.exception(f"處理伺服器 {guild.name} ({guild.id}) 的潛水仔報告時發生錯誤: {e}")
                    # 繼續處理下一個伺服器，不因一個伺服器的錯誤而中斷整個流程
                    continue
            
        except Exception as e:
            log.exception(f"每日檢查潛水仔時發生錯誤: {e}")
            
            
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.command(name="init_anti_dive", description="初始化反潛水系統")
    async def init_anti_dive(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        now, ts = now_with_unix(self.timezone)
        
        initialized_count = 0
        skipped_count = 0
        
        for member in interaction.guild.members:
            if member.bot:
                continue
            
            try:
                # 先檢查用戶是否已有活動記錄
                activities = await self.db_manager.get_user_activity(
                    guild_id=interaction.guild.id,
                    user_id=member.id
                )
                
                # 如果使用者已有活動記錄，且不是預設值 1（表示已經有真實活動）
                if activities and (
                    (activities[0]["last_message_time"] is not None and activities[0]["last_message_time"] != 1) or 
                    (activities[0]["last_voice_time"] is not None and activities[0]["last_voice_time"] != 1)
                ):
                    # 跳過該用戶，不覆蓋已有的資料
                    skipped_count += 1
                    continue
                
                # 如果用戶沒有活動記錄或只有初始值，則將它設為初始值 1
                await self.db_manager.update_user_activity(
                    guild_id=interaction.guild.id,
                    user_id=member.id,
                    message_time=1,
                    voice_time=1
                )
                initialized_count += 1
                
            except Exception as e:
                log.exception(f"初始化用戶 {member.id} 活動時發生錯誤: {e}")
        
        # 回報處理結果
        embed = discord.Embed(
            title="反潛水系統初始化",
            description=f"已完成反潛水系統的初始化",
            color=discord.Color.green(),
            timestamp=now
        )
        
        embed.add_field(
            name="處理結果",
            value=f"👥 已初始化: {initialized_count} 名成員\n⏭️ 已跳過: {skipped_count} 名成員",
            inline=False
        )
        
        embed.set_footer(text=f"伺服器: {interaction.guild.name}")
        
        await interaction.followup.send(embed=embed, ephemeral=True)
        
async def setup(bot: commands.Bot):
    await bot.add_cog(AntiDive(bot))
    log.info("AntiDive 擴展已載入")
import asyncio
import json
import logging

import discord
from discord import app_commands, utils
from discord.ext import commands
from zoneinfo import ZoneInfo

from utils.time_utils import now_with_unix

with open("config.json", "r", encoding="utf-8") as fp:
    cfg = json.load(fp)
    
log = logging.getLogger(__name__)

NOTIFY_CHANNEL = "notify_channel"
MEMBER_LOG_CHANNEL = "member_log_channel"
DEFAULT_TIME_WINDOW = 15

class _EventLoggerSender():
    def __init__(self, bot):
        self.bot = bot
        self.db_manager = bot.db_manager
        self.guild_id = cfg["guild_id"]
        self.timezone = cfg["timezone"]
        
    async def get_log_channel(self, guild_id: int, log_type: str) -> discord.TextChannel | None:
        """獲取日誌頻道"""
        settings = await self.bot.db_manager.get_settings(guild_id)
        if not settings:
            return None
        
        try:
            channel_id = settings[log_type]
            if not channel_id:
                return None
        except (KeyError, IndexError):
            return None
    
        log_channel = self.bot.get_channel(channel_id)
        if not log_channel or not isinstance(log_channel, discord.TextChannel):
            return None
    
        return log_channel
    
    async def log_event(self, guild: discord.Guild, user: discord.User, event_type: str, event_time: float):
        """記錄事件到資料庫"""
        try:
            await self.db_manager.add_event(
                guild_id=guild.id,
                user_id=user.id,
                event_type=event_type,
                event_time=event_time
            )
        except Exception as _:
            log.exception(f"記錄事件時發生錯誤")
        

class ImportantLogger(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_manager = bot.db_manager
        self.guild_id = cfg["guild_id"]
        self.timezone = cfg["timezone"]
        self.event_logger_sender = _EventLoggerSender(bot)

    async def create_user_action_embed(self, *, title: str, description: str, user: discord.abc.User, executor: discord.abc.User = None, reason: str = None, color: discord.Color = discord.Color.red()) -> discord.Embed:
        """建立共用的用戶動作嵌入訊息"""
        now, _ = now_with_unix(self.timezone)
        embed = discord.Embed(title=title, description=description, color=color, timestamp=now)
        if executor:
            embed.add_field(name="執行者", value=f"{executor.mention}({executor.display_name}｜{executor.id})", inline=False)
        embed.add_field(name="原因", value=reason if reason else "未提供原因", inline=False)
        embed.set_author(name=user.display_name, icon_url=user.display_avatar.url)
        return embed
    
    async def get_audit_log_info(self, 
                            guild: discord.Guild, 
                            target_id: int, 
                            action: discord.AuditLogAction = discord.AuditLogAction.kick,
                            time_window: int = DEFAULT_TIME_WINDOW ) -> tuple[bool, discord.User | None, str | None]:
        """
        查詢審核日誌資訊
    
        Args:
            guild: 伺服器
            target_id: 目標成員ID
            action: 審核日誌動作類型 (預設為踢出)
            time_window: 時間窗口 (秒，預設為120秒)
    
        Returns:
            tuple: (是否找到匹配記錄, 執行者, 原因)
        """
        try:
            demand_time = discord.utils.utcnow().timestamp() - time_window
            
            async for entry in guild.audit_logs(limit=5, action=action):
                try:
                    # 獲取目標ID的通用方法
                    entry_target_id = None
                    
                    if isinstance(entry.target, (discord.Member, discord.User)):
                        entry_target_id = entry.target.id
                    elif isinstance(entry.target, int):
                        entry_target_id = entry.target
                    else:
                        # 嘗試從對象獲取ID
                        entry_target_id = getattr(entry.target, 'id', None)
                    
                    if entry_target_id is None:
                        log.debug(f"無法從審核日誌條目中提取目標ID，類型: {type(entry.target)}")
                        continue
                        
                    # 檢查是否匹配目標ID
                    if entry_target_id == target_id:
                        # 檢查時間戳是否在有效範圍內
                        entry_time = entry.created_at.timestamp()
                        if entry_time >= demand_time:
                            return True, entry.user, entry.reason
                except Exception as e:
                    log.warning(f"處理審核日誌條目時發生錯誤: {e}", exc_info=True)
                    continue
            
            # 如果沒找到相符的審核日誌
            return False, None, None
                
        except discord.Forbidden:
            log.error(f"無法存取 {guild.name} 的審核日誌。請檢查機器人權限。")
            return False, None, None
        
        except Exception as e:
            log.error(f"在檢查 {guild.name} 的審核日誌時發生錯誤: {e}", exc_info=True)
            return False, None, None

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        """處理成員離開事件，包含踢出和自行離開"""
        try:
            is_kicked, kicker, kick_reason = await self.get_audit_log_info(
                guild=member.guild,
                target_id=member.id,
                action=discord.AuditLogAction.kick,
                time_window=DEFAULT_TIME_WINDOW
            )
            
            now, ts = now_with_unix(self.timezone)
            if is_kicked:
                log_channel = await self.event_logger_sender.get_log_channel(member.guild.id, NOTIFY_CHANNEL)
                
                if log_channel:
                    embed = await self.create_user_action_embed(
                        title="成員被踢出",
                        description=f"{member.mention} ({member.display_name}｜{member.id}) 被踢出伺服器",
                        user=member,
                        executor=kicker,
                        reason=kick_reason,
                        color=discord.Color.orange()
                    )
                    embed.add_field(
                        name="成員資訊",
                        value=f"Discord 帳號建立時間: <t:{int(member.created_at.timestamp())}:R>\n"
                              f"加入伺服器時間: <t:{int(member.joined_at.timestamp())}:R> \n" if member.joined_at else "加入時間未知\n"
                              f"目前伺服器成員數: {member.guild.member_count}\n",
                        inline=False
                    )
                    await log_channel.send(embed=embed)
                    
            else:
                log_channel = await self.event_logger_sender.get_log_channel(member.guild.id, MEMBER_LOG_CHANNEL)
                
                try:
                    await self.event_logger_sender.log_event(
                        guild=member.guild,
                        user=member,
                        event_type="member_leave",
                        event_time=ts)
                except Exception as _:
                    log.exception(f"記錄成員離開事件時發生錯誤")
                
                if log_channel:
                    embed = discord.Embed(
                        title="成員退出",
                        description=f"{member.mention} ({member.display_name}｜{member.id}) 離開了伺服器",
                        color=discord.Color.red(),
                        timestamp=now
                    )
                    embed.add_field(
                        name="成員資訊",
                        value=f"Discord 帳號建立時間: <t:{int(member.created_at.timestamp())}:R>\n"
                              f"加入伺服器時間: <t:{int(member.joined_at.timestamp())}:R>\n"
                              f"目前伺服器成員數: {member.guild.member_count}\n",
                        inline=False
                    )
                    embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
                    await log_channel.send(embed=embed)
                    
        except Exception as e:
            log.error(f"處理 on_member_remove 事件時發生錯誤: {e}", exc_info=True)

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User, ban_reason: str | None = None):
        """處理成員被封禁事件"""
        try:
            now, _ = now_with_unix(self.timezone)
            log_channel = await self.event_logger_sender.get_log_channel(guild.id, NOTIFY_CHANNEL)
            _, banner, ban_reason = await self.get_audit_log_info(
                guild=guild,
                target_id=user.id,
                action=discord.AuditLogAction.ban,
                time_window=DEFAULT_TIME_WINDOW
            )
            if log_channel:
                embed = await self.create_user_action_embed(
                    title="成員被封禁",
                    description=f"{user.mention} ({user.display_name}｜{user.id}) 被封禁",
                    user=user,
                    executor=banner,
                    reason=ban_reason,
                    color=discord.Color.red()
                )
                await log_channel.send(embed=embed)
        except Exception as e:
            log.error(f"處理 on_member_ban 事件時發生錯誤: {e}", exc_info=True)

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        """處理成員被解除封禁事件"""
        try:
            now, _ = now_with_unix(self.timezone)
            log_channel = await self.event_logger_sender.get_log_channel(guild.id, NOTIFY_CHANNEL)
            _, unbanner, unban_reason = await self.get_audit_log_info(
                guild=guild,
                target_id=user.id,
                action=discord.AuditLogAction.unban,
                time_window=DEFAULT_TIME_WINDOW
            )
            if log_channel:
                embed = await self.create_user_action_embed(
                    title="成員被解除封禁",
                    description=f"{user.mention} ({user.display_name}｜{user.id}) 被解除封禁",
                    user=user,
                    executor=unbanner,
                    reason=unban_reason,
                    color=discord.Color.green()
                )
                await log_channel.send(embed=embed)
        except Exception as e:
            log.error(f"處理 on_member_unban 事件時發生錯誤: {e}", exc_info=True)
            
    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after :discord.Member):
        """處理禁言事件"""
        try:
            before_timeout = getattr(before, "timed_out_until", None)
            after_timeout = getattr(after, "timed_out_until", None)
            
            now, _ = now_with_unix(self.timezone)
            log_channel = await self.event_logger_sender.get_log_channel(before.guild.id, NOTIFY_CHANNEL)
            if before_timeout != after_timeout:
                if (before_timeout is None or before_timeout < discord.utils.utcnow()) and (after_timeout and after_timeout > discord.utils.utcnow()):
                    if log_channel:
                        embed = discord.Embed(
                            title="成員被禁言",
                            description=f"{after.mention} ({after.display_name}｜{after.id}) 被禁言",
                            color=discord.Color.orange(),
                            timestamp=now
                        )
                        local_dt = after_timeout.astimezone(ZoneInfo(self.timezone))
                        embed.add_field(
                            name="禁言結束時間",
                            value=f"<t:{int(after_timeout.timestamp())}:F>",)
                        embed.set_author(name=after.display_name, icon_url=after.display_avatar.url)
                        await log_channel.send(embed=embed)
                elif (before_timeout and before_timeout > discord.utils.utcnow()) and (after_timeout is None or after_timeout < discord.utils.utcnow()):
                    if log_channel:
                        embed = discord.Embed(
                            title="成員解除禁言",
                            description=f"{after.mention} ({after.display_name}｜{after.id}) 被解除禁言",
                            color=discord.Color.green(),
                            timestamp=now
                        )
                        embed.set_author(name=after.display_name, icon_url=after.display_avatar.url)
                        await log_channel.send(embed=embed)

        except Exception as _:
            log.exception(f"處理 on_member_update 事件時發生錯誤")
            return
    
class MemberLogger(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_manager = bot.db_manager
        self.guild_id = cfg["guild_id"]
        self.timezone = cfg["timezone"]
        self.event_logger_sender = _EventLoggerSender(bot)
    
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """處理成員加入事件"""
        try:
            log_channel = await self.event_logger_sender.get_log_channel(member.guild.id, MEMBER_LOG_CHANNEL)
            now , ts = now_with_unix(self.timezone)
            await self.event_logger_sender.log_event(
                guild=member.guild,
                user=member,
                event_type="member_join",
                event_time=ts
            )
            
        except Exception as _:
            log.exception(f"處理 on_member_join 事件時發生錯誤")
            return
        
        try:
            if log_channel:
                embed = discord.Embed(
                    title="成員加入",
                    description=f"{member.mention} ({member.display_name}｜{member.id}) 加入了伺服器",
                    color=discord.Color.green(),
                    timestamp=now
                )
                embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
                embed.add_field(
                    name="成員資訊",
                    value=f"Discord 帳號建立時間: <t:{int(member.created_at.timestamp())}:R>\n"
                          f"目前伺服器成員數: {member.guild.member_count}\n",
                    inline=False
                )
                await log_channel.send(embed=embed)
                
        except Exception as _:
            log.exception(f"發送成員加入事件時發生錯誤")
            return

                
async def setup(bot: commands.Bot) -> None:
    """載入擴充"""
    await bot.add_cog(ImportantLogger(bot))
    log.info("ImportantLogger 擴充已載入")
    await bot.add_cog(MemberLogger(bot))  # 加入這行
    log.info("MemberLogger 擴充已載入")
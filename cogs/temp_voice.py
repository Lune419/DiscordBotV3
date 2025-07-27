import re
import discord
import os
from discord.ext import commands
from discord import app_commands
from typing import Optional, List
import aiosqlite
import asyncio
import json
import logging
from datetime import datetime

from utils.Temp_vioce_database import TempVoiceDatabase
from utils.time_utils import now_with_unix

log = logging.getLogger(__name__)

with open("config.json", "r", encoding="utf-8") as f:
    cfg = json.load(f)

class TemplateFormatter:
    """處理語音頻道名稱模板的格式化"""
    
    @staticmethod
    def format_template(template: str, member: discord.Member, **extra_vars) -> str:
        """
        格式化頻道名稱模板
        
        可用的預設變數:
        - {user}: 使用者的名稱 (不含標籤)
        - {user_displayname}: 使用者的顯示名稱
        
        額外變數可透過 extra_vars 參數傳入
        """
        if not template:
            return f"{member.display_name} 的頻道"
            
        # 準備基本變數
        variables = {
            "user": member.name,
            "user_displayname": member.display_name
        }
        
        # 添加額外變數
        variables.update(extra_vars)
        
        # 使用正則表達式尋找並替換所有變數
        def replace_var(match):
            var_name = match.group(1)
            if var_name in variables:
                return str(variables[var_name])
            return match.group(0)  # 如果找不到變數，保留原始文本
            
        # 替換變數
        result = re.sub(r'\{([a-zA-Z0-9_]+)\}', replace_var, template)
        
        # 確保頻道名稱不超過100個字元 (Discord 限制)
        if len(result) > 100:
            result = result[:97] + "..."
            
        return result
    
class TempVoice(commands.Cog):
    """臨時語音頻道"""
    def __init__(self, bot: commands.Bot, db_path):
        self.bot = bot
        self.TemplateFormatter = TemplateFormatter
        self.TempVoiceDatabase = TempVoiceDatabase(db_path)
        self.panel = None
        self.cleanup_task = None
    
    async def create_child_channel(self, *, parent_channel: discord.VoiceChannel, member: discord.Member) -> discord.VoiceChannel:
        """創建一個新的子頻道"""
        parent_channel_info = await self.TempVoiceDatabase.get_parent_channel(parent_channel.id)
        if not parent_channel_info:
            return None
        
        template = parent_channel_info['template'] if parent_channel_info['template'] else None
        category_id = parent_channel_info['category_id'] if parent_channel_info['category_id'] else None
        
        # 獲取類別對象
        category = None
        if category_id:
            category = parent_channel.guild.get_channel(category_id)
        
        # 格式化頻道名稱
        channel_name = self.TemplateFormatter.format_template(template, member)
        
        # 複製母頻道的權限設定
        overwrites = parent_channel.overwrites.copy()
        
        # 給頻道創建者添加管理權限
        if member not in overwrites:
            overwrites[member] = discord.PermissionOverwrite()
        
        overwrites[member].connect = True
        overwrites[member].mute_members = True
        overwrites[member].deafen_members = True
        overwrites[member].move_members = True
        overwrites[member].manage_channels = True
        
        # 確保機器人有在語音頻道中發送訊息的權限
        bot_member = parent_channel.guild.me
        if bot_member not in overwrites:
            overwrites[bot_member] = discord.PermissionOverwrite()
        
        overwrites[bot_member].send_messages = True
        overwrites[bot_member].embed_links = True
        overwrites[bot_member].attach_files = True
        overwrites[bot_member].read_message_history = True
        overwrites[bot_member].use_external_emojis = True
        
        # 創建新頻道
        new_channel = await parent_channel.guild.create_voice_channel(
            name=channel_name,
            category=category or parent_channel.category,  # 如果沒有指定類別，使用與母頻道相同的類別
            overwrites=overwrites,
            bitrate=parent_channel.bitrate,
            user_limit=parent_channel.user_limit,
            rtc_region=parent_channel.rtc_region,
            video_quality_mode=parent_channel.video_quality_mode,
        )
        
        # 將子頻道添加到資料庫
        await self.TempVoiceDatabase.add_child_channel(
            guild_id=parent_channel.guild.id,
            parent_channel_id=parent_channel.id,
            channel_id=new_channel.id,
            owner_id=member.id
        )
        
        # 如果用戶當前在母頻道中，將他移動到新建立的子頻道
        if member.voice and member.voice.channel and member.voice.channel.id == parent_channel.id:
            try:
                await member.move_to(new_channel)
            except discord.HTTPException:
                # 如果移動失敗，記錄但不中斷流程
                log.warning(f"無法將用戶 {member.display_name} 移動到新建立的子頻道")
        
        return new_channel

    async def delete_child_channel(self, channel: discord.VoiceChannel):
        """刪除子頻道"""
        try:
            # 從資料庫移除記錄
            await self.TempVoiceDatabase.delete_child_channel(channel.id)
            # 刪除頻道
            await channel.delete(reason="臨時語音頻道自動清理")
            log.info(f"已刪除子頻道: {channel.name} ({channel.id})")
        except discord.HTTPException:
            log.warning(f"無法刪除頻道: {channel.name} ({channel.id})")
        except Exception as e:
            log.exception(f"刪除子頻道時發生錯誤: {e}")

    async def send_control_panel(self, channel: discord.VoiceChannel, owner: discord.Member):
        """發送控制面板到語音頻道的內置文字聊天"""
        try:
            # 獲取子頻道信息
            child_info = await self.TempVoiceDatabase.get_child_channel(channel.id)
            if not child_info:
                return None
            
            # 創建控制面板視圖和嵌入
            view = VoiceChannelControlView(channel, owner.id, self)
            embed = await view.create_panel_embed(channel, owner, child_info['created_at'])
            
            # 直接發送到語音頻道的內置文字聊天
            try:
                message = await channel.send(
                    embed=embed, 
                    view=view
                )
                
                # 更新資料庫中的控制面板訊息ID
                await self.TempVoiceDatabase.update_control_message(channel.id, message.id)
                
                return message
                
            except discord.Forbidden:
                log.warning(f"無法在語音頻道 {channel.name} 中發送控制面板：權限不足")
                return None
            except discord.HTTPException as e:
                log.error(f"發送控制面板時發生 HTTP 錯誤: {e}")
                return None
            
        except Exception as e:
            log.exception(f"發送控制面板時發生錯誤: {e}")
            return None

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        """監聽語音狀態更新事件"""
        # 處理用戶進入母頻道的情況
        if after.channel and before.channel != after.channel:
            is_parent = await self.TempVoiceDatabase.is_parent_channel(after.channel.id)
            if is_parent:
                try:
                    # 創建子頻道
                    new_channel = await self.create_child_channel(parent_channel=after.channel, member=member)
                    if new_channel:
                        # 短暫延遲後移動用戶到新頻道
                        await asyncio.sleep(0.5)
                        if member.voice and member.voice.channel and member.voice.channel.id == after.channel.id:
                            await member.move_to(new_channel)
                        
                        # 發送控制面板
                        await self.send_control_panel(new_channel, member)
                        
                except Exception as e:
                    log.exception(f'創建子頻道時發生錯誤: {e}')
        
        # 處理用戶離開子頻道的情況
        if before.channel and after.channel != before.channel:
            is_child = await self.TempVoiceDatabase.is_child_channel(before.channel.id)
            if is_child:
                # 檢查頻道是否為空
                if len(before.channel.members) == 0:
                    # 頻道為空，刪除它
                    await self.delete_child_channel(before.channel)
                else:
                    # 檢查擁有者是否離開了子頻道（而不是移動到其他頻道）
                    child_info = await self.TempVoiceDatabase.get_child_channel(before.channel.id)
                    if child_info and child_info['owner_id'] == member.id:
                        # 確保擁有者真的離開了，而不是斷線重連或其他原因
                        if not after.channel or after.channel.id != before.channel.id:
                            # 擁有者離開了且頻道不為空，發送繼承按鈕
                            await self.send_inheritance_panel(before.channel, child_info)

    async def send_inheritance_panel(self, channel: discord.VoiceChannel, child_info):
        """發送頻道繼承面板到語音頻道內"""
        try:
            if not channel.members:
                # 如果頻道已經空了，直接刪除
                await self.delete_child_channel(channel)
                return
            
            # 創建繼承視圖
            view = ChannelInheritanceView(channel, self)
            
            embed = discord.Embed(
                title="🔄 頻道擁有權轉移",
                description=f"頻道擁有者已離開此頻道\n在場的任何成員都可以點擊下方按鈕來繼承頻道擁有權",
                color=discord.Color.orange()
            )
    
            # 直接發送到語音頻道的內置文字聊天
            try:
                inheritance_message = await channel.send(embed=embed, view=view)
                # 將訊息引用存儲到 View 中，以便後續刪除
                view.inheritance_message = inheritance_message
            except discord.Forbidden:
                log.warning(f"無法在語音頻道 {channel.name} 中發送繼承面板：權限不足")
            except discord.HTTPException as e:
                log.error(f"發送繼承面板時發生 HTTP 錯誤: {e}")
            
        except Exception as e:
            log.exception(f"發送繼承面板時發生錯誤: {e}")                    
                
            
    @app_commands.command(name="set_mother_channel", description="設定母頻道")
    @app_commands.describe(
        channel="要設置為母頻道的語音頻道",
        category="選擇一個類別 (可選)",
        template="頻道名稱模板 (可選)"
    )
    @app_commands.checks.has_permissions(manage_channels=True)
    async def set_mother_channel(
        self,
        interaction: discord.Interaction,
        channel: discord.VoiceChannel,
        category: Optional[discord.CategoryChannel] = None,
        template: Optional[str] = None
    ):
        """設置一個語音頻道為母頻道"""
        await interaction.response.defer(thinking=True,ephemeral=True)
        
        is_parent = await self.TempVoiceDatabase.is_parent_channel(channel.id)
        
        # 檢查是否已經是母頻道
        if is_parent:
            try:
                await self.TempVoiceDatabase.update_parent_channel(channel_id=channel.id,
                                                                   category_id=category.id if category else None,
                                                                    template=template)
                await interaction.followup.send(f"{channel.mention} 已更新母頻道")
            except Exception as _:
                log.exception("更新母頻道時發生錯誤")
        else:
            try:
                await self.TempVoiceDatabase.add_parent_channel(
                    guild_id=interaction.guild.id,
                    channel_id=channel.id,
                    category_id=category.id if category else None,
                    template=template
                )
                
                embed = discord.Embed(
                    title="母頻道設定成功",
                    description=f"已將 {channel.mention} 設定為母頻道",
                    color=discord.Color.green()
                )
                
                await interaction.followup.send(embed=embed)
            except Exception as _:
                log.exception("設置母頻道時發生錯誤")
                await interaction.followup.send("設置母頻道時發生錯誤，請稍後再試。", ephemeral=True)
                
    @app_commands.command(name="remove_mother_channel", description="移除母頻道")
    @app_commands.describe(channel="要移除的母頻道")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def remove_mother_channel(self, interaction: discord.Interaction, channel: discord.VoiceChannel):
        """移除一個母頻道"""
        await interaction.response.defer(thinking=True, ephemeral=True)
        
        is_parent = await self.TempVoiceDatabase.is_parent_channel(channel.id)
        
        if not is_parent:
            await interaction.followup.send(f"{channel.mention} 不是一個母頻道", ephemeral=True)
            return
        
        try:
            await self.TempVoiceDatabase.delete_parent_channel(channel.id)
            embed = discord.Embed(
                title="母頻道移除成功",
                description=f"已將 {channel.mention} 從母頻道列表中移除",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed)
            
        except Exception as _:
            log.exception("移除母頻道時發生錯誤")
            await interaction.followup.send("移除母頻道時發生錯誤，請稍後再試。", ephemeral=True)

    @app_commands.command(name="temp_voice_info", description="查看臨時語音頻道信息")
    async def temp_voice_info(self, interaction: discord.Interaction):
        """查看當前伺服器的臨時語音頻道設定"""
        await interaction.response.defer(ephemeral=True)
        
        try:
            # 獲取母頻道
            parent_channels = await self.TempVoiceDatabase.get_parent_channels_by_guild(interaction.guild.id)
            
            # 獲取子頻道
            child_channels = await self.TempVoiceDatabase.get_child_channels_by_guild(interaction.guild.id)
            
            embed = discord.Embed(
                title="🎛️ 臨時語音頻道信息",
                color=discord.Color.blue()
            )
            
            if parent_channels:
                parent_list = []
                for parent in parent_channels:
                    channel = interaction.guild.get_channel(parent['channel_id'])
                    if channel:
                        template = parent['template'] or "預設模板"
                        parent_list.append(f"• {channel.mention} - `{template}`")
                    else:
                        parent_list.append(f"• 已刪除頻道 (ID: {parent['channel_id']})")
                
                embed.add_field(
                    name=f"🏠 母頻道 ({len(parent_channels)})",
                    value="\n".join(parent_list) if parent_list else "無",
                    inline=False
                )
            
            if child_channels:
                child_list = []
                for child in child_channels:
                    channel = interaction.guild.get_channel(child['channel_id'])
                    owner = interaction.guild.get_member(child['owner_id'])
                    if channel and owner:
                        child_list.append(f"• {channel.mention} - {owner.display_name}")
                    elif channel:
                        child_list.append(f"• {channel.mention} - 未知擁有者")
                    else:
                        child_list.append(f"• 已刪除頻道 (ID: {child['channel_id']})")
                
                # 限制顯示數量
                if len(child_list) > 10:
                    child_list = child_list[:10] + [f"... 還有 {len(child_list) - 10} 個"]
                
                embed.add_field(
                    name=f"📞 子頻道 ({len(child_channels)})",
                    value="\n".join(child_list) if child_list else "無",
                    inline=False
                )
            
            if not parent_channels and not child_channels:
                embed.description = "此伺服器尚未設定任何臨時語音頻道"
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            log.exception("獲取臨時語音頻道信息時發生錯誤")
            await interaction.followup.send("獲取信息時發生錯誤，請稍後再試。", ephemeral=True)

    @app_commands.command(name="force_cleanup", description="強制清理無效的臨時語音頻道記錄")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def force_cleanup(self, interaction: discord.Interaction):
        """強制清理無效的記錄"""
        await interaction.response.defer(ephemeral=True)
        
        try:
            cleaned_count = 0
            
            # 清理子頻道
            child_channels = await self.TempVoiceDatabase.get_child_channels_by_guild(interaction.guild.id)
            for child_info in child_channels:
                channel = interaction.guild.get_channel(child_info['channel_id'])
                if not channel:
                    await self.TempVoiceDatabase.delete_child_channel(child_info['channel_id'])
                    cleaned_count += 1
            
            # 清理母頻道
            parent_channels = await self.TempVoiceDatabase.get_parent_channels_by_guild(interaction.guild.id)
            for parent_info in parent_channels:
                channel = interaction.guild.get_channel(parent_info['channel_id'])
                if not channel:
                    await self.TempVoiceDatabase.delete_parent_channel(parent_info['channel_id'])
                    cleaned_count += 1
            
            embed = discord.Embed(
                title="🧹 清理完成",
                description=f"已清理 {cleaned_count} 個無效記錄",
                color=discord.Color.green()
            )
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            log.exception("強制清理時發生錯誤")
            await interaction.followup.send("清理時發生錯誤，請稍後再試。", ephemeral=True)

    @app_commands.command(name="admin_panel", description="開啟臨時語音頻道管理員控制面板")
    @app_commands.describe(channel="要管理的臨時語音頻道 (可選，不填則使用當前所在頻道)")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def admin_panel(self, interaction: discord.Interaction, channel: Optional[discord.VoiceChannel] = None):
        """開啟管理員控制面板"""
        await interaction.response.defer(ephemeral=True)
        
        try:
            # 如果沒有指定頻道，使用用戶當前所在的語音頻道
            if channel is None:
                if not interaction.user.voice or not interaction.user.voice.channel:
                    await interaction.followup.send("❌ 您必須在語音頻道中或指定一個頻道", ephemeral=True)
                    return
                channel = interaction.user.voice.channel
            
            # 檢查是否為子頻道
            is_child = await self.TempVoiceDatabase.is_child_channel(channel.id)
            if not is_child:
                await interaction.followup.send("❌ 此頻道不是臨時語音頻道", ephemeral=True)
                return
            
            # 獲取子頻道信息
            child_info = await self.TempVoiceDatabase.get_child_channel(channel.id)
            if not child_info:
                await interaction.followup.send("❌ 無法獲取頻道信息", ephemeral=True)
                return
            
            # 創建管理員面板
            view = AdminPanelView(channel, child_info, self)
            embed = await view.create_admin_embed(channel, child_info, interaction.guild)
            
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            
        except Exception as e:
            log.exception("開啟管理員面板時發生錯誤")
            await interaction.followup.send("❌ 開啟管理員面板時發生錯誤", ephemeral=True)
            
class VoiceChannelControlView(discord.ui.View):
    """語音頻道控制面板視圖"""
    
    def __init__(self, channel: discord.VoiceChannel, owner_id: int, cog):
        super().__init__(timeout=None)  # 無超時
        self.channel = channel
        self.owner_id = owner_id
        self.cog = cog
        
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """檢查互動用戶是否為頻道擁有者"""
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ 只有頻道擁有者可以使用此控制面板", ephemeral=True)
            return False
        return True
    
    # 第一行按鈕：頻道狀態控制
    @discord.ui.button(label="公開頻道", style=discord.ButtonStyle.success, emoji="🔓", row=0)
    async def public_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        """公開頻道按鈕"""
        try:
            overwrite = self.channel.overwrites_for(self.channel.guild.default_role)
            
            # 檢查是否已經是公開狀態
            if overwrite.connect is True and overwrite.view_channel is True:
                await interaction.response.send_message("ℹ️ 頻道已經是公開狀態", ephemeral=True)
                return
            
            overwrite.connect = True
            overwrite.view_channel = True
            await self.channel.set_permissions(self.channel.guild.default_role, overwrite=overwrite)
            
            await interaction.response.send_message("🔓 頻道已設為公開", ephemeral=True)
            
            # 更新面板
            await self.update_panel(interaction)
            
        except discord.Forbidden:
            await interaction.response.send_message("❌ 無法更改頻道權限，請檢查機器人權限", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ 發生錯誤：{str(e)}", ephemeral=True)

    @discord.ui.button(label="鎖定頻道", style=discord.ButtonStyle.danger, emoji="🔒", row=0)
    async def lock_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        """鎖定頻道按鈕"""
        try:
            overwrite = self.channel.overwrites_for(self.channel.guild.default_role)
            
            # 檢查是否已經是鎖定狀態
            if overwrite.connect is False and overwrite.view_channel is True:
                await interaction.response.send_message("ℹ️ 頻道已經是鎖定狀態", ephemeral=True)
                return
            
            overwrite.connect = False
            overwrite.view_channel = True
            await self.channel.set_permissions(self.channel.guild.default_role, overwrite=overwrite)
            
            await interaction.response.send_message("🔒 頻道已鎖定", ephemeral=True)
            
            # 更新面板
            await self.update_panel(interaction)
            
        except discord.Forbidden:
            await interaction.response.send_message("❌ 無法更改頻道權限，請檢查機器人權限", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ 發生錯誤：{str(e)}", ephemeral=True)
        
    @discord.ui.button(label="隱藏頻道", style=discord.ButtonStyle.secondary, emoji="👻", row=0)
    async def hide_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        """隱藏頻道按鈕"""
        try:
            overwrite = self.channel.overwrites_for(self.channel.guild.default_role)
            
            # 檢查是否已經是隱藏狀態
            if overwrite.connect is False and overwrite.view_channel is False:
                await interaction.response.send_message("ℹ️ 頻道已經是隱藏狀態", ephemeral=True)
                return
            
            overwrite.connect = False
            overwrite.view_channel = False
            await self.channel.set_permissions(self.channel.guild.default_role, overwrite=overwrite)
            
            await interaction.response.send_message("👻 頻道已隱藏", ephemeral=True)
            
            # 更新面板
            await self.update_panel(interaction)
            
        except discord.Forbidden:
            await interaction.response.send_message("❌ 無法更改頻道權限，請檢查機器人權限", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ 發生錯誤：{str(e)}", ephemeral=True)
    
    # 第二行按鈕：成員管理
    @discord.ui.button(label="踢出成員", style=discord.ButtonStyle.danger, emoji="👢", row=1)
    async def kick_member(self, interaction: discord.Interaction, button: discord.ui.Button):
        """踢出成員按鈕"""
        members = [m for m in self.channel.members if m.id != self.owner_id]
        if not members:
            await interaction.response.send_message("❌ 頻道中沒有其他成員", ephemeral=True)
            return
        
        view = PaginatedMemberSelectView(members, "kick", self.channel)
        await interaction.response.send_message("👢 請選擇要踢出的成員:", view=view, ephemeral=True)
        
    @discord.ui.button(label="封鎖成員", style=discord.ButtonStyle.danger, emoji="🚫", row=1)
    async def ban_member(self, interaction: discord.Interaction, button: discord.ui.Button):
        """封鎖成員按鈕"""
        # 獲取伺服器中的成員列表（排除擁有者）
        guild_members = [m for m in interaction.guild.members if m.id != self.owner_id and not m.bot]
        if not guild_members:
            await interaction.response.send_message("❌ 沒有可封鎖的成員", ephemeral=True)
            return
        
        view = PaginatedMemberSelectView(guild_members, "ban", self.channel)
        await interaction.response.send_message("🚫 請選擇要封鎖的成員:", view=view, ephemeral=True)
        
    @discord.ui.button(label="允許成員", style=discord.ButtonStyle.success, emoji="✅", row=1)
    async def allow_member(self, interaction: discord.Interaction, button: discord.ui.Button):
        """允許成員按鈕 - 提供白名單和解除黑名單選項"""
        view = AllowMemberOptionsView(self.channel)
        await interaction.response.send_message("✅ 請選擇操作類型:", view=view, ephemeral=True)
    
    # 第三行按鈕：頻道設定
    @discord.ui.button(label="切換地區", style=discord.ButtonStyle.primary, emoji="🌍", row=2)
    async def change_region(self, interaction: discord.Interaction, button: discord.ui.Button):
        """切換地區按鈕"""
        view = RegionSelectView(self.channel, self)
        await interaction.response.send_message("🌍 請選擇新的地區:", view=view, ephemeral=True)
        
    @discord.ui.button(label="更改名稱", style=discord.ButtonStyle.primary, emoji="📝", row=2)
    async def change_name(self, interaction: discord.Interaction, button: discord.ui.Button):
        """更改名稱按鈕"""
        modal = ChannelNameModal(self.channel, self)
        await interaction.response.send_modal(modal)
        
    @discord.ui.button(label="人數上限", style=discord.ButtonStyle.primary, emoji="👥", row=2)
    async def user_limit(self, interaction: discord.Interaction, button: discord.ui.Button):
        """人數上限按鈕"""
        modal = UserLimitModal(self.channel, self)
        await interaction.response.send_modal(modal)
    
    # 第四行按鈕：進階功能
    @discord.ui.button(label="檢視權限", style=discord.ButtonStyle.secondary, emoji="🔍", row=3)
    async def view_permissions(self, interaction: discord.Interaction, button: discord.ui.Button):
        """檢視權限按鈕"""
        embed = discord.Embed(
            title="🔍 頻道權限檢視",
            color=discord.Color.blue()
        )
        
        # 獲取頻道權限設定
        for target, overwrite in self.channel.overwrites.items():
            permissions = []
            if overwrite.connect is True:
                permissions.append("✅ 連接")
            elif overwrite.connect is False:
                permissions.append("❌ 連接")
            
            if overwrite.view_channel is True:
                permissions.append("✅ 查看頻道")
            elif overwrite.view_channel is False:
                permissions.append("❌ 查看頻道")
            
            if overwrite.mute_members is True:
                permissions.append("✅ 禁言成員")
            elif overwrite.mute_members is False:
                permissions.append("❌ 禁言成員")
                
            if permissions:
                name = target.display_name if isinstance(target, discord.Member) else target.name
                embed.add_field(
                    name=name,
                    value="\n".join(permissions),
                    inline=True
                )
        
        if not embed.fields:
            embed.description = "此頻道沒有特殊權限設定"
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
    @discord.ui.button(label="回復預設", style=discord.ButtonStyle.danger, emoji="🔄", row=3)
    async def reset_defaults(self, interaction: discord.Interaction, button: discord.ui.Button):
        """回復預設按鈕"""
        try:
            # 清除所有權限覆寫（除了擁有者的權限）
            owner = interaction.guild.get_member(self.owner_id)
            for target in list(self.channel.overwrites.keys()):
                if target != owner:
                    await self.channel.set_permissions(target, overwrite=None)
            
            # 重新設定預設狀態（公開）
            default_overwrite = discord.PermissionOverwrite()
            default_overwrite.connect = True
            default_overwrite.view_channel = True
            await self.channel.set_permissions(self.channel.guild.default_role, overwrite=default_overwrite)
            
            await interaction.response.send_message("🔄 頻道設定已回復預設", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ 無法重置頻道權限，請檢查機器人權限", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ 發生錯誤：{str(e)}", ephemeral=True)
    
    async def create_panel_embed(self, channel: discord.VoiceChannel, owner: discord.Member, created_at: str) -> discord.Embed:
        """創建控制面板嵌入"""
        
        overwrite = channel.overwrites_for(channel.guild.default_role)
        if overwrite.connect is False and overwrite.view_channel is False:
            status = "👻 隱藏"
        elif overwrite.connect is False:
            status = "🔒 鎖定"
        else:
            status = "🔓 公開"
            
        region_map = {
            "automatic": "🌐 自動",
            "brazil": "🇧🇷 巴西",
            "hongkong": "🇭🇰 香港",
            "india": "🇮🇳 印度",
            "japan": "🇯🇵 日本",
            "singapore": "🇸🇬 新加坡",
            "south-korea": "🇰🇷 南韓",
        }

        region = region_map.get(str(channel.rtc_region), "🌐 自動")
        
        embed = discord.Embed(
            title=f'🎛️ 語音頻道控制面板',
            color=discord.Color.blue(),
        )
        
        embed.add_field(name="📍 當前狀態", value=f'{region} ｜ {status}', inline=False)
        embed.add_field(name="👑 頻道擁有者", value=owner.mention, inline=False)
        
        # 處理時間戳
        try:
            if isinstance(created_at, (int, float)):
                # 如果是數字（UNIX 時間戳），直接使用
                timestamp = int(created_at)
            elif isinstance(created_at, str):
                # 如果是字符串，嘗試解析為 UNIX 時間戳
                try:
                    timestamp = int(created_at)
                except ValueError:
                    # 如果不是數字字符串，嘗試解析為 ISO 格式
                    created_time = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    timestamp = int(created_time.timestamp())
            else:
                # 如果是其他類型，使用當前時間
                _, timestamp = now_with_unix(cfg["timezone"])
            
            embed.add_field(name="📅 建立時間", value=f'<t:{timestamp}:F> (<t:{timestamp}:R>)', inline=False)
        except Exception as e:
            log.warning(f"處理建立時間時發生錯誤: {e}")
            embed.add_field(name="📅 建立時間", value="剛剛", inline=False)
        
        embed.add_field(name=" 人數上限", value=str(channel.user_limit) if channel.user_limit else "無限制", inline=True)
        
        embed.set_footer(text=f'{channel.guild.name} • {channel.name}')

        return embed
    
    async def update_panel(self, interaction: discord.Interaction):
        """更新控制面板嵌入"""
        try:
            # 獲取子頻道信息
            child_info = await self.cog.TempVoiceDatabase.get_child_channel(self.channel.id)
            if not child_info:
                return False
            
            # 獲取頻道擁有者
            owner = interaction.guild.get_member(self.owner_id)
            if not owner:
                return False
            
            # 創建新的嵌入
            new_embed = await self.create_panel_embed(self.channel, owner, child_info['created_at'])
            
            # 獲取原始控制面板訊息ID
            control_message_id = child_info['control_message_id'] if child_info and child_info['control_message_id'] else None
            if control_message_id:
                try:
                    # 嘗試獲取並更新原始控制面板訊息
                    control_message = await self.channel.fetch_message(control_message_id)
                    await control_message.edit(
                        embed=new_embed, 
                        view=self
                    )
                    return True
                except discord.NotFound:
                    # 如果原始訊息不存在，記錄並繼續使用備用方法
                    log.warning(f"控制面板訊息 {control_message_id} 不存在，將使用備用更新方法")
                except discord.HTTPException as e:
                    # 如果更新失敗，記錄錯誤
                    log.error(f"更新控制面板訊息時發生HTTP錯誤: {e}")
            
            # 備用方法：更新當前互動的響應（如果上面的方法失敗）
            try:
                await interaction.edit_original_response(embed=new_embed, view=self)
                return True
            except:
                # 如果備用方法也失敗，嘗試發送新訊息作為回應
                await interaction.response.send_message("⚠️ 無法更新控制面板", ephemeral=True)
                return False
                
        except Exception as e:
            log.exception(f"更新面板時發生錯誤: {e}")
            return False

class AllowMemberOptionsView(discord.ui.View):
    """允許成員選項視圖 - 提供白名單和解除黑名單選項"""
    
    def __init__(self, channel: discord.VoiceChannel):
        super().__init__(timeout=60)
        self.channel = channel
    
    @discord.ui.button(label="加入白名單", style=discord.ButtonStyle.success, emoji="➕")
    async def add_to_whitelist(self, interaction: discord.Interaction, button: discord.ui.Button):
        """將成員加入白名單，允許他們進入頻道"""
        # 獲取伺服器中所有成員（排除機器人和頻道擁有者）
        guild_members = []
        owner_id = None
        
        # 獲取頻道擁有者ID
        child_info = await interaction.client.get_cog('TempVoice').TempVoiceDatabase.get_child_channel(self.channel.id)
        if child_info:
            owner_id = child_info['owner_id']
        
        for member in interaction.guild.members:
            if not member.bot and member.id != owner_id:
                # 檢查成員是否已經有明確的允許權限
                overwrite = self.channel.overwrites_for(member)
                if overwrite.connect is not True:  # 只顯示沒有明確允許權限的成員
                    guild_members.append(member)
        
        if not guild_members:
            await interaction.response.send_message("❌ 沒有可加入白名單的成員", ephemeral=True)
            return
        
        view = PaginatedMemberSelectView(guild_members, "whitelist", self.channel)
        await interaction.response.send_message("➕ 請選擇要加入白名單的成員:", view=view, ephemeral=True)
    
    @discord.ui.button(label="解除黑名單", style=discord.ButtonStyle.secondary, emoji="🔓")
    async def remove_from_blacklist(self, interaction: discord.Interaction, button: discord.ui.Button):
        """將成員從黑名單移除"""
        # 獲取被封鎖的成員列表
        blocked_members = []
        owner_id = None
        
        # 獲取頻道擁有者ID
        child_info = await interaction.client.get_cog('TempVoice').TempVoiceDatabase.get_child_channel(self.channel.id)
        if child_info:
            owner_id = child_info['owner_id']
        
        for member, overwrite in self.channel.overwrites.items():
            if isinstance(member, discord.Member) and overwrite.connect is False and member.id != owner_id:
                blocked_members.append(member)
        
        if not blocked_members:
            await interaction.response.send_message("❌ 黑名單中沒有成員", ephemeral=True)
            return
        
        view = PaginatedMemberSelectView(blocked_members, "unban", self.channel)
        await interaction.response.send_message("🔓 請選擇要從黑名單移除的成員:", view=view, ephemeral=True)

class PaginatedMemberSelectView(discord.ui.View):
    """分頁成員選擇視圖 - 支援超過25人的情況"""
    
    def __init__(self, members: List[discord.Member], action: str, channel: discord.VoiceChannel):
        super().__init__(timeout=60)
        self.all_members = members
        self.action = action
        self.channel = channel
        self.current_page = 0
        self.page_size = 25  # Discord 限制
        self.total_pages = (len(members) + self.page_size - 1) // self.page_size
        
        # 初始化當前頁面
        self.update_page()
    
    def update_page(self):
        """更新當前頁面的內容"""
        # 清除現有項目
        self.clear_items()
        
        # 計算當前頁面的成員範圍
        start_idx = self.current_page * self.page_size
        end_idx = min(start_idx + self.page_size, len(self.all_members))
        current_members = self.all_members[start_idx:end_idx]
        
        # 添加成員選擇選單
        if current_members:
            select = MemberSelect(current_members, self.action, self.channel)
            self.add_item(select)
        
        # 添加分頁按鈕（如果需要）
        if self.total_pages > 1:
            # 上一頁按鈕
            prev_button = discord.ui.Button(
                label="上一頁",
                emoji="⬅️",
                style=discord.ButtonStyle.secondary,
                disabled=(self.current_page == 0)
            )
            prev_button.callback = self.prev_page
            self.add_item(prev_button)
            
            # 頁面指示器
            page_info = discord.ui.Button(
                label=f"{self.current_page + 1}/{self.total_pages}",
                style=discord.ButtonStyle.secondary,
                disabled=True
            )
            self.add_item(page_info)
            
            # 下一頁按鈕
            next_button = discord.ui.Button(
                label="下一頁",
                emoji="➡️",
                style=discord.ButtonStyle.secondary,
                disabled=(self.current_page >= self.total_pages - 1)
            )
            next_button.callback = self.next_page
            self.add_item(next_button)
    
    async def prev_page(self, interaction: discord.Interaction):
        """上一頁"""
        if self.current_page > 0:
            self.current_page -= 1
            self.update_page()
            await interaction.response.edit_message(view=self)
        else:
            await interaction.response.defer()
    
    async def next_page(self, interaction: discord.Interaction):
        """下一頁"""
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            self.update_page()
            await interaction.response.edit_message(view=self)
        else:
            await interaction.response.defer()

class MemberSelectView(discord.ui.View):
    """成員選擇視圖"""
    
    def __init__(self, members: List[discord.Member], action: str, channel: discord.VoiceChannel):
        super().__init__(timeout=60)
        self.members = members
        self.action = action
        self.channel = channel
        
        # 添加選擇選單
        select = MemberSelect(members, action, channel)
        self.add_item(select)

class MemberSelect(discord.ui.Select):
    """成員選擇下拉選單"""
    
    def __init__(self, members: List[discord.Member], action: str, channel: discord.VoiceChannel):
        self.action = action
        self.channel = channel
        
        options = []
        for member in members[:25]:  # Discord 限制最多25個選項
            options.append(discord.SelectOption(
                label=member.display_name,
                value=str(member.id),
                description=f"@{member.name}"
            ))
        
        placeholder_map = {
            "kick": "選擇要踢出的成員...",
            "ban": "選擇要封鎖的成員...",
            "unban": "選擇要解除封鎖的成員...",
            "whitelist": "選擇要加入白名單的成員..."
        }
        
        super().__init__(
            placeholder=placeholder_map.get(action, "選擇成員..."),
            options=options,
            max_values=min(len(options), 5)  # 最多選擇5個
        )
    
    async def callback(self, interaction: discord.Interaction):
        selected_members = []
        for value in self.values:
            member = interaction.guild.get_member(int(value))
            if member:
                selected_members.append(member)
        
        if not selected_members:
            await interaction.response.send_message("❌ 未找到選擇的成員", ephemeral=True)
            return
        
        try:
            if self.action == "kick":
                for member in selected_members:
                    if member.voice and member.voice.channel == self.channel:
                        await member.move_to(None)
                await interaction.response.send_message(
                    f"👢 已踢出 {', '.join([m.display_name for m in selected_members])}",
                    ephemeral=True
                )
            
            elif self.action == "ban":
                for member in selected_members:
                    overwrite = self.channel.overwrites_for(member)
                    overwrite.connect = False
                    overwrite.view_channel = False
                    await self.channel.set_permissions(member, overwrite=overwrite)
                    
                    # 如果成員在頻道中，踢出他們
                    if member.voice and member.voice.channel == self.channel:
                        await member.move_to(None)
                
                await interaction.response.send_message(
                    f"🚫 已封鎖 {', '.join([m.display_name for m in selected_members])}",
                    ephemeral=True
                )
            
            elif self.action == "unban":
                for member in selected_members:
                    await self.channel.set_permissions(member, overwrite=None)
                
                await interaction.response.send_message(
                    f"✅ 已解除封鎖 {', '.join([m.display_name for m in selected_members])}",
                    ephemeral=True
                )
            
            elif self.action == "whitelist":
                for member in selected_members:
                    overwrite = self.channel.overwrites_for(member)
                    overwrite.connect = True
                    overwrite.view_channel = True
                    await self.channel.set_permissions(member, overwrite=overwrite)
                
                await interaction.response.send_message(
                    f"➕ 已將 {', '.join([m.display_name for m in selected_members])} 加入白名單",
                    ephemeral=True
                )
        
        except discord.Forbidden:
            await interaction.response.send_message("❌ 沒有足夠的權限執行此操作", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ 發生錯誤：{str(e)}", ephemeral=True)

class RegionSelectView(discord.ui.View):
    """地區選擇視圖"""
    
    def __init__(self, channel: discord.VoiceChannel, control_view=None):
        super().__init__(timeout=60)
        self.channel = channel
        self.control_view = control_view
        
        select = RegionSelect(channel, control_view)
        self.add_item(select)

class RegionSelect(discord.ui.Select):
    """地區選擇下拉選單"""
    
    def __init__(self, channel: discord.VoiceChannel, control_view=None):
        self.channel = channel
        self.control_view = control_view
        
        regions = [
            ("🌐 自動", "automatic"),
            ("🇧🇷 巴西", "brazil"),
            ("🇭🇰 香港", "hongkong"),
            ("🇮🇳 印度", "india"),
            ("🇯🇵 日本", "japan"),
            ("🇸🇬 新加坡", "singapore"),
            ("🇰🇷 南韓", "south-korea"),
            ("🇺🇸 美國東部", "us-east"),
            ("🇺🇸 美國西部", "us-west"),
            ("🇺🇸 美國中部", "us-central"),
            ("🇪🇺 歐洲", "europe"),
        ]
        
        options = []
        for name, value in regions:
            options.append(discord.SelectOption(
                label=name,
                value=value,
                default=(str(channel.rtc_region) == value)
            ))
        
        super().__init__(
            placeholder="選擇新的地區...",
            options=options
        )
    
    async def callback(self, interaction: discord.Interaction):
        try:
            region = None if self.values[0] == "automatic" else self.values[0]
            await self.channel.edit(rtc_region=region)
            
            region_name = next(name for name, value in [
                ("🌐 自動", "automatic"),
                ("🇧🇷 巴西", "brazil"),
                ("🇭🇰 香港", "hongkong"),
                ("🇮🇳 印度", "india"),
                ("🇯🇵 日本", "japan"),
                ("🇸🇬 新加坡", "singapore"),
                ("🇰🇷 南韓", "south-korea"),
                ("🇺🇸 美國東部", "us-east"),
                ("🇺🇸 美國西部", "us-west"),
                ("🇺🇸 美國中部", "us-central"),
                ("🇪🇺 歐洲", "europe"),
            ] if value == self.values[0])
            
            await interaction.response.send_message(f"🌍 地區已更改為 {region_name}", ephemeral=True)
            
            # 更新控制面板
            if self.control_view:
                # 創建一個假的交互來更新控制面板
                try:
                    await self.control_view.update_panel(interaction)
                except:
                    pass  # 如果更新失敗就忽略
                    
        except discord.Forbidden:
            await interaction.response.send_message("❌ 沒有足夠的權限更改地區", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ 發生錯誤：{str(e)}", ephemeral=True)

class ChannelNameModal(discord.ui.Modal):
    """頻道名稱更改模態框"""
    
    def __init__(self, channel: discord.VoiceChannel, control_view=None):
        super().__init__(title="更改頻道名稱")
        self.channel = channel
        self.control_view = control_view
        
        self.name_input = discord.ui.TextInput(
            label="新的頻道名稱",
            placeholder="輸入新的頻道名稱...",
            default=channel.name,
            max_length=100,
            required=True
        )
        self.add_item(self.name_input)
    
    async def on_submit(self, interaction: discord.Interaction):
        try:
            new_name = self.name_input.value.strip()
            if not new_name:
                await interaction.response.send_message("❌ 頻道名稱不能為空", ephemeral=True)
                return
            
            await self.channel.edit(name=new_name)
            await interaction.response.send_message(f"📝 頻道名稱已更改為 `{new_name}`", ephemeral=True)
            
            # 更新控制面板
            if self.control_view:
                try:
                    await self.control_view.update_panel(interaction)
                except:
                    pass  # 如果更新失敗就忽略
                    
        except discord.Forbidden:
            await interaction.response.send_message("❌ 沒有足夠的權限更改頻道名稱", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ 發生錯誤：{str(e)}", ephemeral=True)

class UserLimitModal(discord.ui.Modal):
    """人數上限設定模態框"""
    
    def __init__(self, channel: discord.VoiceChannel, control_view=None):
        super().__init__(title="設定人數上限")
        self.channel = channel
        self.control_view = control_view
        
        current_limit = str(channel.user_limit) if channel.user_limit else "0"
        
        self.limit_input = discord.ui.TextInput(
            label="人數上限",
            placeholder="輸入人數上限 (0 = 無限制, 最大 99)",
            default=current_limit,
            max_length=2,
            required=True
        )
        self.add_item(self.limit_input)
    
    async def on_submit(self, interaction: discord.Interaction):
        try:
            limit_str = self.limit_input.value.strip()
            
            # 驗證輸入
            if not limit_str.isdigit():
                await interaction.response.send_message("❌ 請輸入有效的數字 (0-99)", ephemeral=True)
                return
            
            limit = int(limit_str)
            
            # 檢查範圍
            if limit < 0 or limit > 99:
                await interaction.response.send_message("❌ 人數上限必須在 0-99 之間 (0 = 無限制)", ephemeral=True)
                return
            
            # 設定人數上限
            await self.channel.edit(user_limit=limit if limit > 0 else None)
            
            limit_text = "無限制" if limit == 0 else f"{limit} 人"
            await interaction.response.send_message(f"👥 人數上限已設為 {limit_text}", ephemeral=True)
            
            # 更新控制面板
            if self.control_view:
                try:
                    await self.control_view.update_panel(interaction)
                except:
                    pass  # 如果更新失敗就忽略
                    
        except discord.Forbidden:
            await interaction.response.send_message("❌ 沒有足夠的權限更改人數上限", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ 發生錯誤：{str(e)}", ephemeral=True)

class ChannelInheritanceView(discord.ui.View):
    """頻道繼承視圖"""
    
    def __init__(self, channel: discord.VoiceChannel, cog):
        super().__init__(timeout=None)  # 無超時
        self.channel = channel
        self.cog = cog
        self.inheritance_message = None  # 用於存儲繼承面板訊息的引用
    
    @discord.ui.button(label="繼承頻道", style=discord.ButtonStyle.primary, emoji="👑")
    async def inherit_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        """繼承頻道按鈕"""
        # 檢查用戶是否在頻道中
        if interaction.user not in self.channel.members:
            await interaction.response.send_message("❌ 您必須在頻道中才能繼承擁有權", ephemeral=True)
            return
        
        # 標記是否已經回應
        response_sent = False
        
        try:
            # 獲取舊擁有者資訊
            child_info = await self.cog.TempVoiceDatabase.get_child_channel(self.channel.id)
            old_owner_id = None
            if child_info:
                old_owner_id = child_info['owner_id']
            
            # 移除舊擁有者的管理權限
            if old_owner_id and old_owner_id != interaction.user.id:
                old_owner = interaction.guild.get_member(old_owner_id)
                if old_owner:
                    # 清除舊擁有者的特殊權限，恢復為普通成員
                    await self.channel.set_permissions(old_owner, overwrite=None)
            
            # 更新資料庫中的擁有者
            await self.cog.TempVoiceDatabase.update_child_channel_owner(self.channel.id, interaction.user.id)
            
            # 給予新擁有者權限
            overwrite = self.channel.overwrites_for(interaction.user)
            overwrite.connect = True
            overwrite.mute_members = True
            overwrite.deafen_members = True
            overwrite.move_members = True
            overwrite.manage_channels = True
            await self.channel.set_permissions(interaction.user, overwrite=overwrite)
            
            # 發送繼承成功訊息
            await interaction.response.send_message(
                f"👑 {interaction.user.mention} 已成為此頻道的新擁有者！",
                ephemeral=False
            )
            response_sent = True
            
            # 更新現有的控制面板
            if child_info and child_info['control_message_id'] is not None:
                try:
                    control_message = await self.channel.fetch_message(child_info['control_message_id'])
                    if control_message:
                        # 更新控制面板的擁有者
                        new_view = VoiceChannelControlView(self.channel, interaction.user.id, self.cog)
                        new_embed = await new_view.create_panel_embed(self.channel, interaction.user, child_info['created_at'])
                        await control_message.edit(embed=new_embed, view=new_view)
                except discord.NotFound:
                    # 如果控制面板訊息不存在，發送新的
                    await self.cog.send_control_panel(self.channel, interaction.user)
            else:
                # 如果沒有控制面板記錄，發送新的
                await self.cog.send_control_panel(self.channel, interaction.user)
            
            # 刪除繼承面板訊息
            if self.inheritance_message:
                try:
                    await self.inheritance_message.delete()
                except:
                    # 如果無法刪除原始訊息，至少禁用按鈕
                    try:
                        for item in self.children:
                            item.disabled = True
                        await self.inheritance_message.edit(view=self)
                    except:
                        pass
            
        except Exception as e:
            log.exception("繼承頻道時發生錯誤")
            
            # 根據是否已經回應來決定如何發送錯誤訊息
            error_message = f"❌ 繼承頻道時發生錯誤：{str(e)}"
            
            if not response_sent:
                # 還沒有回應，可以直接回應
                try:
                    await interaction.response.send_message(error_message, ephemeral=True)
                except:
                    # 如果回應失敗，嘗試發送跟進訊息
                    try:
                        await interaction.followup.send(error_message, ephemeral=True)
                    except:
                        pass
            else:
                # 已經回應過，使用跟進訊息
                try:
                    await interaction.followup.send(error_message, ephemeral=True)
                except:
                    pass

class AdminPanelView(discord.ui.View):
    """管理員控制面板視圖"""
    
    def __init__(self, channel: discord.VoiceChannel, child_info, cog):
        super().__init__(timeout=300)  # 5分鐘超時
        self.channel = channel
        self.child_info = child_info
        self.cog = cog
    
    async def create_admin_embed(self, channel: discord.VoiceChannel, child_info, guild: discord.Guild) -> discord.Embed:
        """創建管理員面板嵌入"""
        embed = discord.Embed(
            title="🛡️ 管理員控制面板",
            description=f"管理頻道：{channel.mention}",
            color=discord.Color.red()
        )
        
        # 獲取頻道擁有者
        owner = guild.get_member(child_info['owner_id'])
        owner_name = owner.display_name if owner else f"未知用戶 (ID: {child_info['owner_id']})"
        
        # 獲取母頻道
        parent_channel = guild.get_channel(child_info['parent_channel_id'])
        parent_name = parent_channel.name if parent_channel else f"已刪除頻道 (ID: {child_info['parent_channel_id']})"
        
        # 頻道狀態
        overwrite = channel.overwrites_for(guild.default_role)
        if overwrite.connect is False and overwrite.view_channel is False:
            status = "👻 隱藏"
        elif overwrite.connect is False:
            status = "🔒 鎖定"
        else:
            status = "🔓 公開"
        
        embed.add_field(name="👑 當前擁有者", value=owner_name, inline=True)
        embed.add_field(name="📍 狀態", value=status, inline=True)
        embed.add_field(name="👥 當前人數", value=f"{len(channel.members)}/{channel.user_limit or '∞'}", inline=True)
        embed.add_field(name="🏠 母頻道", value=parent_name, inline=True)
        embed.add_field(name="🆔 頻道ID", value=f"`{channel.id}`", inline=True)
        
        # 處理建立時間
        try:
            if isinstance(child_info['created_at'], (int, float)):
                timestamp = int(child_info['created_at'])
            else:
                timestamp = int(child_info['created_at'])
            embed.add_field(name="📅 建立時間", value=f"<t:{timestamp}:R>", inline=True)
        except:
            embed.add_field(name="📅 建立時間", value="未知", inline=True)
        
        embed.set_footer(text="⚠️ 管理員專用面板 - 請謹慎使用")
        
        return embed
    
    @discord.ui.button(label="強制奪取擁有權", style=discord.ButtonStyle.danger, emoji="👑", row=0)
    async def force_take_ownership(self, interaction: discord.Interaction, button: discord.ui.Button):
        """強制奪取頻道擁有權"""
        try:
            # 獲取舊擁有者
            old_owner_id = self.child_info['owner_id']
            old_owner = interaction.guild.get_member(old_owner_id)
            
            # 移除舊擁有者的權限
            if old_owner:
                await self.channel.set_permissions(old_owner, overwrite=None)
            
            # 給予新擁有者權限
            overwrite = self.channel.overwrites_for(interaction.user)
            overwrite.connect = True
            overwrite.mute_members = True
            overwrite.deafen_members = True
            overwrite.move_members = True
            overwrite.manage_channels = True
            await self.channel.set_permissions(interaction.user, overwrite=overwrite)
            
            # 更新資料庫
            await self.cog.TempVoiceDatabase.update_child_channel_owner(self.channel.id, interaction.user.id)
            
            # 更新控制面板（如果存在）
            if self.child_info['control_message_id']:
                try:
                    control_message = await self.channel.fetch_message(self.child_info['control_message_id'])
                    new_view = VoiceChannelControlView(self.channel, interaction.user.id, self.cog)
                    new_embed = await new_view.create_panel_embed(self.channel, interaction.user, self.child_info['created_at'])
                    await control_message.edit(embed=new_embed, view=new_view)
                except:
                    pass
            
            # 在頻道中發送通知
            await self.channel.send(f"⚠️ 管理員 {interaction.user.mention} 已強制接管此頻道的擁有權")
            
            await interaction.response.send_message(f"✅ 已成功奪取 {self.channel.mention} 的擁有權", ephemeral=True)
            
        except Exception as e:
            await interaction.response.send_message(f"❌ 奪取擁有權失敗：{str(e)}", ephemeral=True)
    
    @discord.ui.button(label="強制刪除頻道", style=discord.ButtonStyle.danger, emoji="🗑️", row=0)
    async def force_delete_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        """強制刪除頻道"""
        # 創建確認視圖
        confirm_view = ConfirmDeleteView(self.channel, self.cog)
        embed = discord.Embed(
            title="⚠️ 確認刪除",
            description=f"您確定要刪除頻道 {self.channel.mention} 嗎？\n\n**此操作無法撤銷！**",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, view=confirm_view, ephemeral=True)
    
    @discord.ui.button(label="轉移擁有權", style=discord.ButtonStyle.primary, emoji="🔄", row=0)
    async def transfer_ownership(self, interaction: discord.Interaction, button: discord.ui.Button):
        """轉移頻道擁有權給其他成員"""
        # 獲取頻道中的成員（排除機器人和當前擁有者）
        members = [m for m in self.channel.members if not m.bot and m.id != self.child_info['owner_id']]
        
        if not members:
            await interaction.response.send_message("❌ 頻道中沒有可轉移的成員", ephemeral=True)
            return
        
        view = TransferOwnershipView(members, self.channel, self.child_info, self.cog)
        await interaction.response.send_message("🔄 請選擇新的擁有者：", view=view, ephemeral=True)
    
    @discord.ui.button(label="踢出所有成員", style=discord.ButtonStyle.danger, emoji="👢", row=1)
    async def kick_all_members(self, interaction: discord.Interaction, button: discord.ui.Button):
        """踢出頻道中所有成員"""
        try:
            kicked_members = []
            for member in self.channel.members:
                if member.id != self.child_info['owner_id'] and not member.bot:
                    try:
                        await member.move_to(None)
                        kicked_members.append(member.display_name)
                    except:
                        pass
            
            if kicked_members:
                await interaction.response.send_message(
                    f"👢 已踢出 {len(kicked_members)} 名成員：{', '.join(kicked_members[:5])}{'...' if len(kicked_members) > 5 else ''}",
                    ephemeral=True
                )
                # 在頻道中發送通知
                await self.channel.send(f"⚠️ 管理員 {interaction.user.mention} 已清空頻道")
            else:
                await interaction.response.send_message("ℹ️ 頻道中沒有可踢出的成員", ephemeral=True)
                
        except Exception as e:
            await interaction.response.send_message(f"❌ 踢出成員失敗：{str(e)}", ephemeral=True)
    
    @discord.ui.button(label="重置權限", style=discord.ButtonStyle.secondary, emoji="🔄", row=1)
    async def reset_permissions(self, interaction: discord.Interaction, button: discord.ui.Button):
        """重置頻道權限為預設狀態"""
        try:
            # 清除所有權限覆寫（除了機器人和擁有者）
            owner = interaction.guild.get_member(self.child_info['owner_id'])
            bot_member = interaction.guild.me
            
            for target in list(self.channel.overwrites.keys()):
                if target != owner and target != bot_member:
                    await self.channel.set_permissions(target, overwrite=None)
            
            # 設定預設狀態（公開）
            default_overwrite = discord.PermissionOverwrite()
            default_overwrite.connect = True
            default_overwrite.view_channel = True
            await self.channel.set_permissions(self.channel.guild.default_role, overwrite=default_overwrite)
            
            # 更新控制面板
            if self.child_info['control_message_id']:
                try:
                    control_message = await self.channel.fetch_message(self.child_info['control_message_id'])
                    if owner:
                        view = VoiceChannelControlView(self.channel, owner.id, self.cog)
                        embed = await view.create_panel_embed(self.channel, owner, self.child_info['created_at'])
                        await control_message.edit(embed=embed, view=view)
                except:
                    pass
            
            await interaction.response.send_message("🔄 頻道權限已重置為預設狀態", ephemeral=True)
            await self.channel.send(f"⚠️ 管理員 {interaction.user.mention} 已重置頻道權限")
            
        except Exception as e:
            await interaction.response.send_message(f"❌ 重置權限失敗：{str(e)}", ephemeral=True)
    
    @discord.ui.button(label="查看詳細信息", style=discord.ButtonStyle.secondary, emoji="📊", row=1)
    async def view_details(self, interaction: discord.Interaction, button: discord.ui.Button):
        """查看頻道詳細信息"""
        embed = discord.Embed(
            title="📊 頻道詳細信息",
            description=f"頻道：{self.channel.mention}",
            color=discord.Color.blue()
        )
        
        # 基本信息
        embed.add_field(name="🆔 頻道ID", value=f"`{self.channel.id}`", inline=True)
        embed.add_field(name="🏠 母頻道ID", value=f"`{self.child_info['parent_channel_id']}`", inline=True)
        embed.add_field(name="👑 擁有者ID", value=f"`{self.child_info['owner_id']}`", inline=True)
        embed.add_field(name="🎵 比特率", value=f"{self.channel.bitrate} bps", inline=True)
        embed.add_field(name="🌍 地區", value=str(self.channel.rtc_region) or "自動", inline=True)
        embed.add_field(name="📹 視頻品質", value=str(self.channel.video_quality_mode).split('.')[-1], inline=True)
        
        # 權限設定
        permissions_text = []
        for target, overwrite in self.channel.overwrites.items():
            name = target.display_name if isinstance(target, discord.Member) else target.name
            perms = []
            if overwrite.connect is True:
                perms.append("✅連接")
            elif overwrite.connect is False:
                perms.append("❌連接")
            if overwrite.view_channel is True:
                perms.append("✅查看")
            elif overwrite.view_channel is False:
                perms.append("❌查看")
            if perms:
                permissions_text.append(f"**{name}**: {', '.join(perms)}")
        
        if permissions_text:
            embed.add_field(
                name="🔐 權限設定",
                value="\n".join(permissions_text[:10]) + ("..." if len(permissions_text) > 10 else ""),
                inline=False
            )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

class ConfirmDeleteView(discord.ui.View):
    """確認刪除視圖"""
    
    def __init__(self, channel: discord.VoiceChannel, cog):
        super().__init__(timeout=30)
        self.channel = channel
        self.cog = cog
    
    @discord.ui.button(label="確認刪除", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def confirm_delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        """確認刪除頻道"""
        try:
            channel_name = self.channel.name
            await self.cog.delete_child_channel(self.channel)
            await interaction.response.send_message(f"✅ 已成功刪除頻道 `{channel_name}`", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ 刪除頻道失敗：{str(e)}", ephemeral=True)
    
    @discord.ui.button(label="取消", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel_delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        """取消刪除"""
        await interaction.response.send_message("❌ 已取消刪除操作", ephemeral=True)

class TransferOwnershipView(discord.ui.View):
    """轉移擁有權視圖"""
    
    def __init__(self, members: List[discord.Member], channel: discord.VoiceChannel, child_info, cog):
        super().__init__(timeout=60)
        self.members = members
        self.channel = channel
        self.child_info = child_info
        self.cog = cog
        
        # 添加選擇選單  
        select = TransferOwnershipSelect(members, channel, child_info, cog)
        self.add_item(select)

class TransferOwnershipSelect(discord.ui.Select):
    """轉移擁有權選擇選單"""
    
    def __init__(self, members: List[discord.Member], channel: discord.VoiceChannel, child_info, cog):
        self.channel = channel
        self.child_info = child_info
        self.cog = cog
        
        options = []
        for member in members[:25]:  # Discord 限制最多25個選項
            options.append(discord.SelectOption(
                label=member.display_name,
                value=str(member.id),
                description=f"@{member.name}"
            ))
        
        super().__init__(
            placeholder="選擇新的擁有者...",
            options=options
        )
    
    async def callback(self, interaction: discord.Interaction):
        try:
            new_owner_id = int(self.values[0])
            new_owner = interaction.guild.get_member(new_owner_id)
            
            if not new_owner:
                await interaction.response.send_message("❌ 找不到選擇的成員", ephemeral=True)
                return
            
            # 獲取舊擁有者
            old_owner = interaction.guild.get_member(self.child_info['owner_id'])
            
            # 移除舊擁有者的權限
            if old_owner:
                await self.channel.set_permissions(old_owner, overwrite=None)
            
            # 給予新擁有者權限
            overwrite = self.channel.overwrites_for(new_owner)
            overwrite.connect = True
            overwrite.mute_members = True
            overwrite.deafen_members = True
            overwrite.move_members = True
            overwrite.manage_channels = True
            await self.channel.set_permissions(new_owner, overwrite=overwrite)
            
            # 更新資料庫
            await self.cog.TempVoiceDatabase.update_child_channel_owner(self.channel.id, new_owner_id)
            
            # 更新控制面板（如果存在）
            if self.child_info['control_message_id']:
                try:
                    control_message = await self.channel.fetch_message(self.child_info['control_message_id'])
                    new_view = VoiceChannelControlView(self.channel, new_owner_id, self.cog)
                    new_embed = await new_view.create_panel_embed(self.channel, new_owner, self.child_info['created_at'])
                    await control_message.edit(embed=new_embed, view=new_view)
                except:
                    pass
            
            # 在頻道中發送通知
            await self.channel.send(f"🔄 管理員 {interaction.user.mention} 已將頻道擁有權轉移給 {new_owner.mention}")
            
            await interaction.response.send_message(f"✅ 已成功將擁有權轉移給 {new_owner.display_name}", ephemeral=True)
            
        except Exception as e:
            await interaction.response.send_message(f"❌ 轉移擁有權失敗：{str(e)}", ephemeral=True)

async def setup(bot):
    """載入擴充"""
    # 設定資料庫路徑
    db_path = os.getenv("VOICEDATABASE", "temp_voice.db")
    
    # 建立資料庫連接並初始化
    db = TempVoiceDatabase(db_path)
    await db.initdb()
    
    # 將 cog 添加到機器人
    await bot.add_cog(TempVoice(bot, db_path))
    log.info("TempVoice 擴充已載入")
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
        self.TempVoiceDatabase = 
        self.panel = VoiceChannelControlView
        
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
    

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        """監聽語音狀態更新事件"""
        # 如果用戶進入了母頻道，則創建子頻道
        if after.channel and before.channel != after.channel:
            is_parent = await self.TempVoiceDatabase.is_parent_channel(after.channel.id)
            try:
                if is_parent:
                    await self.create_child_channel(parent_channel=after.channel, member=member)
                    await asyncio.sleep(1)
                    await member.move_to(after.channel)
                    await 
                    
            except Exception as _:
                log.exception('創建頻道時發生錯誤')                    
                
            
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

class VoiceChannelControlView(discord.ui.View):
    """語音頻道控制面板視圖"""
    
    def __init__(self, channel: discord.VoiceChannel, owner_id: int):
        self.channel = channel
        self.owner_id = owner_id
        
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """檢查互動用戶是否為頻道擁有者"""
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ 只有頻道擁有者可以使用此控制面板", ephemeral=True)
            return False
        return True
    
    async def on_timeout(self):
        """當視圖超時時禁用所有按鈕"""
        for item in self.children:
            item.disabled = True
    
    # 第一行按鈕：頻道狀態控制
    @discord.ui.button(label="公開頻道", style=discord.ButtonStyle.success, emoji="🔓", row=0)
    async def public_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        """公開頻道按鈕"""
        await interaction.response.send_message("🔓 頻道已設為公開", ephemeral=True)
        # TODO: 實作公開頻道邏輯
        
    @discord.ui.button(label="鎖定頻道", style=discord.ButtonStyle.secondary, emoji="🔒", row=0)
    async def lock_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        """鎖定頻道按鈕"""
        await interaction.response.send_message("🔒 頻道已鎖定", ephemeral=True)
        # TODO: 實作鎖定頻道邏輯
        
    @discord.ui.button(label="隱藏頻道", style=discord.ButtonStyle.danger, emoji="👻", row=0)
    async def hide_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        """隱藏頻道按鈕"""
        await interaction.response.send_message("👻 頻道已隱藏", ephemeral=True)
        # TODO: 實作隱藏頻道邏輯
    
    # 第二行按鈕：成員管理
    @discord.ui.button(label="踢出成員", style=discord.ButtonStyle.secondary, emoji="👢", row=1)
    async def kick_member(self, interaction: discord.Interaction, button: discord.ui.Button):
        """踢出成員按鈕"""
        await interaction.response.send_message("👢 請選擇要踢出的成員", ephemeral=True)
        # TODO: 實作踢出成員邏輯
        
    @discord.ui.button(label="封鎖成員", style=discord.ButtonStyle.danger, emoji="🚫", row=1)
    async def ban_member(self, interaction: discord.Interaction, button: discord.ui.Button):
        """封鎖成員按鈕"""
        await interaction.response.send_message("🚫 請選擇要封鎖的成員", ephemeral=True)
        # TODO: 實作封鎖成員邏輯
        
    @discord.ui.button(label="允許成員", style=discord.ButtonStyle.success, emoji="✅", row=1)
    async def allow_member(self, interaction: discord.Interaction, button: discord.ui.Button):
        """允許成員按鈕"""
        await interaction.response.send_message("✅ 請選擇要允許的成員", ephemeral=True)
        # TODO: 實作允許成員邏輯
    
    # 第三行按鈕：頻道設定
    @discord.ui.button(label="切換地區", style=discord.ButtonStyle.secondary, emoji="🌍", row=2)
    async def change_region(self, interaction: discord.Interaction, button: discord.ui.Button):
        """切換地區按鈕"""
        await interaction.response.send_message("🌍 請選擇新的地區", ephemeral=True)
        # TODO: 實作切換地區邏輯
        
    @discord.ui.button(label="更改名稱", style=discord.ButtonStyle.secondary, emoji="📝", row=2)
    async def change_name(self, interaction: discord.Interaction, button: discord.ui.Button):
        """更改名稱按鈕"""
        await interaction.response.send_message("📝 請輸入新的頻道名稱", ephemeral=True)
        # TODO: 實作更改名稱邏輯
        
    @discord.ui.button(label="人數上限", style=discord.ButtonStyle.secondary, emoji="👥", row=2)
    async def user_limit(self, interaction: discord.Interaction, button: discord.ui.Button):
        """人數上限按鈕"""
        await interaction.response.send_message("👥 請設定人數上限", ephemeral=True)
        # TODO: 實作人數上限邏輯
    
    # 第四行按鈕：進階功能
    @discord.ui.button(label="檢視權限", style=discord.ButtonStyle.secondary, emoji="🔍", row=3)
    async def view_permissions(self, interaction: discord.Interaction, button: discord.ui.Button):
        """檢視權限按鈕"""
        await interaction.response.send_message("🔍 正在檢視頻道權限", ephemeral=True)
        # TODO: 實作檢視權限邏輯
        
    @discord.ui.button(label="回復預設", style=discord.ButtonStyle.danger, emoji="🔄", row=3)
    async def reset_defaults(self, interaction: discord.Interaction, button: discord.ui.Button):
        """回復預設按鈕"""
        await interaction.response.send_message("🔄 頻道設定已回復預設", ephemeral=True)
        # TODO: 實作回復預設邏輯
    
    async def create_panel(self, channel:discord.VoiceChannel, owner: discord.member, created_at: float,) -> discord.Embed:
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
            title=f'語音頻道控制面板',
            color=discord.Color.blue(),
        )
        
        embed.add_field(name="當前狀態", value=f'{region}｜{status}', inline=False)
        embed.add_field(name="頻道擁有者",value=owner.display_name, inline=False)
        embed.add_field(name="頻道建立時間", value=f'<t:{int(created_at)}:F>(<t:{int(created_at)}R>)', inline=False)
        
        embed.set_footer(text=f'{channel.guild.name} | {channel.name}')

        return embed
    
    async def update_panel(self, channel: discord.Message, region: Optional[str] = None, status: Optional[str] = None) -> discord.Embed:
        """更新控制面板嵌入"""
        pass
        

async def setup(bot):
    """載入擴充"""
    # 設定資料庫路徑
    db_path = os.getenv("VOICEDATABASE", "temp_voice.db")
    
    # 建立資料庫連接並初始化
    db = TempVoiceDatabase(db_path)
    await db.initdb()
    
    # 將 cog 添加到機器人
    await bot.add_cog(TempVoice(bot, db_path))
    log.info("已載入臨時語音頻道擴充")
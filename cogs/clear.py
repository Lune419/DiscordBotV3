import json
import time
import logging
import re
import asyncio
import typing as t

import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger(__name__)

class ConfirmDeleteView(discord.ui.View):
    """詢問刪除確認的互動視圖。"""

    def __init__(self, requester: discord.Member):
        super().__init__(timeout=180)  # 3 分鐘
        self.requester: discord.Member = requester
        self.confirmed: bool = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:  # noqa: D401,E501
        """限制只有觸發 slash 指令的人可以操作此 View。"""
        if interaction.user != self.requester:
            await interaction.response.send_message("您不是此操作的觸發者。", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="✅ 確認刪除", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, _button: discord.ui.Button):  # noqa: D401,E501
        self.confirmed = True
        await interaction.response.send_message("已確認，開始刪除…", ephemeral=True)
        self.stop()

    @discord.ui.button(label="❌ 取消", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _button: discord.ui.Button):  # noqa: D401,E501
        await interaction.response.send_message("已取消刪除操作。", ephemeral=True)
        self.stop()

class Clear(commands.Cog):
    """訊息管理相關指令群組。"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        super().__init__()

    @app_commands.command(name="clear", description="清除指定範圍的訊息")
    @app_commands.describe(
        amount="要刪除的訊息數量 (1–1000)",
        to_message_id="刪除到該訊息ID（含）為止",
        users="僅限這些使用者，多位請以空白隔開或 @mention"
    )
    @app_commands.checks.has_permissions(manage_messages=True)
    async def clear(
        self,
        interaction: discord.Interaction,
        amount: app_commands.Range[int, 1, 1000] = None,
        to_message_id: str = None,
        users: str = None,
    ) -> None:
        """批量刪除訊息，支援數量或訊息 ID 模式。"""
        await interaction.response.defer(ephemeral=True)
        
        # 檢查參數有效性
        if amount is None and to_message_id is None:
            await interaction.followup.send("請至少提供訊息數量或目標訊息ID其中之一", ephemeral=True)
            return
            
        # 如果沒有指定數量但有指定訊息ID，預設設為最大值
        if amount is None:
            amount = 1000  # 使用最大允許值

        channel: discord.TextChannel = t.cast(discord.TextChannel, interaction.channel)

        # ------------------ 處理使用者過濾 ------------------
        target_users: set[int] = set()
        if users:
            # 同時支援 "@User" mention 與純 ID
            id_matches = re.findall(r"<@!?(\d+)>", users) or re.findall(r"\d+", users)
            target_users = {int(uid) for uid in id_matches}

        # ------------------ 獲取目標訊息 ------------------
        to_message = None
        if to_message_id:
            try:
                to_message = await channel.fetch_message(int(to_message_id))
            except (discord.NotFound, ValueError):
                await interaction.followup.send(f"找不到指定的訊息 ID: {to_message_id}", ephemeral=True)
                return

        # ------------------ 收集待刪訊息 ------------------
        messages: list[discord.Message] = []
        
        # 確保 amount 是整數且大於0
        max_messages = amount if amount is not None else 1000
        
        if to_message:
            # ID模式：收集從指定ID到更早的訊息
            try:
                # 先確認目標訊息是否符合過濾條件
                target_msg_valid = not target_users or to_message.author.id in target_users
                
                # 使用限制最大數量的方式從頻道底部往上收集訊息
                async for msg in channel.history(limit=max_messages):
                    # 如果到達目標訊息，就停止收集
                    if msg.id == to_message.id:
                        if target_msg_valid:
                            messages.append(msg)  # 加入目標訊息本身
                        break
                    
                    # 如果符合過濾條件，就加入列表
                    if not target_users or msg.author.id in target_users:
                        messages.append(msg)
                
                # 反轉訊息列表，讓它從舊到新排序(底部到目標ID)
                messages.reverse()
                
            except Exception as e:
                log.error(f"收集訊息時出錯: {e}")
                await interaction.followup.send(f"收集訊息時發生錯誤: {e}", ephemeral=True)
                return
        else:
            # 數量模式：直接收集指定數量的最新訊息
            async for msg in channel.history(limit=max_messages):
                if target_users and msg.author.id not in target_users:
                    continue
                messages.append(msg)
                if len(messages) >= max_messages:
                    break

        if not messages:
            await interaction.followup.send("找不到符合條件的訊息。", ephemeral=True)
            return

        # ------------------ 預覽 ------------------
        earliest, latest = messages[-1], messages[0]
        embed = discord.Embed(
            title="預覽即將刪除的訊息",
            colour=discord.Colour.red(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="刪除總數", value=f"{len(messages)}", inline=False)

        for tag, msg in (("最舊", earliest), ("最新", latest)):
            content = (
                (msg.content[:75] + "…")
                if msg.content and len(msg.content) > 75
                else (msg.content or "[Embed/檔案]")
            )
            embed.add_field(
                name=f"{tag}訊息",
                value=(
                    f"作者：{msg.author.mention}\n"
                    f"時間：{discord.utils.format_dt(msg.created_at)}\n"
                    f"內容：{content}\n"
                    f"[點擊查看原始訊息]({msg.jump_url})"
                ),
                inline=False,
            )

        if target_users:
            mentions = "、".join(f"<@{uid}>" for uid in target_users)
            embed.add_field(name="過濾使用者", value=mentions, inline=False)

        view = ConfirmDeleteView(interaction.user)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        await view.wait()
        if not view.confirmed:
            return

        # ------------------ 刪除 ------------------
        success, failed = 0, 0
        progress = await interaction.followup.send("開始刪除…", ephemeral=True)

        for i, msg in enumerate(messages, 1):
            try:
                await msg.delete()
                success += 1
            except (discord.Forbidden, discord.HTTPException):
                failed += 1

            # 每 10 筆更新一次進度並稍作休息，減少速限可能
            if i % 10 == 0:
                await progress.edit(content=f"已刪除 {i}/{len(messages)}")
                await asyncio.sleep(0.25)

        summary = f"完成！成功刪除 {success} 筆"
        if failed:
            summary += f"；失敗 {failed} 筆（可能權限不足或已不存在）"
        await progress.edit(content=summary)

async def setup(bot: commands.Bot):
    await bot.add_cog(Clear(bot))
    log.info("Clear 擴充已載入")


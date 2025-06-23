import discord

from typing import List
from discord.ui import View, button

"""
Paginator 分頁器類別

作用：
將多個 embed 內容分頁顯示，並提供按鈕切換上下頁。當 embed 數量超過一頁時，使用者可以點擊按鈕瀏覽不同頁面，提升大量資料的閱讀體驗。分頁器會自動顯示目前頁數，並在超時後自動將所有按鈕設為不可用。

傳入參數：
- embeds (List[discord.Embed]): 要分頁顯示的 embed 物件列表，每一個 embed 代表一頁。

傳出/互動：
- 使用者在 Discord 上點擊分頁按鈕時，訊息會即時更新為對應的 embed 頁面。
- 分頁器本身不會回傳資料，但可透過 self.message 屬性記錄訊息物件，方便在 timeout 時自動將按鈕設為 disabled。

使用方式範例：
embeds = [...]  # 你的 embed 列表
paginator = Paginator(embeds)
await interaction.response.send_message(embed=embeds[0], view=paginator, ephemeral=True)
paginator.message = await interaction.original_response()
"""

class Paginator(View):
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
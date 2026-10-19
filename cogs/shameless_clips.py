"""Cog Shameless « Clips » : dépose sur l'API les vidéos postées dans SHAMELESS_CLIPS_CHANNEL_ID."""
import logging

import discord
from discord.ext import commands

from services.shameless_clips import ClipsDepositor
from shameless_config import ShamelessSettings


logger = logging.getLogger(__name__)


class ShamelessClips(commands.Cog):
    def __init__(self, bot, settings: ShamelessSettings):
        self.bot = bot
        self.depositor = ClipsDepositor(settings)

    async def cog_load(self):
        if self.depositor.configured:
            logger.info("shameless clips : dépôt actif sur le salon %s", self.depositor.settings.clips_channel_id)
        else:
            logger.warning("shameless clips : inactif (SHAMELESS_API_URL, SHAMELESS_BOT_TO_API_KEY ou SHAMELESS_CLIPS_CHANNEL_ID manquant)")

    async def cog_unload(self):
        await self.depositor.close()

    @commands.Cog.listener()
    async def on_message(self, message):
        deposited = await self.depositor.handle_message(message)
        if not deposited:
            return
        text = "✅ Clip enregistré" if len(deposited) == 1 else f"✅ {len(deposited)} clips enregistrés"
        try:
            await message.reply(text, mention_author=False)
        except discord.HTTPException:
            logger.exception("Confirmation du clip (message %s) non envoyée", message.id)


async def setup(bot):
    await bot.add_cog(ShamelessClips(bot, bot.settings.shameless))

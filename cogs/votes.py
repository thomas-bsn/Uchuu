"""Cog fin du module Vote : arrivée d'un membre → vote Invité, expiration périodique,
bouton ✅ persistant réenregistré au démarrage."""
from __future__ import annotations

import logging

import discord
from discord.ext import commands, tasks

from bot_settings import BotSettings
from services.vote import Votes
from services.vote_gateway import DiscordVoteGateway
from services.vote_policies import InvitePolicy
from services.vote_store import VoteStore
from views.vote_button import VOTES_COG, VoteButton

log = logging.getLogger(__name__)

EXPIRY_CHECK_SECONDS = 30


def build_votes(bot, settings: BotSettings) -> Votes:
    return Votes(
        VoteStore(settings.votes.db_path),
        DiscordVoteGateway(bot, settings),
        [InvitePolicy(settings.ids, settings.votes)],
        approvals_required=settings.votes.approvals_required,
        voter_role_id=settings.ids.role_confiance_id,
    )


class VotesCog(commands.Cog, name=VOTES_COG):
    def __init__(self, bot, settings: BotSettings):
        self.bot = bot
        self.settings = settings
        self.votes = build_votes(bot, settings)

    async def cog_load(self):
        self.expire_due_votes.start()

    async def cog_unload(self):
        self.expire_due_votes.cancel()

    @tasks.loop(seconds=EXPIRY_CHECK_SECONDS)
    async def expire_due_votes(self):
        try:
            await self.votes.expire_due()
        except Exception:
            log.exception("expiration des votes en échec")

    @expire_due_votes.before_loop
    async def _wait_ready(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.guild.id != self.settings.ids.guild_id or member.bot:
            return
        await self.votes.open("invite", member.id)


async def setup(bot):
    bot.add_dynamic_items(VoteButton)
    await bot.add_cog(VotesCog(bot, bot.settings))

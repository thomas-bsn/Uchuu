"""Cog fin du module Vote : arrivée d'un membre → vote Invité, scan périodique des
candidats Confiance, expiration périodique, bouton ✅ persistant réenregistré au démarrage."""
from __future__ import annotations

import asyncio
import logging

import discord
from discord.ext import commands, tasks

from bot_settings import BotSettings
from services.vote import Votes
from services.vote_gateway import DiscordVoteGateway
from services.vote_policies import ConfiancePolicy, InvitePolicy
from services.vote_store import VoteStore
from services.vote_types import VoteKind
from views.vote_button import VOTES_COG, VoteButton

log = logging.getLogger(__name__)

EXPIRY_CHECK_SECONDS = 30
REPLY_ERROR = "Erreur lors du vote. Réessaie plus tard."


def build_votes(bot, settings: BotSettings) -> Votes:
    return Votes(
        VoteStore(settings.votes.db_path, init_schema=False),  # schéma créé dans cog_load
        DiscordVoteGateway(bot, settings),
        [InvitePolicy(settings.ids, settings.votes), ConfiancePolicy(settings.ids, settings.votes)],
        approvals_required=settings.votes.approvals_required,
        voter_role_id=settings.ids.role_confiance_id,
    )


class VotesCog(commands.Cog, name=VOTES_COG):
    def __init__(self, bot, settings: BotSettings):
        self.bot = bot
        self.settings = settings
        self.votes = build_votes(bot, settings)
        self.scan_confiance.change_interval(hours=settings.votes.confiance_scan_interval_hours)

    async def cog_load(self):
        await asyncio.to_thread(self.votes.store.create_schema)  # I/O SQLite hors de la boucle
        self.expire_due_votes.start()
        self.scan_confiance.start()

    async def cog_unload(self):
        self.expire_due_votes.cancel()
        self.scan_confiance.cancel()

    @tasks.loop(seconds=EXPIRY_CHECK_SECONDS)
    async def expire_due_votes(self):
        try:
            await self.votes.expire_due()
        except Exception:
            log.exception("expiration des votes en échec")

    @tasks.loop(hours=24)  # intervalle réel : CONFIANCE_SCAN_INTERVAL_HOURS
    async def scan_confiance(self):
        try:
            await self.votes.scan(VoteKind.CONFIANCE)
        except Exception:
            log.exception("scan des candidats Confiance en échec")

    @expire_due_votes.before_loop
    @scan_confiance.before_loop
    async def _wait_ready(self):
        await self.bot.wait_until_ready()

    async def vote_clicked(self, vote_id: int, voter_id: int) -> str:
        """Clic ✅ (bouton persistant) ; renvoie la réponse éphémère du votant."""
        try:
            return await self.votes.approve(vote_id, voter_id)
        except Exception:
            log.exception("vote %s : échec du bulletin de %s", vote_id, voter_id)
            return REPLY_ERROR

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.guild.id != self.settings.ids.guild_id or member.bot:
            return
        await self.votes.open(VoteKind.INVITE, member.id)


async def setup(bot):
    bot.add_dynamic_items(VoteButton)
    await bot.add_cog(VotesCog(bot, bot.settings))

"""Cog fin du module Vote : arrivée d'un membre → vote Invité (rattrapage des arrivées
pendant un arrêt au démarrage), scan périodique des candidats Confiance, tick périodique
(expiration, complétion des votes ouverts, heartbeat), bouton ✅ persistant réenregistré
au démarrage. Toute erreur inattendue est aussi postée dans le salon de logs."""
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

TICK_SECONDS = 30
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
        self.scan_loop.change_interval(hours=settings.votes.confiance_scan_interval_hours)

    async def cog_load(self):
        await asyncio.to_thread(self.votes.store.create_schema)  # I/O SQLite hors de la boucle
        self.tick_loop.start()
        self.scan_loop.start()

    async def cog_unload(self):
        self.tick_loop.cancel()
        self.scan_loop.cancel()

    async def tick(self) -> None:
        """Expiration des votes échus, complétion des votes ouverts (rôle Invité, message
        de vote manquants), heartbeat. Chaque étape tourne même si la précédente échoue."""
        await self._guarded("expiration des votes", self.votes.expire_due)
        await self._guarded("complétion des votes ouverts", self.votes.reconcile)
        await self._guarded("heartbeat des votes", self.votes.heartbeat)

    async def scan(self) -> None:
        await self._guarded("scan des candidats Confiance", self.votes.scan, VoteKind.CONFIANCE)

    async def vote_clicked(self, vote_id: int, voter_id: int) -> str:
        """Clic ✅ (bouton persistant) ; renvoie la réponse éphémère du votant."""
        try:
            return await self.votes.approve(vote_id, voter_id)
        except Exception as error:
            await self._report(f"bulletin de <@{voter_id}> sur le vote {vote_id}", error)
            return REPLY_ERROR

    async def _guarded(self, action: str, step, *args) -> None:
        try:
            await step(*args)
        except Exception as error:
            await self._report(action, error)

    async def _report(self, action: str, error: Exception) -> None:
        """Erreur inattendue : logging Python (trace complète) + salon de logs."""
        log.error("%s en échec", action, exc_info=error)
        try:
            await self.votes.gateway.log(f"❌ [votes] {action} en échec : {type(error).__name__}: {error}")
        except Exception:
            log.exception("signalement au salon de logs impossible")

    @tasks.loop(seconds=TICK_SECONDS)
    async def tick_loop(self):
        await self.tick()

    @tasks.loop(hours=24)  # intervalle réel : CONFIANCE_SCAN_INTERVAL_HOURS
    async def scan_loop(self):
        await self.scan()

    @tick_loop.before_loop
    async def _before_tick(self):
        await self.bot.wait_until_ready()
        # Arrivées pendant l'arrêt du bot (avant le premier heartbeat du tick).
        await self._guarded("rattrapage des arrivées", self.votes.catch_up_arrivals, VoteKind.INVITE)

    @scan_loop.before_loop
    async def _before_scan(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.guild.id != self.settings.ids.guild_id or member.bot:
            return
        await self.votes.open(VoteKind.INVITE, member.id)


async def setup(bot):
    bot.add_dynamic_items(VoteButton)
    await bot.add_cog(VotesCog(bot, bot.settings))

"""Cog Shameless « Games » (#5) : annonce de Série, récap de Game, présences vocales.

Handlers branchés sur le dispatcher webhook de #2 (game_started / game_completed).
Présences (US 24) : entre game_started et game_completed d'une Game, on note les humains
vus dans n'importe quel salon vocal du serveur Shameless (SHAMELESS_GUILD_ID), hors Joueurs
de la Game et hors bots. Tout est dans SQLite -> un redémarrage en pleine Game reprend la
fenêtre ouverte.
SQLite est appelé via asyncio.to_thread : jamais d'I/O bloquante sur la boucle du bot.
"""
from __future__ import annotations

import asyncio
import logging

from discord.ext import commands

from services.shameless_events import EVENT_GAME_COMPLETED, EVENT_GAME_STARTED, ShamelessEvent, get_dispatcher
from services.shameless_games_store import POST_GAME_RECAP, POST_SERIES_ANNOUNCE, GameAttendanceStore, GamePostsStore
from services.shameless_payloads import participant_discord_ids
from services.shameless_recap import game_recap, series_announcement
from shameless_config import ShamelessSettings

logger = logging.getLogger(__name__)


class ShamelessGames(commands.Cog):
    def __init__(self, bot, settings: ShamelessSettings):
        self.bot = bot
        self.settings = settings
        self.posts = GamePostsStore(settings.db_path)
        self.attendance = GameAttendanceStore(settings.db_path)

    async def cog_load(self):
        dispatcher = get_dispatcher(self.bot)
        dispatcher.register(EVENT_GAME_STARTED, self.on_game_started)
        dispatcher.register(EVENT_GAME_COMPLETED, self.on_game_completed)
        logger.info("shameless games : handlers game_started / game_completed enregistrés (annonces sur %s)",
                    self.settings.announce_channel_id or "aucun salon configuré")

    async def cog_unload(self):
        dispatcher = get_dispatcher(self.bot)
        dispatcher.unregister(EVENT_GAME_STARTED)
        dispatcher.unregister(EVENT_GAME_COMPLETED)

    # =========================
    # WEBHOOK HANDLERS
    # =========================

    async def on_game_started(self, event: ShamelessEvent) -> None:
        data = event.data
        game_id = data.get("game_id")
        if game_id:
            # présences d'abord : idempotent, et indépendant d'un échec d'annonce
            participants = participant_discord_ids(data)
            await asyncio.to_thread(self.attendance.open_window, str(game_id), participants)
            await self._snapshot({str(game_id): participants})

        # annonce au premier game_started vu pour la Série (dédup par series_id), même si
        # celui de la Game 1 a été raté
        key = str(data.get("series_id") or game_id or event.event_id)
        await self._post_once(POST_SERIES_ANNOUNCE, key, lambda: series_announcement(data, self.settings.web_url))

    async def on_game_completed(self, event: ShamelessEvent) -> None:
        data = event.data
        game_id = data.get("game_id")
        if game_id:
            open_windows = await asyncio.to_thread(self.attendance.open_windows)
            if str(game_id) in open_windows:
                # dernier relevé : présents à la fin
                await self._snapshot({str(game_id): open_windows[str(game_id)]})
            await asyncio.to_thread(self.attendance.close_window, str(game_id), participant_discord_ids(data))

        key = str(game_id or event.event_id)
        await self._post_once(POST_GAME_RECAP, key, lambda: game_recap(data, self.settings.web_url))

    # =========================
    # VOICE (présences)
    # =========================

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        channel = getattr(after, "channel", None)
        # mute / deafen / stream : même salon -> rien à noter
        if channel is None or channel == getattr(before, "channel", None):
            return
        # filtre en mémoire, avant tout accès SQLite : seuls les vocaux du serveur configuré
        guild = getattr(channel, "guild", None)
        if member.bot or guild is None or guild.id != self.settings.guild_id:
            return
        await asyncio.to_thread(self._record_everywhere, str(member.id))

    def _record_everywhere(self, discord_id: str) -> None:
        for game_id, participants in self.attendance.open_windows().items():
            if discord_id not in participants:
                self.attendance.record(game_id, {discord_id})

    @commands.Cog.listener()
    async def on_ready(self):
        # (re)connexion : rattrape ceux arrivés pendant que le bot était absent
        open_windows = await asyncio.to_thread(self.attendance.open_windows)
        if open_windows:
            await self._snapshot(open_windows)

    # =========================
    # HELPERS
    # =========================

    def _voice_channels(self) -> list:
        """Tous les salons vocaux (et Stages) du serveur Shameless configuré."""
        guild_id = self.settings.guild_id
        guild = self.bot.get_guild(guild_id) if guild_id is not None else None
        if guild is None:
            return []
        return [*guild.voice_channels, *getattr(guild, "stage_channels", ())]

    async def _snapshot(self, windows: dict[str, set[str]]) -> None:
        """Note les humains actuellement dans un vocal du serveur pour ces Games."""
        present = {str(m.id) for c in self._voice_channels() for m in c.members if not m.bot}

        def _record():
            for game_id, participants in windows.items():
                self.attendance.record(game_id, present - participants)

        await asyncio.to_thread(_record)

    async def _post_once(self, kind: str, key: str, build_embed) -> None:
        # salon résolu AVANT la réservation : absent / inaccessible -> exception, l'event
        # n'est pas marqué traité et Shameless retente
        channel = await self._announce_channel()
        if not await asyncio.to_thread(self.posts.claim, kind, key):
            return
        try:
            await channel.send(embed=build_embed())
        except BaseException:
            # pas publié (erreur ou timeout du handler) -> on libère pour que le retry republie.
            # shield : la libération va au bout même si on est annulé.
            await asyncio.shield(asyncio.to_thread(self.posts.release, kind, key))
            raise

    async def _announce_channel(self):
        channel_id = self.settings.announce_channel_id
        if channel_id is None:
            raise RuntimeError("SHAMELESS_ANNOUNCE_CHANNEL_ID absent : annonce/récap impossibles")
        # pas dans le cache -> fetch ; s'il lève, le webhook répond 500 et Shameless retente
        return self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)


async def setup(bot):
    await bot.add_cog(ShamelessGames(bot, bot.settings.shameless))

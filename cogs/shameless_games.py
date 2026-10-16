"""Cog Shameless « Games » (#5) : annonce de Série, récap de Game, présences vocales.

Handlers branchés sur le dispatcher webhook de #2 (game_started / game_completed).
Présences (US 24) : entre game_started et game_completed d'une Game, on note les humains
vus dans les salons vocaux commun / Team 1 / Team 2, hors Joueurs de la Game. Tout est
dans SQLite -> un redémarrage en pleine Game reprend la fenêtre ouverte.
"""
from __future__ import annotations

import logging
from typing import Any

from discord.ext import commands

from services.shameless_events import EVENT_GAME_COMPLETED, EVENT_GAME_STARTED, ShamelessEvent, get_dispatcher
from services.shameless_games_store import GameAttendanceStore, GamePostsStore
from services.shameless_recap import game_recap, series_announcement
from shameless_config import ShamelessSettings

logger = logging.getLogger(__name__)


def participant_ids(data: dict[str, Any]) -> set[str]:
    """IDs Discord des Joueurs liés de la Game (contrat API), sinon déduits des Teams."""
    ids = data.get("participant_discord_ids")
    if not isinstance(ids, list):
        teams = data.get("teams") if isinstance(data.get("teams"), dict) else {}
        ids = [
            p.get("discord_id")
            for team in teams.values() if isinstance(team, dict)
            for p in team.get("players") or [] if isinstance(p, dict)
        ]
    return {str(i) for i in ids if i}


class ShamelessGames(commands.Cog):
    def __init__(self, bot, settings: ShamelessSettings):
        self.bot = bot
        self.settings = settings
        self.posts = GamePostsStore(settings.db_path)
        self.attendance = GameAttendanceStore(settings.db_path)
        dispatcher = get_dispatcher(bot)
        dispatcher.register(EVENT_GAME_STARTED, self.on_game_started)
        dispatcher.register(EVENT_GAME_COMPLETED, self.on_game_completed)

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
            participants = participant_ids(data)
            self.attendance.open_window(str(game_id), participants)
            self._snapshot({str(game_id): participants})

        # annonce seulement au lancement de la 1re Game (numéro absent = on suppose la 1re)
        if data.get("game_number") not in (None, 1):
            return
        key = str(data.get("series_id") or game_id or event.event_id)
        await self._post_once("series_announce", key, lambda: series_announcement(data, self.settings.web_url))

    async def on_game_completed(self, event: ShamelessEvent) -> None:
        data = event.data
        game_id = data.get("game_id")
        if game_id:
            open_windows = self.attendance.open_windows()
            if str(game_id) in open_windows:
                # dernier relevé : présents à la fin
                self._snapshot({str(game_id): open_windows[str(game_id)]})
            self.attendance.close_window(str(game_id), participant_ids(data))

        key = str(game_id or event.event_id)
        await self._post_once("game_recap", key, lambda: game_recap(data, self.settings.web_url))

    # =========================
    # VOICE (présences)
    # =========================

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        channel = getattr(after, "channel", None)
        if member.bot or channel is None or channel.id not in self._voice_ids():
            return
        discord_id = str(member.id)
        for game_id, participants in self.attendance.open_windows().items():
            if discord_id not in participants:
                self.attendance.record(game_id, {discord_id})

    @commands.Cog.listener()
    async def on_ready(self):
        # (re)connexion : rattrape ceux arrivés pendant que le bot était absent
        open_windows = self.attendance.open_windows()
        if open_windows:
            self._snapshot(open_windows)

    # =========================
    # HELPERS
    # =========================

    def _voice_ids(self) -> set[int]:
        s = self.settings
        return {i for i in (s.shared_voice_id, s.team1_voice_id, s.team2_voice_id) if i is not None}

    def _snapshot(self, windows: dict[str, set[str]]) -> None:
        """Note les humains actuellement dans les salons configurés pour ces Games."""
        present = set()
        for channel_id in self._voice_ids():
            channel = self.bot.get_channel(channel_id)
            if channel is None:
                continue
            present |= {str(m.id) for m in channel.members if not m.bot}
        for game_id, participants in windows.items():
            self.attendance.record(game_id, present - participants)

    async def _post_once(self, kind: str, key: str, build_embed) -> None:
        channel = await self._announce_channel()
        if channel is None or not self.posts.claim(kind, key):
            return
        try:
            await channel.send(embed=build_embed())
        except Exception:
            # pas publié -> on libère pour que le retry Shameless republie
            self.posts.release(kind, key)
            raise

    async def _announce_channel(self):
        channel_id = self.settings.announce_channel_id
        if channel_id is None:
            logger.warning("SHAMELESS_ANNOUNCE_CHANNEL_ID absent : annonce/récap ignorés")
            return None
        # pas dans le cache -> fetch ; s'il lève, le webhook répond 500 et Shameless retente
        return self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)


async def setup(bot):
    await bot.add_cog(ShamelessGames(bot, ShamelessSettings.from_env()))

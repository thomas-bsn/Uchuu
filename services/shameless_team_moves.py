"""teams_formed (#4) : placer les Joueurs liés et connectés dans les vocaux d'équipe.

Team A -> vocal Team 1, Team B -> vocal Team 2 pour toute la Série (pas de lien avec
les côtés bleu/rouge). Un seul move, à la formation des Teams : les events de Game
ne redéplacent personne, les joueurs reviennent quand ils veulent.

Snapshot attendu dans event.data :

    {"series_id": "...",
     "team_a": {"name": "...", "players": [{"discord_id": "111..." | null, ...}, ...]},
     "team_b": {...}}
"""
from __future__ import annotations

import logging

import discord

from services.shameless_events import EVENT_TEAMS_FORMED, ShamelessEvent, get_dispatcher

logger = logging.getLogger(__name__)


def _linked_discord_ids(team: dict) -> list[int]:
    return [int(p["discord_id"]) for p in team.get("players", []) if p.get("discord_id")]


def make_teams_formed_handler(bot, settings):
    async def on_teams_formed(event: ShamelessEvent) -> None:
        series_id = event.data.get("series_id")
        guild = bot.get_guild(settings.guild_id) if settings.guild_id else None
        if guild is None:
            raise RuntimeError(f"Shameless guild {settings.guild_id} introuvable")

        # résolution AVANT tout move : move_to(None) déconnecterait le membre.
        # Exception -> 500, la réservation est libérée et Shameless retente.
        targets = []
        for team_key, channel_id in (("team_a", settings.team1_voice_id), ("team_b", settings.team2_voice_id)):
            channel = guild.get_channel(channel_id) if channel_id else None
            if channel is None:
                raise RuntimeError(f"vocal d'équipe {channel_id} ({team_key}) introuvable")
            targets.append((event.data[team_key], channel))

        for team, channel in targets:
            for discord_id in _linked_discord_ids(team):
                member = guild.get_member(discord_id)
                # pas sur le serveur / pas en vocal : Discord ne permet pas de move
                if member is None or member.voice is None or member.voice.channel == channel:
                    continue
                try:
                    await member.move_to(channel, reason=f"Shameless: Teams de la Série {series_id}")
                except discord.HTTPException:
                    # un membre bloqué ne doit pas priver les autres de leur move
                    logger.exception("shameless %s: move de %s vers %s impossible", event.event_id, discord_id, channel.id)

    return on_teams_formed


def register_team_moves(bot, settings) -> None:
    get_dispatcher(bot).register(EVENT_TEAMS_FORMED, make_teams_formed_handler(bot, settings))


def unregister_team_moves(bot) -> None:
    get_dispatcher(bot).unregister(EVENT_TEAMS_FORMED)

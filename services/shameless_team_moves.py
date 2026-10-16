"""teams_formed (#4) : placer les Joueurs liés et connectés dans les vocaux d'équipe.

Un seul move, à la formation des Teams : les events de Game ne redéplacent personne,
les joueurs reviennent quand ils veulent. Mapping Team -> vocal et lecture du snapshot :
services.shameless_payloads.

Erreurs :
- config (serveur / vocal d'équipe introuvable) -> exception, 500, Shameless retente ;
- payload mal formé (Team absente, players null, discord_id invalide) -> ignoré et logué,
  l'event est traité : un retry ne le réparerait jamais.
"""
from __future__ import annotations

import logging

import discord

from services.shameless_events import ShamelessEvent
from services.shameless_payloads import linked_discord_ids, team_voice_ids, teams_of

logger = logging.getLogger(__name__)


def make_teams_formed_handler(bot, settings):
    async def on_teams_formed(event: ShamelessEvent) -> None:
        series_id = event.data.get("series_id")
        guild = bot.get_guild(settings.guild_id) if settings.guild_id else None
        if guild is None:
            raise RuntimeError(f"Shameless guild {settings.guild_id} introuvable")

        # résolution AVANT tout move : move_to(None) déconnecterait le membre.
        channels = {}
        for team_key, channel_id in team_voice_ids(settings).items():
            channel = guild.get_channel(channel_id) if channel_id else None
            if channel is None:
                raise RuntimeError(f"vocal d'équipe {channel_id} (Team {team_key}) introuvable")
            channels[team_key] = channel

        teams = teams_of(event.data)
        for team_key, channel in channels.items():
            team = teams.get(team_key)
            if team is None:
                logger.warning("shameless %s: Team %s absente du snapshot teams_formed", event.event_id, team_key)
                continue
            for discord_id in linked_discord_ids(team):
                member = guild.get_member(discord_id)
                # pas sur le serveur / pas en vocal : Discord ne permet pas de move.
                # Déjà dans le bon salon : no-op (un retry ne re-déplace personne).
                if member is None or member.voice is None or member.voice.channel == channel:
                    continue
                try:
                    await member.move_to(channel, reason=f"Shameless: Teams de la Série {series_id}")
                except discord.HTTPException:
                    # un membre bloqué ne doit pas priver les autres de leur move
                    logger.exception("shameless %s: move de %s vers %s impossible", event.event_id, discord_id, channel.id)

    return on_teams_formed

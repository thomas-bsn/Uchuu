"""Lecture défensive des snapshots Shameless (teams_formed / game_started / game_completed).

Seul endroit qui connaît la forme des Teams et des Joueurs : les handlers et le rendu
passent par ici. Tout champ peut manquer ou être mal typé -> on garde ce qui est
exploitable, on ignore le reste (un retry ne réparerait pas le payload).

    {"team_a": {"name": "...", "side": "blue", "players": [{"discord_id": "111..." | null, ...}]},
     "team_b": {...},
     "participant_discord_ids": ["111...", ...]}
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Team A / Team B du contrat (winner, series_score utilisent aussi "A" / "B")
TEAM_KEYS = ("A", "B")


def team_voice_ids(settings) -> dict[str, int | None]:
    """Team A -> vocal Team 1, Team B -> vocal Team 2, pour toute la Série (pas de lien
    avec les côtés bleu/rouge)."""
    return {"A": settings.team1_voice_id, "B": settings.team2_voice_id}


def teams_of(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """{"A": team_a, "B": team_b}, seulement les Teams présentes et bien formées."""
    teams = {}
    for key in TEAM_KEYS:
        team = data.get(f"team_{key.lower()}")
        if isinstance(team, dict):
            teams[key] = team
    return teams


def players_of(team: dict[str, Any]) -> list[dict[str, Any]]:
    players = team.get("players")
    if not isinstance(players, list):
        return []
    return [p for p in players if isinstance(p, dict)]


def parse_discord_id(raw: Any) -> int | None:
    """Snowflake Discord (string, ou int toléré) -> int ; None si absent ou invalide."""
    if isinstance(raw, bool) or raw is None or raw == "":
        return None
    if isinstance(raw, int):
        value = raw
    elif isinstance(raw, str) and raw.strip().isdigit():
        value = int(raw.strip())
    else:
        logger.warning("shameless: discord_id invalide ignoré : %r", raw)
        return None
    return value if value > 0 else None


def linked_discord_ids(team: dict[str, Any]) -> list[int]:
    """IDs Discord valides des Joueurs liés de la Team, dans l'ordre du snapshot."""
    ids = (parse_discord_id(p.get("discord_id")) for p in players_of(team))
    return [i for i in ids if i is not None]


def participant_discord_ids(data: dict[str, Any]) -> set[str]:
    """IDs Discord (string) des Joueurs de la Game : `participant_discord_ids` du contrat,
    sinon déduits des Teams."""
    raw = data.get("participant_discord_ids")
    if isinstance(raw, list):
        ids = (parse_discord_id(i) for i in raw)
    else:
        ids = (i for team in teams_of(data).values() for i in linked_discord_ids(team))
    return {str(i) for i in ids if i is not None}

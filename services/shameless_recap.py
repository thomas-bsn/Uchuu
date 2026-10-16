"""Rendu Discord des Games Shameless : annonce de Série (game_started) et récap (game_completed).

Les snapshots viennent de l'API (source de vérité) ; tout champ peut manquer -> on
affiche ce qu'on a, jamais de crash. Stats = contrat Shameless #52 (KDA, CS/min, KP,
dégâts, champion, rôle, note /100). Pas de vote MVP/DOFD ici (Phase 2).
"""
from __future__ import annotations

from typing import Any

import discord

from services.shameless_payloads import TEAM_KEYS, players_of, teams_of

BLUE = 0x3B82F6
GOLD = 0xF5B942

# Limites Discord des embeds
FIELD_VALUE_MAX = 1024
TITLE_MAX = 256


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _team_name(teams: dict[str, dict[str, Any]], key: str) -> str:
    return str(teams.get(key, {}).get("name") or f"Team {key}")


def _player_name(p: dict[str, Any]) -> str:
    return str(p.get("name") or "Joueur inconnu")


def _side(team: dict[str, Any]) -> str:
    side = str(team.get("side") or "").lower()
    return {"blue": " 🔵", "red": " 🔴"}.get(side, "")


def _series_label(data: dict[str, Any]) -> str:
    best_of = data.get("best_of")
    return f"Série BO{best_of}" if best_of else "Série"


def _link(data: dict[str, Any], web_url: str | None, *, url_key: str, id_key: str, path: str) -> str | None:
    """URL fournie par l'API, sinon {SHAMELESS_WEB_URL}/{path}/{id}."""
    if data.get(url_key):
        return str(data[url_key])
    if web_url and data.get(id_key):
        return f"{web_url.rstrip('/')}/{path}/{data[id_key]}"
    return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    return value if isinstance(value, (int, float)) else None


def _fmt_damage(value: float) -> str:
    return f"{value / 1000:.1f}k" if value >= 1000 else f"{value:g}"


def _fmt_duration(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 60}:{seconds % 60:02d}"


def player_line(p: dict[str, Any]) -> str:
    """« **Nom** · Zed MID · 12/3/7 · 7.9 CS/min · KP 61% · 31.2k dmg · 88/100 »."""
    parts = [f"**{_player_name(p)}**"]
    pick = " ".join(str(p[k]) for k in ("champion", "role") if p.get(k))
    if pick:
        parts.append(pick)
    kda = [_number(p.get(k)) for k in ("kills", "deaths", "assists")]
    if all(v is not None for v in kda):
        parts.append("/".join(f"{v:g}" for v in kda))
    cs_per_min = _number(p.get("cs_per_min"))
    if cs_per_min is not None:
        parts.append(f"{cs_per_min:.1f} CS/min")
    elif _number(p.get("cs")) is not None:
        parts.append(f"{p['cs']:g} CS")
    kp = _number(p.get("kill_participation"))  # ratio 0..1
    if kp is not None:
        parts.append(f"KP {round(kp * 100)}%")
    damage = _number(p.get("damage"))
    if damage is not None:
        parts.append(f"{_fmt_damage(damage)} dmg")
    score = _number(p.get("performance_score"))
    if score is not None:
        parts.append(f"{round(score)}/100")
    return " · ".join(parts)


def _kickoff(data: dict[str, Any]) -> str:
    number = _number(data.get("game_number"))
    if number is not None and number > 1:
        return f"La Game {number:g} commence, bonne chance à tous."
    return "La première Game commence, bonne chance à tous."


def series_announcement(data: dict[str, Any], web_url: str | None = None) -> discord.Embed:
    teams = teams_of(data)
    title = f"⚔️ {_series_label(data)} : {_team_name(teams, 'A')} vs {_team_name(teams, 'B')}"
    embed = discord.Embed(
        title=_clip(title, TITLE_MAX),
        description=_kickoff(data),
        color=BLUE,
    )
    url = _link(data, web_url, url_key="series_url", id_key="series_id", path="series")
    if url:
        embed.url = url
    for key in TEAM_KEYS:
        team = teams.get(key, {})
        names = "\n".join(_player_name(p) for p in players_of(team)) or "—"
        embed.add_field(name=_clip(_team_name(teams, key) + _side(team), TITLE_MAX), value=_clip(names, FIELD_VALUE_MAX), inline=True)
    return embed


def game_recap(data: dict[str, Any], web_url: str | None = None) -> discord.Embed:
    teams = teams_of(data)
    winner = data.get("winner") if data.get("winner") in TEAM_KEYS else None
    game_number = data.get("game_number")
    game_label = f"Game {game_number}" if game_number else "Game"

    if winner:
        title = f"🏆 {game_label} — Victoire de {_team_name(teams, winner)}"
    else:
        title = f"🏁 {game_label} terminée"
    embed = discord.Embed(title=_clip(title, TITLE_MAX), color=GOLD)

    score = data.get("series_score")
    infos = []
    if isinstance(score, dict) and _number(score.get("A")) is not None and _number(score.get("B")) is not None:
        infos.append(f"{_series_label(data)} : {_team_name(teams, 'A')} **{score['A']:g} - {score['B']:g}** {_team_name(teams, 'B')}")
    duration = _number(data.get("duration_seconds"))
    if duration is not None:
        infos.append(f"Durée : {_fmt_duration(duration)}")
    if infos:
        embed.description = "\n".join(infos)

    url = _link(data, web_url, url_key="recap_url", id_key="game_id", path="games")
    if url:
        embed.url = url

    for key in TEAM_KEYS:
        team = teams.get(key, {})
        crown = " 🏆" if key == winner else ""
        lines = "\n".join(player_line(p) for p in players_of(team)) or "—"
        embed.add_field(name=_clip(_team_name(teams, key) + _side(team) + crown, TITLE_MAX), value=_clip(lines, FIELD_VALUE_MAX), inline=False)

    if url:
        embed.set_footer(text="Récap complet sur Shameless")
    return embed

"""Rendu Discord et vue persistante du vote MVP/DOFD d'une Game (#15).

Les Joueurs viennent de `GET /bot/games/{id}` (source de vérité de l'API) : ce module ne
décide ni de l'éligibilité ni du résultat. Le bulletin n'affiche **aucun** décompte ni
gagnant — les résultats (`GET /bot/games/{id}/votes`) ne sont lus qu'après la clôture.

La vue est persistante (tous les composants portent un `custom_id` stable incluant la Game) :
au redémarrage, le cog la reconstruit depuis SQLite et l'enregistre à nouveau.
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

import discord

logger = logging.getLogger(__name__)

GOLD = 0xF5B942
GREEN = 0x57E07A

# Limites Discord des embeds
FIELD_VALUE_MAX = 1024
TITLE_MAX = 256


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


# =========================
# custom_id STABLES (persistance de la vue)
# =========================

def mvp_custom_id(game_id: str | int) -> str:
    return f"vote:mvp:{game_id}"


def dofd_custom_id(game_id: str | int) -> str:
    return f"vote:dofd:{game_id}"


def submit_custom_id(game_id: str | int) -> str:
    return f"vote:submit:{game_id}"


# =========================
# LECTURE DU CONTEXTE (GameDuBot)
# =========================

def players_of_context(game: dict[str, Any]) -> list[dict[str, Any]]:
    """Les dix Joueurs du contexte : `[{playerId, prenom, discordId}]` (les mieux formés)."""
    players: list[dict[str, Any]] = []
    for key in ("teamA", "teamB"):
        team = game.get(key)
        if not isinstance(team, list):
            continue
        for raw in team:
            if not isinstance(raw, dict):
                continue
            player_id = raw.get("playerId")
            if isinstance(player_id, bool) or not isinstance(player_id, int):
                continue
            discord_id = raw.get("discordId")
            players.append(
                {
                    "playerId": player_id,
                    "prenom": str(raw.get("prenom") or f"Joueur {player_id}"),
                    "discordId": str(discord_id) if discord_id is not None else None,
                }
            )
    return players


def linked_player_id(players: list[dict[str, Any]], discord_id: int | str) -> int | None:
    """Le `playerId` du votant s'il est l'un des Joueurs de la Game (compte Discord lié)."""
    for player in players:
        if player.get("discordId") is not None and player["discordId"] == str(discord_id):
            return player["playerId"]
    return None


def _game_label(game: dict[str, Any]) -> str:
    number = game.get("gameNumber")
    return f"Game {number}" if number else "Game"


# =========================
# EMBEDS
# =========================

def bulletin_embed(game: dict[str, Any]) -> discord.Embed:
    """Bulletin MVP/DOFD : la composition, jamais un décompte."""
    players = players_of_context(game)
    embed = discord.Embed(
        title=_clip(f"🗳️ {_game_label(game)} — MVP & DOFD", TITLE_MAX),
        description=(
            "Choisis le **MVP** et le **DOFD** avec les menus ci-dessous, puis valide ton bulletin.\n"
            "Tu peux n'en choisir qu'un, ou t'abstenir : ton bulletin reste modifiable."
        ),
        color=GOLD,
    )
    for key, label in (("teamA", "Team A"), ("teamB", "Team B")):
        team = game.get(key)
        if not isinstance(team, list):
            continue
        names = "\n".join(
            str(p.get("prenom") or "Joueur inconnu") for p in team if isinstance(p, dict)
        ) or "—"
        embed.add_field(name=label, value=_clip(names, FIELD_VALUE_MAX), inline=True)
    embed.set_footer(text="Le vote se ferme 10 minutes après la fin de la Game.")
    return embed


def _titre_line(titre: dict[str, Any]) -> str:
    """Les gagnants (tous les ex æquo), puis le décompte — lisibles après la clôture."""
    gagnants = [pid for pid in (titre.get("gagnants") or [])]
    prenoms = {row.get("playerId"): str(row.get("prenom") or "") for row in (titre.get("decompte") or [])}
    if not gagnants:
        return "Aucun vote"
    names = ", ".join(prenoms.get(pid) or f"Joueur {pid}" for pid in gagnants)
    return f"**{names}**"


def decompte_line(titre: dict[str, Any]) -> str:
    rows = [
        f"{row.get('prenom') or row.get('playerId')} : {row.get('voix')}"
        for row in (titre.get("decompte") or [])
    ]
    return " · ".join(rows)


def results_embed(results: dict[str, Any]) -> discord.Embed:
    """Résultats de clôture : MVP et DOFD, tous les Joueurs à égalité reconnus."""
    embed = discord.Embed(
        title=_clip(f"🏆 Résultats des votes — Game {results.get('gameId')}", TITLE_MAX),
        color=GREEN,
    )
    for field, label in (("mvp", "MVP"), ("dofd", "DOFD")):
        titre = results.get(field) if isinstance(results.get(field), dict) else {}
        value = _titre_line(titre)
        decompte = decompte_line(titre)
        if decompte:
            value = f"{value}\n{decompte}"
        embed.add_field(name=label, value=_clip(value, FIELD_VALUE_MAX), inline=False)
    return embed


# =========================
# VUE PERSISTANTE
# =========================

# on_submit(interaction, mvp_player_id, dofd_player_id)
SubmitHandler = Callable[[discord.Interaction, int | None, int | None], Awaitable[None]]


class _ChoiceSelect(discord.ui.Select):
    def __init__(self, *, custom_id: str, placeholder: str, options: list[discord.SelectOption], on_choice):
        super().__init__(
            custom_id=custom_id, placeholder=placeholder, options=options, min_values=0, max_values=1
        )
        self._on_choice = on_choice

    async def callback(self, interaction: discord.Interaction) -> None:
        await self._on_choice(interaction, list(self.values))


class _SubmitButton(discord.ui.Button):
    def __init__(self, *, custom_id: str, on_click):
        super().__init__(label="Valider mon bulletin", style=discord.ButtonStyle.primary, custom_id=custom_id)
        self._on_click = on_click

    async def callback(self, interaction: discord.Interaction) -> None:
        await self._on_click(interaction)


class BulletinDeVote(discord.ui.View):
    """Bulletin MVP/DOFD d'une Game : un choix par titre, validé en un seul bulletin.

    Les sélections sont mémorisées par votant jusqu'à « Valider » ; l'API ne reçoit jamais
    deux bulletins partiels (le PUT porte MVP **et** DOFD). Aucun décompte n'est conservé :
    seul `on_submit` parle à l'API.
    """

    def __init__(self, *, game_id: str, players: list[dict[str, Any]], on_submit: SubmitHandler):
        super().__init__(timeout=None)
        self.game_id = game_id
        self.players = list(players)
        self._on_submit = on_submit
        self._pending: dict[int, dict[str, int | None]] = {}

        options = [
            discord.SelectOption(label=p["prenom"][:100], value=str(p["playerId"])) for p in self.players
        ]
        self.add_item(
            _ChoiceSelect(
                custom_id=mvp_custom_id(game_id),
                placeholder="MVP de la Game",
                options=options,
                on_choice=self._choice_made("mvp"),
            )
        )
        self.add_item(
            _ChoiceSelect(
                custom_id=dofd_custom_id(game_id),
                placeholder="DOFD de la Game",
                options=options,
                on_choice=self._choice_made("dofd"),
            )
        )
        self.add_item(_SubmitButton(custom_id=submit_custom_id(game_id), on_click=self.submit))

    def _choice_made(self, title: str):
        async def handler(interaction: discord.Interaction, values: list[str]) -> None:
            self.choose(interaction.user.id, title, int(values[0]) if values else None)
            # acquitte la sélection sans bruit ; le bulletin part au clic sur « Valider »
            await interaction.response.defer(ephemeral=True)

        return handler

    def choose(self, user_id: int, title: str, player_id: int | None) -> None:
        self._pending.setdefault(user_id, {})[title] = player_id

    async def submit(self, interaction: discord.Interaction) -> None:
        pending = self._pending.pop(interaction.user.id, {})
        await self._on_submit(interaction, pending.get("mvp"), pending.get("dofd"))

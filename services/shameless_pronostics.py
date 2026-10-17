"""Pronostics Shameless (#16) : composition de la Série, bulletin Discord et résultats.

Rendu et validation purs (pas d'I/O) : les appels HTTP et SQLite restent au cog. La
composition vient de l'aperçu `GET /bot/series/{id}/pronostics` — `teamA` / `teamB` de
`JoueurDuBot` (`playerId`, `prenom`, `discordId`). Les IDs Discord liés à ces Joueurs sont
exactement ceux qui ne peuvent PAS pronostiquer.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

import discord

from services.shameless_pronostics_store import TITLE_DOFD, TITLE_EQUIPE, TITLE_MVP
from services.shameless_recap import GOLD

TEAM_KEYS = ("A", "B")
_NO_CHOICE = "-"


@dataclass(frozen=True)
class PlayerChoice:
    """Un Joueur de la composition courante, tel que proposé au pronostic."""

    player_id: int
    prenom: str
    team: str  # "A" ou "B"


@dataclass(frozen=True)
class Composition:
    """La Game ouverte d'une Série et ses dix Joueurs."""

    series_id: int
    game_number: int
    best_of: int
    players: tuple[PlayerChoice, ...]
    linked_discord_ids: frozenset[str]

    @property
    def player_ids(self) -> frozenset[int]:
        return frozenset(p.player_id for p in self.players)

    def team_players(self, team: str) -> tuple[PlayerChoice, ...]:
        return tuple(p for p in self.players if p.team == team)


@dataclass(frozen=True)
class PronosticChoice:
    """Les trois choix d'un pronostic (`None` = pas de choix sur ce titre)."""

    equipe_gagnante: str | None = None
    mvp_player_id: int | None = None
    dofd_player_id: int | None = None

    def is_valid_for(self, composition: Composition) -> bool:
        if self.equipe_gagnante not in (None, *TEAM_KEYS):
            return False
        for player_id in (self.mvp_player_id, self.dofd_player_id):
            if player_id is not None and player_id not in composition.player_ids:
                return False
        return True


def composition_of(preview: object, series_id: int) -> Composition | None:
    """`PronosticsDeLaSerie` -> composition, ou None si aucune Game n'est ouverte.

    `gameNumber` null (Game lancée / Série terminée) ou composition illisible : rien à
    proposer (un retry ne réparerait pas le payload)."""
    if not isinstance(preview, dict):
        return None
    game_number = preview.get("gameNumber")
    if isinstance(game_number, bool) or not isinstance(game_number, int) or game_number <= 0:
        return None

    players: list[PlayerChoice] = []
    linked: set[str] = set()
    for team in TEAM_KEYS:
        raw_team = preview.get(f"team{team}")
        if not isinstance(raw_team, list):
            return None  # composition incomplète : on ne propose rien
        for raw_player in raw_team:
            if not isinstance(raw_player, dict):
                continue
            player_id = raw_player.get("playerId")
            if isinstance(player_id, bool) or not isinstance(player_id, int):
                continue
            prenom = raw_player.get("prenom")
            players.append(PlayerChoice(player_id, str(prenom or f"Joueur {player_id}"), team))
            discord_id = raw_player.get("discordId")
            if isinstance(discord_id, str) and discord_id:
                linked.add(discord_id)
    if not players:
        return None

    best_of = preview.get("bestOf")
    return Composition(
        series_id=series_id,
        game_number=game_number,
        best_of=best_of if isinstance(best_of, int) and not isinstance(best_of, bool) else 1,
        players=tuple(players),
        linked_discord_ids=frozenset(linked),
    )


def pronostics_embed(composition: Composition) -> discord.Embed:
    """Le bulletin proposé aux Spectateurs avant la Game."""
    embed = discord.Embed(
        title=f"🎯 Pronostics — Game {composition.game_number}",
        colour=GOLD,
        description=(
            "Devine l'équipe gagnante, le MVP et le DOFD de la prochaine Game.\n"
            "Choisis dans les menus ci-dessous : ton pronostic est transmis aussitôt."
        ),
    )
    for team in TEAM_KEYS:
        names = "\n".join(f"• {p.prenom}" for p in composition.team_players(team))
        if names:
            embed.add_field(name=f"Team {team}", value=names, inline=True)
    embed.set_footer(text="Verrouillé au lancement de la Game — ni point ni classement.")
    return embed


def result_embed(title: str, result: dict, winner: str | None = None) -> discord.Embed:
    """L'annonce d'un titre évalué : la bonne réponse et qui l'a vue juste."""
    if title == TITLE_EQUIPE:
        label = "Vainqueur"
        answer = _winner_answer(result, winner)
    elif title == TITLE_MVP:
        label = "MVP"
        answer = ", ".join(_correct_players(result, TITLE_MVP)) or "aucun Joueur"
    else:
        label = "DOFD"
        answer = ", ".join(_correct_players(result, TITLE_DOFD)) or "aucun Joueur"

    predictors = _correct_predictors(result, title)
    embed = discord.Embed(
        title=f"🎯 Pronostics — {label}",
        colour=GOLD,
        description=f"Réponse : **{answer}**",
    )
    embed.add_field(
        name="Bonnes prédictions",
        value=", ".join(predictors) if predictors else "personne",
        inline=False,
    )
    embed.set_footer(text="Ni point ni classement : juste la satisfaction d'avoir vu juste.")
    return embed


def _pronostics(result: dict) -> list[dict]:
    raw = result.get("pronostics")
    return [p for p in raw if isinstance(p, dict)] if isinstance(raw, list) else []


def _name_of(pronostic: dict) -> str:
    return str(pronostic.get("pronostiqueurNom") or pronostic.get("pronostiqueurDiscordId") or "?")


def _correct_choice(pronostic: dict, title: str) -> dict | None:
    choice = pronostic.get(title)
    if isinstance(choice, dict) and choice.get("correct") is True:
        return choice
    return None


def _correct_players(result: dict, title: str) -> list[str]:
    """Les Joueurs élus (MVP/DOFD) d'après les pronostics corrects, sans doublon."""
    prenoms: list[str] = []
    for pronostic in _pronostics(result):
        choice = _correct_choice(pronostic, title)
        if choice is None:
            continue
        prenom = choice.get("prenom")
        if isinstance(prenom, str) and prenom and prenom not in prenoms:
            prenoms.append(prenom)
    return prenoms


def _winner_answer(result: dict, winner: str | None) -> str:
    if winner in TEAM_KEYS:
        return f"Team {winner}"
    # re-vérification tardive sans l'event : on déduit des pronostics corrects
    for pronostic in _pronostics(result):
        choice = _correct_choice(pronostic, TITLE_EQUIPE)
        if choice and choice.get("equipe") in TEAM_KEYS:
            return f"Team {choice['equipe']}"
    return "inconnu"


def _correct_predictors(result: dict, title: str) -> list[str]:
    return [_name_of(p) for p in _pronostics(result) if _correct_choice(p, title) is not None]


# =========================
# BULLETIN DISCORD (menus persistants)
# =========================

class PronosticsView(discord.ui.View):
    """Bulletin persistant : chaque choix met à jour le pronostic du Spectateur et le
    transmet aussitôt (l'API remplace le pronostic entier)."""

    def __init__(self, composition: Composition, on_submit):
        super().__init__(timeout=None)
        self.composition = composition
        self._on_submit = on_submit
        self._choices: dict[int, PronosticChoice] = {}
        prefix = f"pronostics:{composition.series_id}:{composition.game_number}"
        self.winner = _WinnerSelect(self, f"{prefix}:winner")
        self.mvp = _PlayerSelect(self, f"{prefix}:mvp", "MVP pronostiqué")
        self.dofd = _PlayerSelect(self, f"{prefix}:dofd", "DOFD pronostiqué")
        for item in (self.winner, self.mvp, self.dofd):
            self.add_item(item)

    async def select_winner(self, interaction, equipe_gagnante: str | None) -> None:
        await self._update(interaction, equipe_gagnante=equipe_gagnante)

    async def select_mvp(self, interaction, player_id: int | None) -> None:
        await self._update(interaction, mvp_player_id=player_id)

    async def select_dofd(self, interaction, player_id: int | None) -> None:
        await self._update(interaction, dofd_player_id=player_id)

    async def _update(self, interaction, **changes) -> None:
        user_id = interaction.user.id
        choice = replace(self._choices.get(user_id, PronosticChoice()), **changes)
        self._choices[user_id] = choice
        await self._on_submit(interaction, self.composition, choice)


def _selected(values: list[str]) -> str | None:
    value = values[0] if values else _NO_CHOICE
    return None if value == _NO_CHOICE else value


class _WinnerSelect(discord.ui.Select):
    def __init__(self, view: PronosticsView, custom_id: str):
        super().__init__(
            placeholder="Équipe gagnante",
            custom_id=custom_id,
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(label="Team A", value="A"),
                discord.SelectOption(label="Team B", value="B"),
                discord.SelectOption(label="Aucune prédiction", value=_NO_CHOICE),
            ],
        )
        self._view = view

    async def callback(self, interaction):
        await self._view.select_winner(interaction, _selected(self.values))


class _PlayerSelect(discord.ui.Select):
    def __init__(self, view: PronosticsView, custom_id: str, placeholder: str):
        options = [discord.SelectOption(label=p.prenom, value=str(p.player_id)) for p in view.composition.players]
        options.append(discord.SelectOption(label="Aucune prédiction", value=_NO_CHOICE))
        super().__init__(
            placeholder=placeholder,
            custom_id=custom_id,
            min_values=1,
            max_values=1,
            options=options,
        )
        self._view = view
        self._is_mvp = custom_id.endswith(":mvp")

    async def callback(self, interaction):
        raw = _selected(self.values)
        player_id = None if raw is None else int(raw)
        if self._is_mvp:
            await self._view.select_mvp(interaction, player_id)
        else:
            await self._view.select_dofd(interaction, player_id)

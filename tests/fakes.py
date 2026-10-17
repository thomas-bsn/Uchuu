"""Fakes Discord + helpers webhook partagés par les tests Shameless.

Aucun appel Discord réel : les fakes enregistrent ce que le bot *ferait*
(moves, messages) pour que les tests vérifient les effets visibles.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from cogs.shameless_games import ShamelessGames


# =========================
# DISCORD FAKES
# =========================

@dataclass(eq=False)
class FakeMember:
    id: int
    bot: bool = False
    name: str = "member"
    voice_channel: "FakeVoiceChannel | None" = None
    moves: list[int | None] = field(default_factory=list)  # ids des salons cibles, dans l'ordre

    @property
    def voice(self):
        if self.voice_channel is None:
            return None
        return FakeVoiceState(channel=self.voice_channel)

    async def move_to(self, channel, *, reason: str | None = None):
        if self.voice_channel is not None:
            self.voice_channel.members.remove(self)
        self.voice_channel = channel
        if channel is not None:
            channel.members.append(self)
        self.moves.append(channel.id if channel is not None else None)


@dataclass
class FakeVoiceState:
    channel: "FakeVoiceChannel"


@dataclass(eq=False)
class FakeVoiceChannel:
    id: int
    members: list[FakeMember] = field(default_factory=list)
    position: int = 0
    name: str = "voice"
    guild: "FakeGuild | None" = None  # comme discord.VoiceChannel.guild

    def __post_init__(self):
        self.members = list(self.members)
        for member in self.members:
            member.voice_channel = self


@dataclass(eq=False)
class FakeTextChannel:
    id: int
    name: str = "text"
    sent: list[dict[str, Any]] = field(default_factory=list)  # kwargs de chaque send()

    async def send(self, content=None, **kwargs):
        self.sent.append({"content": content, **kwargs})
        return FakeMessage(channel=self, content=content, kwargs=kwargs)

    def views(self) -> list[Any]:
        """Vues attachées aux messages envoyés (persistantes pour #15)."""
        return [m["view"] for m in self.sent if m.get("view") is not None]


@dataclass(eq=False)
class FakeUser:
    id: int
    name: str = "member"
    bot: bool = False

    @property
    def display_name(self) -> str:
        return self.name


@dataclass(eq=False)
class FakeResponse:
    """Réponse d'une interaction : ce que le votant verrait (éphémère ou non)."""

    messages: list[dict[str, Any]] = field(default_factory=list)
    deferred: list[dict[str, Any]] = field(default_factory=list)
    modal: Any = None

    async def send_message(self, content=None, **kwargs):
        self.messages.append({"content": content, **kwargs})

    async def defer(self, **kwargs):
        self.deferred.append(kwargs)

    async def edit_message(self, **kwargs):
        self.messages.append({"edited": True, **kwargs})

    async def send_modal(self, modal):
        self.modal = modal


@dataclass(eq=False)
class FakeInteraction:
    """Interaction minimale vue par les composants (boutons / selecteurs)."""

    user: FakeUser
    message: Any = None
    response: FakeResponse = field(default_factory=FakeResponse)
    guild: Any = None
    channel: Any = None


@dataclass
class FakeMessage:
    channel: FakeTextChannel
    content: str | None
    kwargs: dict[str, Any]


@dataclass(eq=False)
class FakeGuild:
    id: int
    voice_channels: list[FakeVoiceChannel] = field(default_factory=list)
    text_channels: list[FakeTextChannel] = field(default_factory=list)
    extra_members: list[FakeMember] = field(default_factory=list)  # membres hors vocal

    def __post_init__(self):
        self.voice_channels = list(self.voice_channels)
        self.text_channels = list(self.text_channels)

    @property
    def members(self) -> list[FakeMember]:
        in_voice = [m for c in self.voice_channels for m in c.members]
        return in_voice + [m for m in self.extra_members if m not in in_voice]

    def add_voice_channel(self, channel_id: int, members=(), name: str = "voice") -> FakeVoiceChannel:
        channel = FakeVoiceChannel(channel_id, list(members), position=len(self.voice_channels), name=name, guild=self)
        self.voice_channels.append(channel)
        return channel

    def add_text_channel(self, channel_id: int, name: str = "text") -> FakeTextChannel:
        channel = FakeTextChannel(id=channel_id, name=name)
        self.text_channels.append(channel)
        return channel

    def add_member(self, member_id: int, *, bot: bool = False, voice: FakeVoiceChannel | None = None) -> FakeMember:
        member = FakeMember(member_id, bot=bot, name=f"member-{member_id}")
        if voice is not None:
            member.voice_channel = voice
            voice.members.append(member)
        else:
            self.extra_members.append(member)
        return member

    def get_member(self, member_id: int) -> FakeMember | None:
        return next((m for m in self.members if m.id == member_id), None)

    def get_channel(self, channel_id: int):
        return next((c for c in [*self.voice_channels, *self.text_channels] if c.id == channel_id), None)


class FakeBot:
    """Ce que les handlers / routes voient du bot : get_guild / get_channel + runtime_loop."""

    def __init__(self, guilds=(), runtime_loop=None):
        self.guilds: list[FakeGuild] = list(guilds)
        self.runtime_loop = runtime_loop
        self.loop = runtime_loop
        self.views: list[Any] = []  # vues persistantes enregistrées (add_view)

    def add_view(self, view, *, message_id: int | None = None):
        self.views.append(view)

    def add_guild(self, guild_id: int) -> FakeGuild:
        guild = FakeGuild(guild_id)
        self.guilds.append(guild)
        return guild

    def get_guild(self, guild_id: int) -> FakeGuild | None:
        return next((g for g in self.guilds if g.id == guild_id), None)

    def get_channel(self, channel_id: int):
        for guild in self.guilds:
            channel = guild.get_channel(channel_id)
            if channel is not None:
                return channel
        return None

    async def fetch_channel(self, channel_id: int):
        channel = self.get_channel(channel_id)
        if channel is None:
            raise LookupError(f"unknown channel {channel_id}")
        return channel


# =========================
# SHAMELESS GAMES (Annonce de Série / récap de Game) — partagé par #5 et #14
# =========================

GUILD_ID = 1000
SHARED, TEAM1, TEAM2, OTHER_VOICE = 2000, 2001, 2002, 2999  # SHARED : vocal quelconque, non configuré
OTHER_GUILD_ID, FOREIGN_VOICE = 4000, 4001
ANNOUNCE = 3000
VOTE = 3001  # salon des bulletins MVP/DOFD (#15)


def team(name, side, players):
    return {"name": name, "side": side, "players": players}


def player(name, discord_id, **stats):
    return {"name": name, "discord_id": discord_id, **stats}


TEAM_A = team("Les Chauves", "blue", [player(f"A{i}", str(100 + i)) for i in range(1, 6)])
TEAM_B = team("Les Barbus", "red", [player(f"B{i}", str(200 + i)) for i in range(1, 6)])
PARTICIPANTS = [p["discord_id"] for p in TEAM_A["players"] + TEAM_B["players"]]


def game_started(game_id="g-1", game_number=1, series_id="s-1", **extra):
    data = {
        "series_id": series_id,
        "game_id": game_id,
        "game_number": game_number,
        "best_of": 3,
        # même forme de Teams que teams_formed (#4)
        "team_a": TEAM_A,
        "team_b": TEAM_B,
        "participant_discord_ids": PARTICIPANTS,
        **extra,
    }
    return make_event("game_started", data)


def game_completed(game_id="g-1", game_number=1, series_id="s-1", **overrides):
    data = {
        "series_id": series_id,
        "game_id": game_id,
        "game_number": game_number,
        "best_of": 3,
        "winner": "A",
        "series_score": {"A": 1, "B": 0},
        "duration_seconds": 1834,
        "recap_url": f"https://shameless.example/games/{game_id}",
        "team_a": team("Les Chauves", "blue", [
            player("Zed Main", "101", champion="Zed", role="MID", kills=12, deaths=3, assists=7,
                   cs=243, cs_per_min=7.9, kill_participation=0.61, damage=31250, performance_score=88),
        ]),
        "team_b": team("Les Barbus", "red", [
            player("Feeder", "201", champion="Yuumi", role="SUPPORT", kills=0, deaths=11, assists=4,
                   cs=12, cs_per_min=0.4, kill_participation=0.33, damage=4100, performance_score=12),
        ]),
        "participant_discord_ids": PARTICIPANTS,
    }
    data.update(overrides)
    return make_event("game_completed", data)


async def load_games(bot, settings, api=None):
    """Le cog tel que chargé au boot : cog_load enregistre ses handlers sur le dispatcher.

    `api` : client Shameless injecté (tests de transmission #14) ; None -> construit depuis
    la config à la première transmission.
    """
    cog = ShamelessGames(bot, settings, api=api)
    await cog.cog_load()
    return cog


async def load_votes(bot, settings, api=None, clock=None):
    """Cog des votes MVP/DOFD (#15), chargé comme au boot (enregistre son handler)."""
    from cogs.shameless_votes import ShamelessVotes

    cog = ShamelessVotes(bot, settings, api=api, clock=clock or time.time)
    await cog.cog_load()
    return cog


# =========================
# CONTEXTE GAME (GameDuBot, #15) — Joueurs et comptes Discord liés
# =========================

VOTE_PLAYERS_A = [{"playerId": 10 + i, "prenom": f"A{i}", "discordId": str(100 + i)} for i in range(1, 6)]
VOTE_PLAYERS_B = [{"playerId": 20 + i, "prenom": f"B{i}", "discordId": str(200 + i)} for i in range(1, 6)]
VOTE_PLAYERS = VOTE_PLAYERS_A + VOTE_PLAYERS_B


def iso(epoch: float) -> str:
    """Horodatage ISO 8601 UTC, comme `completedAt` du contrat."""
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def game_du_bot(
    game_id=1,
    *,
    completed_at: str | None = "2026-10-17T20:00:00Z",
    status: str = "completed",
    winner: str | None = "A",
    team_a=None,
    team_b=None,
    series_id=1,
    game_number=1,
    best_of=1,
) -> dict[str, Any]:
    """Réponse `GameDuBot` de `GET /bot/games/{id}` (dix Joueurs, chacun lié à un compte)."""
    return {
        "gameId": game_id,
        "seriesId": series_id,
        "gameNumber": game_number,
        "bestOf": best_of,
        "status": status,
        "startedAt": "2026-10-17T19:30:00Z",
        "completedAt": completed_at,
        "winner": winner if status == "completed" else None,
        "teamA": team_a if team_a is not None else VOTE_PLAYERS_A,
        "teamB": team_b if team_b is not None else VOTE_PLAYERS_B,
    }


# =========================
# INTERACTIONS DISCORD (View / Select / Button) — #15
# =========================

def view_of(channel, index: int = -1):
    """La vue attachée au message `index` du salon (persistante pour #15)."""
    return channel.views()[index]


def component(view, custom_id: str):
    return next(item for item in view.children if getattr(item, "custom_id", None) == custom_id)


async def choose(view, custom_id: str, interaction, values):
    """Sélectionne des valeurs dans un Select de la vue, comme Discord le ferait."""
    item = component(view, custom_id)
    item._values = list(values)  # ce que _refresh_state alimente avec interaction.data["values"]
    await item.callback(interaction)


async def press(view, custom_id: str, interaction):
    """Clique un bouton de la vue."""
    await component(view, custom_id).callback(interaction)


async def join(cog, member, channel):
    """Simule l'event gateway on_voice_state_update."""
    before = FakeVoiceState(member.voice_channel) if member.voice_channel else None
    if member.voice_channel is not None:
        member.voice_channel.members.remove(member)
    member.voice_channel = channel
    if channel is not None:
        channel.members.append(member)
    after = FakeVoiceState(channel) if channel else None
    await cog.on_voice_state_update(member, before, after)


# =========================
# SHAMELESS API FAKE (bot -> API)
# =========================

class PutSpectateurs(BaseModel):
    """`SignalerSpectateursRequest` du contrat OpenAPI (tag Bot)."""

    discordIds: list[str]


class Voter(BaseModel):
    """`VoterRequest` du contrat OpenAPI (tag Bot)."""

    votantDiscordId: str
    mvpPlayerId: int | None = None
    dofdPlayerId: int | None = None


@dataclass
class ApiCall:
    method: str
    path: str
    payload: Any
    authorization: str | None


class FakeShamelessApi:
    """Fausse API Shameless : une vraie app FastAPI servie par un transport httpx.

    Enregistre chaque appel (méthode, chemin, corps, Authorization) et applique la
    sémantique des routes `/bot` : clé inconnue -> 401, `status` forcé -> ProblemDetails,
    `PUT .../spectateurs` remplace l'ensemble, `PUT/GET .../votes` suit le contrat #15
    (éligibilité, auto-vote, clôture). `unreachable_transport()` simule une panne réseau.
    """

    BASE_URL = "https://api.shameless.test"
    BOT_TO_API_KEY = "test-bot-to-api-key"

    def __init__(self, api_key: str = BOT_TO_API_KEY):
        self.api_key = api_key
        self.calls: list[ApiCall] = []
        self.spectateurs: dict[int, list[str]] = {}
        self.games: dict[int, dict[str, Any]] = {}          # game_id -> GameDuBot
        self.votes: dict[int, dict[str, dict[str, Any]]] = {}  # game_id -> votant -> bulletin
        self.vote_status: dict[int, str] = {}               # game_id -> a_venir|ouverts|clos
        self.results: dict[int, dict[str, Any]] = {}        # game_id -> ResultatsDesVotes forcé
        self.status: int | None = None  # force la réponse (erreur API) ; None -> 200
        self.detail = "votes already closed"
        self.app = self._build_app()

    @property
    def base_url(self) -> str:
        return self.BASE_URL

    @property
    def transport(self) -> httpx.ASGITransport:
        return httpx.ASGITransport(app=self.app)

    def unreachable_transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        return httpx.MockTransport(handler)

    def _players(self, game_id: int) -> list[dict[str, Any]]:
        game = self.games.get(game_id) or {}
        return [*game.get("teamA", []), *game.get("teamB", [])]

    def _prenoms(self, game_id: int) -> dict[int, str]:
        return {p["playerId"]: p.get("prenom") or "Joueur inconnu" for p in self._players(game_id)}

    def _titre(self, game_id: int, field: str) -> dict[str, Any]:
        """`ResultatDuTitre` à la clôture : décompte trié (voix desc, prénom) + tous les ex æquo."""
        counts: dict[int, int] = {}
        for bulletin in self.votes.get(game_id, {}).values():
            player_id = bulletin.get(field)
            if player_id is not None:
                counts[player_id] = counts.get(player_id, 0) + 1
        prenoms = self._prenoms(game_id)
        decompte = sorted(
            ({"playerId": pid, "prenom": prenoms.get(pid, "Joueur inconnu"), "voix": voix} for pid, voix in counts.items()),
            key=lambda row: (-row["voix"], row["prenom"].lower(), row["playerId"]),
        )
        best = decompte[0]["voix"] if decompte else 0
        return {"gagnants": [row["playerId"] for row in decompte if row["voix"] == best], "decompte": decompte}

    def results_for(self, game_id: int) -> dict[str, Any]:
        """`ResultatsDesVotes` : décompte et gagnants vides tant que le vote n'est pas clos."""
        if game_id in self.results:
            return self.results[game_id]
        statut = self.vote_status.get(game_id, "ouverts")
        bulletins = self.votes.get(game_id, {})
        votants = sum(1 for b in bulletins.values() if b["mvpPlayerId"] is not None or b["dofdPlayerId"] is not None)
        hidden = {"gagnants": [], "decompte": []}
        titles = (
            {titre: self._titre(game_id, f"{titre}PlayerId") for titre in ("mvp", "dofd")}
            if statut == "clos"
            else {titre: dict(hidden) for titre in ("mvp", "dofd")}
        )
        completed = (self.games.get(game_id) or {}).get("completedAt")
        return {
            "gameId": game_id,
            "statut": statut,
            "ouvertureLe": completed,
            "fermetureLe": None,
            "votants": votants,
            **titles,
        }

    def _build_app(self) -> FastAPI:
        app = FastAPI()
        api = self

        def _refuse(game_id: int) -> None:
            if api.status is not None and api.status != 200:
                raise HTTPException(status_code=api.status, detail=api.detail)
            if game_id not in api.games and api.status is None:
                raise HTTPException(status_code=404, detail="Cette game n'existe pas.")

        @app.put("/bot/games/{game_id}/spectateurs")
        async def put_spectateurs(game_id: int, request: Request, payload: PutSpectateurs):
            authorization = request.headers.get("authorization")
            api.calls.append(ApiCall("PUT", request.url.path, payload.model_dump(), authorization))
            if authorization != f"Bearer {api.api_key}":
                raise HTTPException(status_code=401, detail="invalid shameless api key")
            if api.status is not None and api.status != 200:
                raise HTTPException(status_code=api.status, detail=api.detail)
            api.spectateurs[game_id] = list(payload.discordIds)  # remplace l'ensemble
            return {"gameId": game_id, "discordIds": api.spectateurs[game_id]}

        @app.get("/bot/games/{game_id}")
        async def get_game(game_id: int, request: Request):
            authorization = request.headers.get("authorization")
            api.calls.append(ApiCall("GET", request.url.path, None, authorization))
            if authorization != f"Bearer {api.api_key}":
                raise HTTPException(status_code=401, detail="invalid shameless api key")
            if api.status is not None and api.status != 200:
                raise HTTPException(status_code=api.status, detail=api.detail)
            game = api.games.get(game_id)
            if game is None:
                raise HTTPException(status_code=404, detail="Cette game n'existe pas.")
            return game

        @app.put("/bot/games/{game_id}/votes")
        async def put_votes(game_id: int, request: Request, payload: Voter):
            authorization = request.headers.get("authorization")
            api.calls.append(ApiCall("PUT", request.url.path, payload.model_dump(), authorization))
            if authorization != f"Bearer {api.api_key}":
                raise HTTPException(status_code=401, detail="invalid shameless api key")
            _refuse(game_id)
            statut = api.vote_status.get(game_id, "ouverts")
            if statut == "a_venir":
                raise HTTPException(status_code=409, detail="Les votes ouvrent à la fin de la game.")
            if statut == "clos":
                raise HTTPException(status_code=409, detail="Les votes de cette game sont clos.")
            if not payload.votantDiscordId.isascii() or not payload.votantDiscordId.isdigit():
                raise HTTPException(status_code=400, detail=f"« {payload.votantDiscordId} » n'est pas un ID Discord.")
            joueurs = api._players(game_id)
            joueurs_par_id = {p["playerId"]: p for p in joueurs}
            lies = {str(p["discordId"]) for p in joueurs if p.get("discordId")}
            eligibles = lies | set(api.spectateurs.get(game_id, []))
            if payload.votantDiscordId not in eligibles:
                raise HTTPException(
                    status_code=400,
                    detail="Seuls les dix Joueurs de la game et les Spectateurs présents en vocal peuvent voter.",
                )
            for titre, player_id in (("MVP", payload.mvpPlayerId), ("DOFD", payload.dofdPlayerId)):
                if player_id is None:
                    continue
                if player_id not in joueurs_par_id:
                    raise HTTPException(status_code=400, detail=f"Le {titre} doit être l'un des dix Joueurs de la game.")
                if str(joueurs_par_id[player_id].get("discordId")) == payload.votantDiscordId:
                    raise HTTPException(status_code=400, detail=f"Tu ne peux pas voter pour toi-même ({titre}).")
            api.votes.setdefault(game_id, {})[payload.votantDiscordId] = {
                "mvpPlayerId": payload.mvpPlayerId,
                "dofdPlayerId": payload.dofdPlayerId,
            }
            return {
                "gameId": game_id,
                "votantDiscordId": payload.votantDiscordId,
                "mvpPlayerId": payload.mvpPlayerId,
                "dofdPlayerId": payload.dofdPlayerId,
            }

        @app.get("/bot/games/{game_id}/votes")
        async def get_votes(game_id: int, request: Request):
            authorization = request.headers.get("authorization")
            api.calls.append(ApiCall("GET", request.url.path, None, authorization))
            if authorization != f"Bearer {api.api_key}":
                raise HTTPException(status_code=401, detail="invalid shameless api key")
            _refuse(game_id)
            return api.results_for(game_id)

        return app


# =========================
# WEBHOOK HELPERS
# =========================

WEBHOOK_SECRET = "test-webhook-secret"
WEBHOOK_PATH = "/internal/shameless/webhook"


def make_event(event_type: str, data: dict[str, Any] | None = None, *, event_id: str | None = None, version: int = 1) -> dict[str, Any]:
    """Enveloppe versionnée telle que Shameless l'envoie."""
    return {
        "version": version,
        "event_id": event_id or str(uuid.uuid4()),
        "type": event_type,
        "occurred_at": "2026-10-17T20:00:00Z",
        "data": data or {},
    }


def sign_webhook(body: bytes, secret: str = WEBHOOK_SECRET, *, timestamp: int | None = None) -> dict[str, str]:
    """Headers de signature : HMAC-SHA256(secret, f"{timestamp}.{body}")."""
    ts = str(int(time.time()) if timestamp is None else timestamp)
    digest = hmac.new(secret.encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()
    return {
        "X-Shameless-Timestamp": ts,
        "X-Shameless-Signature": f"sha256={digest}",
        "Content-Type": "application/json",
    }


def encode_event(event: dict[str, Any]) -> bytes:
    return json.dumps(event).encode()

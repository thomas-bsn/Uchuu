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
    `PUT .../spectateurs` remplace l'ensemble. `unreachable_transport()` simule une panne
    réseau, sans serveur.
    """

    BASE_URL = "https://api.shameless.test"
    BOT_TO_API_KEY = "test-bot-to-api-key"

    def __init__(self, api_key: str = BOT_TO_API_KEY):
        self.api_key = api_key
        self.calls: list[ApiCall] = []
        self.spectateurs: dict[int, list[str]] = {}
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

    def _build_app(self) -> FastAPI:
        app = FastAPI()
        api = self

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

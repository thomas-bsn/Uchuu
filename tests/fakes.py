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

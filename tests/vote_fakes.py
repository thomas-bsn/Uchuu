"""Fake du VoteGateway : un petit "serveur" en mémoire qui enregistre les effets
(rôles, DM, kicks, messages de vote, logs) que le module Vote demande."""
from __future__ import annotations

from dataclasses import dataclass, field

from services.vote_gateway import MemberInfo, MessageRef

VALIDATION_CHANNEL_ID = 20


class FakeClock:
    def __init__(self, now: float = 1_800_000_000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@dataclass
class FakeVoteMessage:
    vote_id: int
    content: str
    deleted: bool = False


@dataclass
class FakeVoteGateway:
    members: dict[int, MemberInfo] = field(default_factory=dict)
    messages: dict[int, FakeVoteMessage] = field(default_factory=dict)
    dms: list[tuple[int, str]] = field(default_factory=list)
    kicked: list[int] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)
    validation_channel_available: bool = True
    _next_message_id: int = 500

    # --- monde ---
    def add_member(self, member_id: int, *roles: int, bot: bool = False, joined_at: float | None = None) -> None:
        self.members[member_id] = MemberInfo(member_id, frozenset(roles), bot=bot, joined_at=joined_at)

    def roles_of(self, member_id: int) -> set[int]:
        return set(self.members[member_id].role_ids)

    def live_messages(self) -> list[FakeVoteMessage]:
        return [m for m in self.messages.values() if not m.deleted]

    def _set_roles(self, member_id: int, roles) -> None:
        info = self.members[member_id]
        self.members[member_id] = MemberInfo(member_id, frozenset(roles), bot=info.bot, joined_at=info.joined_at)

    # --- VoteGateway ---
    async def member(self, member_id: int) -> MemberInfo | None:
        return self.members.get(member_id)

    async def add_role(self, member_id: int, role_id: int, reason: str) -> bool:
        if member_id not in self.members:
            return False
        self._set_roles(member_id, self.roles_of(member_id) | {role_id})
        return True

    async def remove_role(self, member_id: int, role_id: int, reason: str) -> bool:
        if member_id not in self.members:
            return False
        self._set_roles(member_id, self.roles_of(member_id) - {role_id})
        return True

    async def send_dm(self, member_id: int, content: str) -> bool:
        self.dms.append((member_id, content))
        return True

    async def kick(self, member_id: int, reason: str) -> bool:
        if self.members.pop(member_id, None) is None:
            return False
        self.kicked.append(member_id)
        return True

    async def post_vote(self, vote_id: int, content: str) -> MessageRef | None:
        if not self.validation_channel_available:
            await self.log("❌ Salon de validation introuvable.")
            return None
        self._next_message_id += 1
        self.messages[self._next_message_id] = FakeVoteMessage(vote_id, content)
        return MessageRef(VALIDATION_CHANNEL_ID, self._next_message_id)

    async def edit_vote(self, ref: MessageRef, content: str) -> None:
        message = self.messages.get(ref.message_id)
        if message is not None and not message.deleted:
            message.content = content

    async def delete_vote(self, ref: MessageRef) -> None:
        message = self.messages.get(ref.message_id)
        if message is not None:
            message.deleted = True

    async def log(self, content: str) -> None:
        self.logs.append(content)

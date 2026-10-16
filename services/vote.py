"""Module Vote : ouverture, bulletins, quorum, expiration et persistance de tout vote.

Ce qui diffère entre flux (Invité → Membre, Membre → Confiance) vit dans une
`VotePolicy` ; tous les effets Discord passent par le `VoteGateway`.
"""
from __future__ import annotations

import asyncio
import time
from typing import Callable, Iterable, Protocol

from services.vote_gateway import VoteGateway
from services.vote_store import APPROVED, CANCELLED, EXPIRED, OPEN, VoteRecord, VoteStore

REPLY_CLOSED = "Ce vote est terminé."
REPLY_SELF_VOTE = "Tu ne peux pas voter pour toi-même."
REPLY_NOT_ALLOWED = "Seuls les membres Confiance peuvent voter."
REPLY_ALREADY_COUNTED = "Ton vote est déjà compté."


def mentions(user_ids: Iterable[int]) -> str:
    """Mentions des votants, formatées en un seul endroit."""
    return ", ".join(f"<@{uid}>" for uid in user_ids) or "aucun"


class VotePolicy(Protocol):
    """Ce qui distingue un flux de vote. `kind` est persisté avec chaque vote."""

    kind: str
    window_seconds: int

    async def on_open(self, gateway: VoteGateway, target_id: int) -> bool:
        """Prépare la cible (ex. rôle Invité). False = ne pas ouvrir le vote."""

    def render(self, vote: VoteRecord, approvals_required: int) -> str:
        """Texte du message de vote (compteur, expiration)."""

    async def on_approved(self, gateway: VoteGateway, vote: VoteRecord) -> str:
        """Effets du quorum (changement de rôle) ; renvoie le log à publier."""

    async def on_expired(self, gateway: VoteGateway, vote: VoteRecord) -> str:
        """Effets d'une expiration sans quorum (= refus) ; renvoie le log à publier."""


class Votes:
    def __init__(
        self,
        store: VoteStore,
        gateway: VoteGateway,
        policies: Iterable[VotePolicy],
        *,
        approvals_required: int,
        voter_role_id: int,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.store = store
        self.gateway = gateway
        self.policies = {policy.kind: policy for policy in policies}
        self.approvals_required = approvals_required
        self.voter_role_id = voter_role_id
        self.clock = clock

    async def open(self, kind: str, target_id: int) -> VoteRecord | None:
        """Ouvre un vote sur la cible (au plus un vote ouvert par cible et politique).

        None si la politique refuse l'ouverture ou si le message de vote ne peut
        pas être posté (le problème est loggé par le gateway).
        """
        policy = self.policies[kind]
        existing = await asyncio.to_thread(self.store.find_open, kind, target_id)
        if existing is not None:
            return existing
        if not await policy.on_open(self.gateway, target_id):
            return None
        now = self.clock()
        vote_id = await asyncio.to_thread(self.store.create, kind, target_id, now, now + policy.window_seconds)
        vote = await asyncio.to_thread(self.store.get, vote_id)
        ref = await self.gateway.post_vote(vote_id, policy.render(vote, self.approvals_required))
        if ref is None:
            await asyncio.to_thread(self.store.close, vote_id, CANCELLED, now)
            return None
        await asyncio.to_thread(self.store.set_message, vote_id, ref)
        return await asyncio.to_thread(self.store.get, vote_id)

    async def approve(self, vote_id: int, voter_id: int) -> str:
        """Bulletin ✅ d'un votant ; renvoie la réponse éphémère à lui afficher."""
        vote = await asyncio.to_thread(self.store.get, vote_id)
        if vote is None or vote.status != OPEN:
            return REPLY_CLOSED
        if voter_id == vote.target_id:
            return REPLY_SELF_VOTE
        voter = await self.gateway.member(voter_id)
        if voter is None or self.voter_role_id not in voter.role_ids:
            return REPLY_NOT_ALLOWED
        if not await asyncio.to_thread(self.store.add_ballot, vote_id, voter_id, self.clock()):
            return REPLY_ALREADY_COUNTED

        vote = await asyncio.to_thread(self.store.get, vote_id)
        policy = self.policies[vote.kind]
        count = f"{len(vote.approvers)}/{self.approvals_required}"
        if len(vote.approvers) < self.approvals_required:
            if vote.message is not None:
                await self.gateway.edit_vote(vote.message, policy.render(vote, self.approvals_required))
            return f"Vote enregistré ({count})."
        if not await asyncio.to_thread(self.store.close, vote_id, APPROVED, self.clock()):
            return REPLY_CLOSED  # clôturé entre-temps (autre clic ou expiration)
        log = await policy.on_approved(self.gateway, vote)
        await self._finish(vote, log)
        return f"Vote enregistré ({count}) : quorum atteint."

    async def expire_due(self, now: float | None = None) -> list[int]:
        """Clôt chaque vote ouvert dont l'échéance est passée ; renvoie leurs ids."""
        now = self.clock() if now is None else now
        expired = []
        for vote in await asyncio.to_thread(self.store.due, now):
            if not await asyncio.to_thread(self.store.close, vote.id, EXPIRED, now):
                continue  # approuvé entre-temps
            log = await self.policies[vote.kind].on_expired(self.gateway, vote)
            await self._finish(vote, log)
            expired.append(vote.id)
        return expired

    async def _finish(self, vote: VoteRecord, log: str) -> None:
        if vote.message is not None:
            await self.gateway.delete_vote(vote.message)
        await self.gateway.log(log)

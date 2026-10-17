"""Module Vote : ouverture, bulletins, quorum, expiration et persistance de tout vote.

Ce qui diffère entre flux (Invité → Membre, Membre → Confiance) vit dans une
`VotePolicy` ; tous les effets Discord passent par le `VoteGateway`.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable, Iterable, Protocol, runtime_checkable

from services.vote_gateway import VoteGateway
from services.vote_store import VoteRecord, VoteStore
from services.vote_types import MemberInfo, VoteKind, VoteStatus

logger = logging.getLogger(__name__)

RETRY_SECONDS = 300  # délai entre deux tentatives de complétion d'un même vote (évite le spam de logs)

REPLY_CLOSED = "Ce vote est terminé."
REPLY_SELF_VOTE = "Tu ne peux pas voter pour toi-même."
REPLY_NOT_ALLOWED = "Seuls les membres Confiance peuvent voter."
REPLY_ALREADY_COUNTED = "Ton vote est déjà compté."
REPLY_RECORDED_ALREADY_APPROVED = "Vote enregistré : le quorum venait déjà d'être atteint."
REPLY_RECORDED_ALREADY_EXPIRED = "Vote enregistré, mais le délai du vote était déjà écoulé."
REPLY_UNKNOWN_KIND = "Ce vote ne peut pas être traité pour le moment."


def mentions(user_ids: Iterable[int]) -> str:
    """Mentions des votants, formatées en un seul endroit."""
    return ", ".join(f"<@{uid}>" for uid in user_ids) or "aucun"


class VotePolicy(Protocol):
    """Ce qui distingue un flux de vote. `kind` est persisté avec chaque vote."""

    kind: VoteKind
    window_seconds: int

    async def prepare(self, gateway: VoteGateway, target_id: int) -> bool:
        """Prépare la cible (ex. rôle Invité). False = échec : le vote reste ouvert et le
        tick (`Votes.reconcile`) réessaie jusqu'à réussite ou clôture."""

    def render(self, vote: VoteRecord, approvals_required: int) -> str:
        """Texte du message de vote (compteur, expiration)."""

    async def on_approved(self, gateway: VoteGateway, vote: VoteRecord) -> str:
        """Effets du quorum (changement de rôle) ; renvoie le log à publier."""

    async def on_expired(self, gateway: VoteGateway, vote: VoteRecord) -> str:
        """Effets d'une expiration sans quorum (= refus) ; renvoie le log à publier."""


@runtime_checkable
class ScannedPolicy(VotePolicy, Protocol):
    """Politique dont les cibles sont proposées par un scan périodique (`Votes.scan`)."""

    cooldown_seconds: int  # délai après un vote expiré avant de reproposer la cible

    def is_candidate(self, member: MemberInfo, now: float) -> bool:
        """Le membre peut-il être proposé (rôles, ancienneté) ?"""


@runtime_checkable
class ArrivalPolicy(VotePolicy, Protocol):
    """Politique ouverte à l'arrivée d'un membre ; rattrapée au démarrage (`Votes.catch_up_arrivals`)."""

    def is_newcomer(self, member: MemberInfo) -> bool:
        """Le membre attend-il encore ce vote (pas un bot, aucun rôle du parcours) ?"""


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
        retry_seconds: float = RETRY_SECONDS,
    ) -> None:
        self.store = store
        self.gateway = gateway
        self.policies: dict[VoteKind, VotePolicy] = {policy.kind: policy for policy in policies}
        self.scanned: dict[VoteKind, ScannedPolicy] = {
            policy.kind: policy for policy in self.policies.values() if isinstance(policy, ScannedPolicy)
        }
        self.arrivals: dict[VoteKind, ArrivalPolicy] = {
            policy.kind: policy for policy in self.policies.values() if isinstance(policy, ArrivalPolicy)
        }
        self.approvals_required = approvals_required
        self.voter_role_id = voter_role_id
        self.clock = clock
        self.retry_seconds = retry_seconds
        self._in_flight: set[int] = set()  # votes en cours de complétion (open / reconcile)
        self._last_attempt: dict[int, float] = {}  # vote incomplet -> dernière tentative
        self._reported_unknown: set[int] = set()  # votes sans politique déjà signalés

    async def open(self, kind: VoteKind, target_id: int) -> VoteRecord:
        """Ouvre un vote sur la cible (au plus un vote ouvert par cible et politique).

        Le vote est ouvert (et son échéance court) même si la préparation de la cible
        ou l'envoi du message échoue : le gateway logge le problème et `reconcile`
        réessaie à chaque tick.
        """
        policy = self.policies[kind]
        existing = await asyncio.to_thread(self.store.find_open, kind, target_id)
        if existing is not None:
            return existing
        now = self.clock()
        vote_id = await asyncio.to_thread(self.store.create, kind, target_id, now, now + policy.window_seconds)
        await self._complete(policy, vote_id)
        return await asyncio.to_thread(self.store.get, vote_id)

    async def reconcile(self) -> None:
        """Complète chaque vote ouvert : cible pas encore préparée, message pas encore posté.
        Un même vote est retenté au plus toutes les `retry_seconds`."""
        now = self.clock()
        for vote in await asyncio.to_thread(self.store.open_votes):
            if vote.prepared and vote.message is not None:
                self._last_attempt.pop(vote.id, None)
                continue
            if now < self._last_attempt.get(vote.id, float("-inf")) + self.retry_seconds:
                continue
            policy = await self._policy_for(vote)
            if policy is not None:
                await self._complete(policy, vote.id)

    async def _complete(self, policy: VotePolicy, vote_id: int) -> None:
        if vote_id in self._in_flight:
            return  # déjà en cours (open et tick concurrents)
        self._in_flight.add(vote_id)
        self._last_attempt[vote_id] = self.clock()
        try:
            vote = await asyncio.to_thread(self.store.get, vote_id)  # état frais
            if vote is None or vote.status != VoteStatus.OPEN:
                return
            if not vote.prepared and await policy.prepare(self.gateway, vote.target_id):
                await asyncio.to_thread(self.store.set_prepared, vote_id)
            if vote.message is None:
                ref = await self.gateway.post_vote(vote_id, policy.render(vote, self.approvals_required))
                if ref is not None:
                    await asyncio.to_thread(self.store.set_message, vote_id, ref)
        finally:
            self._in_flight.discard(vote_id)

    async def heartbeat(self) -> None:
        """Note que le bot tourne (appelé à chaque tick) : borne le rattrapage au démarrage."""
        await asyncio.to_thread(self.store.set_heartbeat, self.clock())

    async def catch_up_arrivals(self, kind: VoteKind) -> list[VoteRecord]:
        """Au démarrage : ouvre le vote des membres arrivés depuis le dernier heartbeat
        (bot arrêté) et toujours sans rôle du parcours. Premier démarrage (aucun
        heartbeat) : n'ouvre rien, jamais de vote en masse pour les membres existants.
        Renvoie les votes ouverts."""
        policy = self.arrivals[kind]  # KeyError : ce type de vote ne s'ouvre pas à l'arrivée
        last_seen = await asyncio.to_thread(self.store.heartbeat)
        opened = []
        if last_seen is not None:
            for member in await self.gateway.members():
                joined_while_down = member.joined_at is not None and member.joined_at > last_seen
                if joined_while_down and policy.is_newcomer(member):
                    opened.append(await self.open(kind, member.id))
        await self.heartbeat()
        return opened

    async def scan(self, kind: VoteKind) -> list[VoteRecord]:
        """Ouvre un vote pour chaque candidat d'une `ScannedPolicy` : jamais deux votes
        ouverts pour une cible, ni avant la fin du cooldown après un vote expiré.
        Renvoie les seuls votes nouvellement ouverts."""
        policy = self.scanned[kind]  # KeyError : ce type de vote n'a pas de scan
        now = self.clock()
        opened = []
        for member in await self.gateway.members():
            if not policy.is_candidate(member, now):
                continue
            if await asyncio.to_thread(self.store.find_open, kind, member.id) is not None:
                continue  # déjà en vote : rien de reposté
            last_expired = await asyncio.to_thread(self.store.last_closed_at, kind, member.id, VoteStatus.EXPIRED)
            if last_expired is not None and now < last_expired + policy.cooldown_seconds:
                continue
            vote = await self.open(kind, member.id)
            if vote is not None:
                opened.append(vote)
        return opened

    async def approve(self, vote_id: int, voter_id: int) -> str:
        """Bulletin ✅ d'un votant ; renvoie la réponse éphémère à lui afficher."""
        vote = await asyncio.to_thread(self.store.get, vote_id)
        if vote is None or vote.status != VoteStatus.OPEN:
            return REPLY_CLOSED
        policy = await self._policy_for(vote)
        if policy is None:
            return REPLY_UNKNOWN_KIND
        if voter_id == vote.target_id:
            return REPLY_SELF_VOTE
        voter = await self.gateway.member(voter_id)
        if voter is None or self.voter_role_id not in voter.role_ids:
            return REPLY_NOT_ALLOWED
        if not await asyncio.to_thread(self.store.add_ballot, vote_id, voter_id, self.clock()):
            return REPLY_ALREADY_COUNTED

        vote = await asyncio.to_thread(self.store.get, vote_id)
        count = f"{len(vote.approvers)}/{self.approvals_required}"
        if len(vote.approvers) < self.approvals_required:
            if vote.message is not None:
                await self.gateway.edit_vote(vote.message, policy.render(vote, self.approvals_required))
            return f"Vote enregistré ({count})."
        if not await asyncio.to_thread(self.store.close, vote_id, VoteStatus.APPROVED, self.clock()):
            # Clôturé entre-temps par un autre clic ou l'expiration : le bulletin est
            # bien enregistré, mais la décision était déjà prise.
            closed = await asyncio.to_thread(self.store.get, vote_id)
            if closed.status == VoteStatus.APPROVED:
                return REPLY_RECORDED_ALREADY_APPROVED
            return REPLY_RECORDED_ALREADY_EXPIRED
        log = await policy.on_approved(self.gateway, vote)
        await self._finish(vote, log)
        return f"Vote enregistré ({count}) : quorum atteint."

    async def expire_due(self, now: float | None = None) -> list[int]:
        """Clôt chaque vote ouvert dont l'échéance est passée ; renvoie leurs ids."""
        now = self.clock() if now is None else now
        expired = []
        for vote in await asyncio.to_thread(self.store.due, now):
            policy = await self._policy_for(vote)
            if policy is None:
                continue  # laissé ouvert, intact
            if not await asyncio.to_thread(self.store.close, vote.id, VoteStatus.EXPIRED, now):
                continue  # approuvé entre-temps
            log = await policy.on_expired(self.gateway, vote)
            await self._finish(vote, log)
            expired.append(vote.id)
        return expired

    async def _policy_for(self, vote: VoteRecord) -> VotePolicy | None:
        """Politique du vote ; None (signalé une fois, statut inchangé) si ce code ne
        connaît pas son type : base partagée avec une autre version, ligne corrompue."""
        policy = self.policies.get(vote.kind)
        if policy is None and vote.id not in self._reported_unknown:
            self._reported_unknown.add(vote.id)
            logger.warning("vote %s : type %r sans politique, ignoré", vote.id, vote.kind)
            await self.gateway.log(
                f"⚠️ [votes] vote {vote.id} : type « {getattr(vote.kind, 'value', vote.kind)} » inconnu, "
                "ignoré (ni clôturé ni modifié)."
            )
        return policy

    async def _finish(self, vote: VoteRecord, log: str) -> None:
        if vote.message is not None:
            await self.gateway.delete_vote(vote.message)
        await self.gateway.log(log)

"""Types de données du module Vote, sans dépendance à discord.py (le store les importe)."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class VoteKind(str, Enum):
    """Flux de vote ; la valeur est persistée telle quelle (colonne `votes.kind`)."""

    INVITE = "invite"
    CONFIANCE = "confiance"


class VoteStatus(str, Enum):
    """Statut persisté d'un vote (colonne `votes.status`)."""

    OPEN = "open"
    APPROVED = "approved"
    EXPIRED = "expired"
    CANCELLED = "cancelled"  # historique : plus produit, conservé pour les anciennes lignes


@dataclass(frozen=True)
class MemberInfo:
    id: int
    role_ids: frozenset[int]
    bot: bool = False
    joined_at: float | None = None  # timestamp UTC d'arrivée sur le serveur


@dataclass(frozen=True)
class MessageRef:
    channel_id: int
    message_id: int

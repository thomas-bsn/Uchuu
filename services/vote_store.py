"""Persistance SQLite des votes (fichier dédié VOTES_DB_PATH).

Les votes clos restent en base avec leur statut et leur date de clôture : un clic
tardif reçoit "vote terminé", et une politique peut s'appuyer sur l'historique
(ex. cooldown Confiance après un vote expiré).
"""
from __future__ import annotations

from dataclasses import dataclass

from services.shameless_store import SqliteStore
from services.vote_gateway import MessageRef

OPEN = "open"
APPROVED = "approved"
EXPIRED = "expired"
CANCELLED = "cancelled"  # message de vote impossible à poster


@dataclass(frozen=True)
class VoteRecord:
    id: int
    kind: str
    target_id: int
    opened_at: float
    expires_at: float
    status: str
    message: MessageRef | None
    closed_at: float | None
    approvers: tuple[int, ...]  # dans l'ordre des votes


class VoteStore(SqliteStore):
    SCHEMA = (
        """
        CREATE TABLE IF NOT EXISTS votes (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            kind       TEXT NOT NULL,
            target_id  INTEGER NOT NULL,
            opened_at  REAL NOT NULL,
            expires_at REAL NOT NULL,
            status     TEXT NOT NULL,
            channel_id INTEGER,
            message_id INTEGER,
            closed_at  REAL
        )
        """,
        "CREATE INDEX IF NOT EXISTS votes_open ON votes (status, expires_at)",
        "CREATE INDEX IF NOT EXISTS votes_target ON votes (kind, target_id)",
        """
        CREATE TABLE IF NOT EXISTS vote_ballots (
            vote_id  INTEGER NOT NULL REFERENCES votes(id),
            voter_id INTEGER NOT NULL,
            cast_at  REAL NOT NULL,
            PRIMARY KEY (vote_id, voter_id)
        )
        """,
    )

    def create(self, kind: str, target_id: int, opened_at: float, expires_at: float) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO votes (kind, target_id, opened_at, expires_at, status) VALUES (?, ?, ?, ?, ?)",
                (kind, target_id, opened_at, expires_at, OPEN),
            )
            return cur.lastrowid

    def set_message(self, vote_id: int, ref: MessageRef) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE votes SET channel_id = ?, message_id = ? WHERE id = ?",
                (ref.channel_id, ref.message_id, vote_id),
            )

    def get(self, vote_id: int) -> VoteRecord | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM votes WHERE id = ?", (vote_id,)).fetchone()
            return self._record(conn, row) if row else None

    def find_open(self, kind: str, target_id: int) -> VoteRecord | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM votes WHERE kind = ? AND target_id = ? AND status = ? ORDER BY id DESC LIMIT 1",
                (kind, target_id, OPEN),
            ).fetchone()
            return self._record(conn, row) if row else None

    def last_closed_at(self, kind: str, target_id: int, status: str) -> float | None:
        """Date de la dernière clôture de ce statut pour la cible (None si jamais)."""
        with self._conn() as conn:
            (closed_at,) = conn.execute(
                "SELECT MAX(closed_at) FROM votes WHERE kind = ? AND target_id = ? AND status = ?",
                (kind, target_id, status),
            ).fetchone()
            return closed_at

    def due(self, now: float) -> list[VoteRecord]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM votes WHERE status = ? AND expires_at <= ? ORDER BY expires_at",
                (OPEN, now),
            ).fetchall()
            return [self._record(conn, row) for row in rows]

    def add_ballot(self, vote_id: int, voter_id: int, cast_at: float) -> bool:
        """True si le bulletin est nouveau (un votant ne compte qu'une fois)."""
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO vote_ballots (vote_id, voter_id, cast_at) VALUES (?, ?, ?)",
                (vote_id, voter_id, cast_at),
            )
            return cur.rowcount == 1

    def close(self, vote_id: int, status: str, closed_at: float) -> bool:
        """Clôt un vote ouvert ; False s'il était déjà clos (une seule clôture gagne)."""
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE votes SET status = ?, closed_at = ? WHERE id = ? AND status = ?",
                (status, closed_at, vote_id, OPEN),
            )
            return cur.rowcount == 1

    @staticmethod
    def _record(conn, row) -> VoteRecord:
        (vote_id, kind, target_id, opened_at, expires_at, status, channel_id, message_id, closed_at) = row
        approvers = tuple(
            voter for (voter,) in conn.execute(
                "SELECT voter_id FROM vote_ballots WHERE vote_id = ? ORDER BY cast_at, rowid", (vote_id,)
            )
        )
        message = MessageRef(channel_id, message_id) if message_id is not None else None
        return VoteRecord(vote_id, kind, target_id, opened_at, expires_at, status, message, closed_at, approvers)

"""Persistance SQLite des votes (fichier dédié VOTES_DB_PATH).

Les votes clos restent en base avec leur statut et leur date de clôture : un clic
tardif reçoit "vote terminé", et une politique peut s'appuyer sur l'historique
(ex. cooldown Confiance après un vote expiré).

Un vote ouvert peut être incomplet (`prepared` faux : cible pas encore préparée, ex.
rôle Invité refusé ; `message` absent : message de vote pas encore posté) : le tick
périodique du module Vote le complète. `vote_meta` garde le heartbeat du bot.
"""
from __future__ import annotations

from dataclasses import dataclass

from services.sqlite_store import SqliteStore
from services.vote_types import MessageRef, VoteKind, VoteStatus


@dataclass(frozen=True)
class VoteRecord:
    id: int
    kind: VoteKind | str  # str brut si le type stocké est inconnu de ce code
    target_id: int
    opened_at: float
    expires_at: float
    status: VoteStatus
    message: MessageRef | None
    closed_at: float | None
    approvers: tuple[int, ...]  # dans l'ordre des votes
    prepared: bool = False  # la politique a préparé la cible (ex. rôle Invité donné)


_COLUMNS = "id, kind, target_id, opened_at, expires_at, status, channel_id, message_id, closed_at, prepared"


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
            closed_at  REAL,
            prepared   INTEGER NOT NULL DEFAULT 0
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
        "CREATE TABLE IF NOT EXISTS vote_meta (key TEXT PRIMARY KEY, value REAL NOT NULL)",
    )

    def create_schema(self) -> None:
        super().create_schema()
        with self._conn() as conn:  # base créée avant la colonne `prepared` : votes déjà préparés
            columns = {row[1] for row in conn.execute("PRAGMA table_info(votes)")}
            if "prepared" not in columns:
                conn.execute("ALTER TABLE votes ADD COLUMN prepared INTEGER NOT NULL DEFAULT 1")

    def create(self, kind: VoteKind, target_id: int, opened_at: float, expires_at: float) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO votes (kind, target_id, opened_at, expires_at, status) VALUES (?, ?, ?, ?, ?)",
                (kind.value, target_id, opened_at, expires_at, VoteStatus.OPEN.value),
            )
            return cur.lastrowid

    def set_message(self, vote_id: int, ref: MessageRef) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE votes SET channel_id = ?, message_id = ? WHERE id = ?",
                (ref.channel_id, ref.message_id, vote_id),
            )

    def set_prepared(self, vote_id: int) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE votes SET prepared = 1 WHERE id = ?", (vote_id,))

    def get(self, vote_id: int) -> VoteRecord | None:
        with self._conn() as conn:
            row = conn.execute(f"SELECT {_COLUMNS} FROM votes WHERE id = ?", (vote_id,)).fetchone()
            return self._record(conn, row) if row else None

    def find_open(self, kind: VoteKind, target_id: int) -> VoteRecord | None:
        with self._conn() as conn:
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM votes WHERE kind = ? AND target_id = ? AND status = ? "
                "ORDER BY id DESC LIMIT 1",
                (kind.value, target_id, VoteStatus.OPEN.value),
            ).fetchone()
            return self._record(conn, row) if row else None

    def last_closed_at(self, kind: VoteKind, target_id: int, status: VoteStatus) -> float | None:
        """Date de la dernière clôture de ce statut pour la cible (None si jamais)."""
        with self._conn() as conn:
            (closed_at,) = conn.execute(
                "SELECT MAX(closed_at) FROM votes WHERE kind = ? AND target_id = ? AND status = ?",
                (kind.value, target_id, status.value),
            ).fetchone()
            return closed_at

    def open_votes(self) -> list[VoteRecord]:
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT {_COLUMNS} FROM votes WHERE status = ? ORDER BY id", (VoteStatus.OPEN.value,)
            ).fetchall()
            return [self._record(conn, row) for row in rows]

    def heartbeat(self) -> float | None:
        """Dernier instant où le bot tournait (None : jamais enregistré)."""
        with self._conn() as conn:
            row = conn.execute("SELECT value FROM vote_meta WHERE key = 'heartbeat'").fetchone()
            return row[0] if row else None

    def set_heartbeat(self, now: float) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO vote_meta (key, value) VALUES ('heartbeat', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (now,),
            )

    def due(self, now: float) -> list[VoteRecord]:
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT {_COLUMNS} FROM votes WHERE status = ? AND expires_at <= ? ORDER BY expires_at",
                (VoteStatus.OPEN.value, now),
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

    def close(self, vote_id: int, status: VoteStatus, closed_at: float) -> bool:
        """Clôt un vote ouvert ; False s'il était déjà clos (une seule clôture gagne)."""
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE votes SET status = ?, closed_at = ? WHERE id = ? AND status = ?",
                (status.value, closed_at, vote_id, VoteStatus.OPEN.value),
            )
            return cur.rowcount == 1

    @staticmethod
    def _record(conn, row) -> VoteRecord:
        (vote_id, kind, target_id, opened_at, expires_at, status, channel_id, message_id, closed_at, prepared) = row
        approvers = tuple(
            voter for (voter,) in conn.execute(
                "SELECT voter_id FROM vote_ballots WHERE vote_id = ? ORDER BY cast_at, rowid", (vote_id,)
            )
        )
        message = MessageRef(channel_id, message_id) if message_id is not None else None
        try:
            kind = VoteKind(kind)
        except ValueError:
            pass  # type inconnu : laissé brut, le module Vote le signale sans y toucher
        return VoteRecord(
            vote_id, kind, target_id, opened_at, expires_at, VoteStatus(status), message, closed_at, approvers,
            bool(prepared),
        )

"""Persistance SQLite locale de l'intégration Shameless.

Même fichier pour la dédup webhook et les tables des Games (#5) ; chaque store crée
ses propres tables sur la base partagée `services.sqlite_store.SqliteStore`.
"""
from __future__ import annotations

import time

from services.sqlite_store import SqliteStore

# Résultats de ProcessedEventStore.claim()
CLAIMED = "claimed"          # à nous d'exécuter le handler
IN_PROGRESS = "in_progress"  # une autre livraison l'exécute (lease encore valide)
DONE = "done"                # déjà traité : doublon


class ProcessedEventStore(SqliteStore):
    """event_id traité -> plus jamais ré-exécuté (même après redémarrage).

    Cycle : claim() AVANT le handler, puis mark_done() ; release() si le handler lève.
    Un claim "processing" a un lease : passé ce délai (crash, timeout), un retry de
    Shameless le reprend. Les effets Discord des handlers restent idempotents
    (posts gardés par GamePostsStore, moves sans effet si déjà dans le bon salon).
    """

    SCHEMA = (
        """
        CREATE TABLE IF NOT EXISTS shameless_processed_events (
            event_id   TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,
            status     TEXT NOT NULL,
            claimed_at REAL NOT NULL,
            done_at    REAL
        )
        """,
    )

    def claim(self, event_id: str, event_type: str, lease_seconds: float) -> str:
        now = time.time()
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO shameless_processed_events (event_id, event_type, status, claimed_at) "
                "VALUES (?, ?, 'processing', ?)",
                (event_id, event_type, now),
            )
            if cur.rowcount == 1:
                return CLAIMED
            # lease expiré -> on reprend (UPDATE conditionnel : un seul gagnant)
            cur = conn.execute(
                "UPDATE shameless_processed_events SET claimed_at = ? "
                "WHERE event_id = ? AND status = 'processing' AND claimed_at <= ?",
                (now, event_id, now - lease_seconds),
            )
            if cur.rowcount == 1:
                return CLAIMED
            row = conn.execute(
                "SELECT status FROM shameless_processed_events WHERE event_id = ?", (event_id,)
            ).fetchone()
        return DONE if row and row[0] == "done" else IN_PROGRESS

    def mark_done(self, event_id: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE shameless_processed_events SET status = 'done', done_at = ? WHERE event_id = ?",
                (time.time(), event_id),
            )

    def release(self, event_id: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM shameless_processed_events WHERE event_id = ? AND status = 'processing'",
                (event_id,),
            )

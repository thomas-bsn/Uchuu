"""Persistance SQLite locale de l'intégration Shameless.

`connect(db_path)` est partagé : d'autres tables (présences par Game, #5) peuvent
vivre dans le même fichier, chacune créée par son propre service.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path


def connect(db_path: str) -> sqlite3.Connection:
    """Connexion courte durée (une par opération) : sûre entre threads uvicorn / bot."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10, isolation_level=None)  # autocommit
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


class ProcessedEventStore:
    """event_id déjà pris en charge -> plus jamais ré-exécuté (même après redémarrage).

    Cycle : claim() AVANT le handler (persisté avant l'ack), puis mark_done().
    Si le handler lève, release() pour laisser Shameless retenter.
    Un claim resté "processing" (crash / timeout) n'est PAS rejoué : on préfère
    rater un effet Discord plutôt que le doubler.
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS shameless_processed_events (
                    event_id   TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    status     TEXT NOT NULL,
                    claimed_at REAL NOT NULL,
                    done_at    REAL
                )
                """
            )

    def _conn(self):
        return _Closing(connect(self.db_path))

    def claim(self, event_id: str, event_type: str) -> bool:
        """True si on vient de le réserver, False si déjà connu (doublon)."""
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO shameless_processed_events (event_id, event_type, status, claimed_at) "
                "VALUES (?, ?, 'processing', ?)",
                (event_id, event_type, time.time()),
            )
            return cur.rowcount == 1

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


class _Closing:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def __enter__(self) -> sqlite3.Connection:
        return self.conn

    def __exit__(self, *exc) -> None:
        self.conn.close()

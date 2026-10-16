"""SQLite des Games Shameless (#5) : messages déjà publiés + présences par Game.

Même fichier que la dédup webhook (shameless_store.connect) ; tables propres à ce module.
"""
from __future__ import annotations

import json
import time

from services.shameless_store import _Closing, connect


class GamePostsStore:
    """Annonce par Série / récap par Game : publiés au plus une fois, même si l'API
    republie avec un autre event_id, et après redémarrage."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS shameless_game_posts (
                    kind      TEXT NOT NULL,  -- 'series_announce' | 'game_recap'
                    key       TEXT NOT NULL,  -- series_id | game_id
                    posted_at REAL NOT NULL,
                    PRIMARY KEY (kind, key)
                )
                """
            )

    def _conn(self):
        return _Closing(connect(self.db_path))

    def claim(self, kind: str, key: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO shameless_game_posts (kind, key, posted_at) VALUES (?, ?, ?)",
                (kind, key, time.time()),
            )
            return cur.rowcount == 1

    def release(self, kind: str, key: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM shameless_game_posts WHERE kind = ? AND key = ?", (kind, key))


class GameAttendanceStore:
    """Présences vocales par Game : fenêtre ouverte par game_started, fermée par
    game_completed. On stocke les IDs Discord (string) des humains vus dans les salons
    configurés, hors Joueurs de la Game. Lu par le futur vote Spectateurs (Phase 2).
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS shameless_game_windows (
                    game_id         TEXT PRIMARY KEY,
                    participant_ids TEXT NOT NULL,  -- JSON : IDs Discord des Joueurs (exclus)
                    opened_at       REAL NOT NULL,
                    closed_at       REAL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS shameless_game_attendance (
                    game_id    TEXT NOT NULL,
                    discord_id TEXT NOT NULL,
                    seen_at    REAL NOT NULL,
                    PRIMARY KEY (game_id, discord_id)
                )
                """
            )

    def _conn(self):
        return _Closing(connect(self.db_path))

    def open_window(self, game_id: str, participant_ids: set[str]) -> None:
        # idempotent ; une fenêtre fermée n'est jamais rouverte
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO shameless_game_windows (game_id, participant_ids, opened_at) VALUES (?, ?, ?)",
                (game_id, json.dumps(sorted(participant_ids)), time.time()),
            )

    def close_window(self, game_id: str, participant_ids: set[str]) -> None:
        now = time.time()
        with self._conn() as conn:
            # game_started raté -> fenêtre créée directement fermée
            conn.execute(
                "INSERT OR IGNORE INTO shameless_game_windows (game_id, participant_ids, opened_at) VALUES (?, ?, ?)",
                (game_id, json.dumps(sorted(participant_ids)), now),
            )
            conn.execute(
                "UPDATE shameless_game_windows SET closed_at = ? WHERE game_id = ? AND closed_at IS NULL",
                (now, game_id),
            )

    def open_windows(self) -> dict[str, set[str]]:
        """game_id -> IDs Discord des Joueurs à exclure."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT game_id, participant_ids FROM shameless_game_windows WHERE closed_at IS NULL"
            ).fetchall()
        return {game_id: set(json.loads(ids)) for game_id, ids in rows}

    def record(self, game_id: str, discord_ids: set[str]) -> None:
        if not discord_ids:
            return
        now = time.time()
        with self._conn() as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO shameless_game_attendance (game_id, discord_id, seen_at) VALUES (?, ?, ?)",
                [(game_id, discord_id, now) for discord_id in discord_ids],
            )

    def spectators(self, game_id: str) -> list[str]:
        """IDs Discord des Spectateurs présents pendant la Game (snowflakes en string, triés)."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT discord_id FROM shameless_game_attendance WHERE game_id = ?", (game_id,)
            ).fetchall()
        return sorted((r[0] for r in rows), key=lambda i: (len(i), i))

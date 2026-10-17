"""SQLite des votes MVP/DOFD (#15) : fenêtre par Game, bulletin publié, résultats annoncés.

Même fichier que la dédup webhook (`sqlite_store.connect`) ; tables propres à ce module.
Une Game n'a qu'une fenêtre : `deadline` = `completedAt` + durée (10 min par défaut),
`posted_at`/`announced_at` rendent l'ouverture et l'annonce idempotentes. Au redémarrage,
`pending()` relit les fenêtres non annoncées : c'est l'API, jamais ce store, qui connaît
les résultats.
"""
from __future__ import annotations

import json
import time
from typing import Any

from services.sqlite_store import SqliteStore


class GameVoteStore(SqliteStore):
    """Fenêtre de vote d'une Game : échéance, Joueurs, bulletin publié, résultats annoncés."""

    SCHEMA = (
        """
        CREATE TABLE IF NOT EXISTS shameless_vote_windows (
            game_id      TEXT PRIMARY KEY,
            deadline     REAL NOT NULL,
            players      TEXT NOT NULL,  -- JSON [{playerId, prenom, discordId}]
            posted_at    REAL,
            announced_at REAL
        )
        """,
    )

    def open_window(self, game_id: str, deadline: float, players: list[dict[str, Any]]) -> bool:
        """Ouvre la fenêtre de vote d'une Game (idempotent) ; True si elle vient d'être créée."""
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO shameless_vote_windows (game_id, deadline, players) VALUES (?, ?, ?)",
                (game_id, deadline, json.dumps(players, ensure_ascii=False)),
            )
            return cur.rowcount == 1

    def claim_bulletin(self, game_id: str) -> bool:
        """Réserve la publication du bulletin ; False s'il a déjà été publié."""
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE shameless_vote_windows SET posted_at = ? WHERE game_id = ? AND posted_at IS NULL",
                (time.time(), game_id),
            )
            return cur.rowcount == 1

    def release_bulletin(self, game_id: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE shameless_vote_windows SET posted_at = NULL WHERE game_id = ?", (game_id,)
            )

    def claim_announce(self, game_id: str) -> bool:
        """Réserve l'annonce des résultats ; False si elle a déjà été faite."""
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE shameless_vote_windows SET announced_at = ? WHERE game_id = ? AND announced_at IS NULL",
                (time.time(), game_id),
            )
            return cur.rowcount == 1

    def release_announce(self, game_id: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE shameless_vote_windows SET announced_at = NULL WHERE game_id = ?", (game_id,)
            )

    def pending(self) -> list[tuple[str, float, list[dict[str, Any]]]]:
        """Fenêtres non annoncées : `(game_id, deadline, players)` — relues au redémarrage."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT game_id, deadline, players FROM shameless_vote_windows WHERE announced_at IS NULL"
            ).fetchall()
        return [(game_id, deadline, json.loads(players)) for game_id, deadline, players in rows]

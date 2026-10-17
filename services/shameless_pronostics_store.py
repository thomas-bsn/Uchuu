"""SQLite des Pronostics Shameless (#16).

Même fichier que la dédup webhook (`sqlite_store.connect`) ; tables propres à ce module :

- bullets déjà publiés par (Série, n° de Game) -> un seul bulletin, même si l'API republie
  l'event avec un autre `event_id` ou après redémarrage ;
- verrous : la Game qui vient d'être lancée (`game_started`) verrouille les pronostics de
  son numéro. Le verrou est l'état local, en plus du refus 409 de l'API ;
- résultats déjà annoncés par (Game, titre) : vainqueur, MVP et DOFD sortent séparément,
  chacun une seule fois ;
- Games en attente : celles dont un titre n'est pas encore connu (MVP/DOFD après clôture
  des votes) -> re-vérifiées par la boucle de réconciliation.
"""
from __future__ import annotations

import time

from services.sqlite_store import SqliteStore

TITLE_EQUIPE = "equipeGagnante"
TITLE_MVP = "mvp"
TITLE_DOFD = "dofd"
TITLES = (TITLE_EQUIPE, TITLE_MVP, TITLE_DOFD)


class PronosticsStore(SqliteStore):
    SCHEMA = (
        """
        CREATE TABLE IF NOT EXISTS shameless_pronostics_bulletins (
            series_id   INTEGER NOT NULL,
            game_number INTEGER NOT NULL,
            posted_at   REAL NOT NULL,
            PRIMARY KEY (series_id, game_number)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS shameless_pronostics_locks (
            series_id   INTEGER NOT NULL,
            game_number INTEGER NOT NULL,
            locked_at   REAL NOT NULL,
            PRIMARY KEY (series_id, game_number)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS shameless_pronostics_announcements (
            game_id       INTEGER NOT NULL,
            title         TEXT NOT NULL,
            announced_at  REAL NOT NULL,
            PRIMARY KEY (game_id, title)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS shameless_pronostics_pending (
            game_id     INTEGER PRIMARY KEY,
            series_id   INTEGER,
            game_number INTEGER,
            added_at    REAL NOT NULL
        )
        """,
    )

    def claim_bulletin(self, series_id: int, game_number: int) -> bool:
        """Réserve le bulletin (Série, Game) : True la première fois, False ensuite."""
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO shameless_pronostics_bulletins (series_id, game_number, posted_at)"
                " VALUES (?, ?, ?)",
                (series_id, game_number, time.time()),
            )
            return cur.rowcount == 1

    def release_bulletin(self, series_id: int, game_number: int) -> None:
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM shameless_pronostics_bulletins WHERE series_id = ? AND game_number = ?",
                (series_id, game_number),
            )

    def lock(self, series_id: int, game_number: int) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO shameless_pronostics_locks (series_id, game_number, locked_at)"
                " VALUES (?, ?, ?)",
                (series_id, game_number, time.time()),
            )

    def is_locked(self, series_id: int, game_number: int) -> bool:
        """La Game `game_number` de cette Série est-elle déjà lancée ? (pronostics verrouillés)"""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM shameless_pronostics_locks WHERE series_id = ? AND game_number = ?",
                (series_id, game_number),
            ).fetchone()
        return row is not None

    def claim_result(self, game_id: int, title: str) -> bool:
        """Réserve l'annonce d'un titre (vainqueur / MVP / DOFD) : une seule fois par Game."""
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO shameless_pronostics_announcements (game_id, title, announced_at)"
                " VALUES (?, ?, ?)",
                (game_id, title, time.time()),
            )
            return cur.rowcount == 1

    def mark_pending(self, game_id: int, series_id: int | None, game_number: int | None) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO shameless_pronostics_pending (game_id, series_id, game_number, added_at)"
                " VALUES (?, ?, ?, ?)",
                (game_id, series_id, game_number, time.time()),
            )

    def clear_pending(self, game_id: int) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM shameless_pronostics_pending WHERE game_id = ?", (game_id,))

    def pending(self) -> list[tuple[int, int | None, int | None]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT game_id, series_id, game_number FROM shameless_pronostics_pending ORDER BY game_id"
            ).fetchall()
        return [(game_id, series_id, game_number) for game_id, series_id, game_number in rows]

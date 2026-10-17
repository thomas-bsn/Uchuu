"""Base SQLite partagée par les stores (Shameless, votes).

Connexions courtes (une par opération), sûres entre le thread uvicorn, celui du bot
et `asyncio.to_thread`. Chaque store déclare ses tables dans `SCHEMA`.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path


def connect(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10, isolation_level=None)  # autocommit
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


class SqliteStore:
    """`SCHEMA` exécuté à l'init (ou plus tard via `create_schema()` si `init_schema=False`,
    pour l'appeler hors de la boucle asyncio) ; `_conn()` fermée en sortie de with."""

    SCHEMA: tuple[str, ...] = ()

    def __init__(self, db_path: str, *, init_schema: bool = True) -> None:
        self.db_path = db_path
        if init_schema:
            self.create_schema()

    def create_schema(self) -> None:
        with self._conn() as conn:
            for statement in self.SCHEMA:
                conn.execute(statement)

    def _conn(self):
        return closing(connect(self.db_path))

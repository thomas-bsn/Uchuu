"""Config de l'intégration Shameless (une Instance par déploiement).

Tout vient de l'env (préfixe SHAMELESS_), jamais de discord_config.py : pas d'IDs
communautaires ni de secrets dans le dépôt. Voir .env.example et docs/shameless.md.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


def _int_or_none(name: str) -> int | None:
    raw = os.getenv(name, "").strip()
    return int(raw) if raw else None


@dataclass(frozen=True)
class ShamelessSettings:
    # Secret HMAC des webhooks API -> bot (distinct de bot_api_key)
    webhook_secret: str | None = None
    # SQLite local (dédup des webhooks, présences...) -> volume persistant en Docker
    db_path: str = "data/shameless.sqlite3"
    # Fenêtre max entre X-Shameless-Timestamp et maintenant
    webhook_tolerance_seconds: int = 300
    # Délai max d'exécution d'un handler sur la boucle du bot
    handler_timeout_seconds: float = 30.0

    # Clé des requêtes authentifiées API -> bot (voice candidates)
    bot_api_key: str | None = None
    guild_id: int | None = None
    shared_voice_id: int | None = None
    team1_voice_id: int | None = None
    team2_voice_id: int | None = None
    announce_channel_id: int | None = None
    web_url: str | None = None

    @classmethod
    def from_env(cls) -> "ShamelessSettings":
        load_dotenv()
        return cls(
            webhook_secret=os.getenv("SHAMELESS_WEBHOOK_SECRET") or None,
            db_path=os.getenv("SHAMELESS_DB_PATH", cls.db_path),
            webhook_tolerance_seconds=int(os.getenv("SHAMELESS_WEBHOOK_TOLERANCE_SECONDS", cls.webhook_tolerance_seconds)),
            handler_timeout_seconds=float(os.getenv("SHAMELESS_HANDLER_TIMEOUT_SECONDS", cls.handler_timeout_seconds)),
            bot_api_key=os.getenv("SHAMELESS_BOT_API_KEY") or None,
            guild_id=_int_or_none("SHAMELESS_GUILD_ID"),
            shared_voice_id=_int_or_none("SHAMELESS_SHARED_VOICE_ID"),
            team1_voice_id=_int_or_none("SHAMELESS_TEAM1_VOICE_ID"),
            team2_voice_id=_int_or_none("SHAMELESS_TEAM2_VOICE_ID"),
            announce_channel_id=_int_or_none("SHAMELESS_ANNOUNCE_CHANNEL_ID"),
            web_url=os.getenv("SHAMELESS_WEB_URL") or None,
        )

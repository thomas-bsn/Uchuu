"""Config de l'intégration Shameless (une Instance par déploiement).

Sous-section de `bot_settings.BotSettings` (`settings.shameless`), lue depuis les variables
SHAMELESS_* par `BotSettings.from_env`. Pas d'IDs communautaires ni de secrets dans le dépôt.
Voir .env.example et docs/shameless.md.
"""
from __future__ import annotations

from dataclasses import dataclass


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
    # Durée d'une réservation "processing" : passé ce délai (crash / timeout), un retry
    # la reprend. Doit rester > handler_timeout_seconds.
    claim_lease_seconds: float = 120.0

    # Clé des requêtes authentifiées API -> bot (voice candidates)
    bot_api_key: str | None = None
    # Client HTTP bot -> API (routes /bot) : URL de l'API et clé machine dédiée
    api_url: str | None = None
    bot_to_api_key: str | None = None
    guild_id: int | None = None
    team1_voice_id: int | None = None
    team2_voice_id: int | None = None
    announce_channel_id: int | None = None
    web_url: str | None = None
    # #16 : salon des bulletins de pronostics. Vide -> la fonctionnalité est désactivée.
    pronostics_channel_id: int | None = None
    # Intervalle de re-vérification des résultats de pronostics (MVP/DOFD après clôture
    # des votes). <= 0 : pas de boucle (les events et le démarrage suffisent).
    pronostics_reconcile_seconds: float = 60.0

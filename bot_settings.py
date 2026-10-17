"""Configuration unique du bot : un objet figé construit une fois depuis l'environnement.

`BotSettings.from_env(environ)` lit un simple mapping (os.environ en prod, un dict en test),
signale TOUTES les variables manquantes ou invalides dans une seule `SettingsError`, et ne
lit jamais l'environnement à l'import. L'objet est construit dans main.py puis passé
explicitement aux cogs (via `bot.settings` dans `setup(bot)`) et à `create_internal_api`.
Les textes des messages restent dans le code. Voir .env.example et docs/configuration.md.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from shameless_config import ShamelessSettings


class SettingsError(ValueError):
    """Config invalide : liste toutes les variables manquantes / invalides d'un coup."""

    def __init__(self, missing: list[str], invalid: list[str]):
        self.missing = missing
        self.invalid = invalid
        parts = []
        if missing:
            parts.append("variables manquantes : " + ", ".join(missing))
        if invalid:
            parts.append("variables invalides : " + ", ".join(invalid))
        super().__init__("Configuration invalide — " + " ; ".join(parts))


@dataclass(frozen=True)
class DiscordSettings:
    token: str
    prefix: str = "$$"
    status: str = "Online"


@dataclass(frozen=True)
class CommunityIds:
    """IDs Discord du serveur communautaire (jamais dans le code)."""

    guild_id: int
    role_invite_id: int
    role_membre_id: int
    role_confiance_id: int
    channel_validation_id: int
    channel_logs_id: int
    channel_match_history_id: int


@dataclass(frozen=True)
class InternalApiSettings:
    key: str
    host: str = "127.0.0.1"
    port: int = 9000


@dataclass(frozen=True)
class VoteSettings:
    invite_window_seconds: int = 24 * 3600
    confiance_window_seconds: int = 24 * 3600
    approvals_required: int = 1
    confiance_eligibility_days: int = 30
    confiance_cooldown_days: int = 30
    confiance_scan_interval_hours: int = 24
    # Fichier SQLite dédié, sur le volume persistant (distinct de la base Shameless)
    db_path: str = "/data/votes.sqlite3"


@dataclass(frozen=True)
class BotSettings:
    discord: DiscordSettings
    ids: CommunityIds
    internal_api: InternalApiSettings
    votes: VoteSettings
    shameless: ShamelessSettings

    @classmethod
    def from_env(cls, environ: Mapping[str, str]) -> "BotSettings":
        env = _EnvReader(environ)
        logs_channel = env.required_int("CHANNEL_LOGS_ID")
        settings = cls(
            discord=DiscordSettings(
                token=env.required_str("DISCORD_TOKEN"),
                prefix=env.str("BOT_PREFIX", DiscordSettings.prefix),
                status=env.str("BOT_STATUS", DiscordSettings.status),
            ),
            ids=CommunityIds(
                guild_id=env.required_int("GUILD_ID"),
                role_invite_id=env.required_int("ROLE_INVITE_ID"),
                role_membre_id=env.required_int("ROLE_MEMBRE_ID"),
                role_confiance_id=env.required_int("ROLE_CONFIANCE_ID"),
                channel_validation_id=env.required_int("CHANNEL_VALIDATION_ID"),
                channel_logs_id=logs_channel,
                channel_match_history_id=env.int("CHANNEL_MATCH_HISTORY_ID", logs_channel),
            ),
            internal_api=InternalApiSettings(
                key=env.required_str("INTERNAL_API_KEY"),
                host=env.str("INTERNAL_API_HOST", InternalApiSettings.host),
                port=env.int("INTERNAL_API_PORT", InternalApiSettings.port),
            ),
            votes=VoteSettings(
                invite_window_seconds=env.int("INVITE_VOTE_WINDOW_SECONDS", VoteSettings.invite_window_seconds),
                confiance_window_seconds=env.int("CONFIANCE_VOTE_WINDOW_SECONDS", VoteSettings.confiance_window_seconds),
                approvals_required=env.int("VOTE_APPROVALS_REQUIRED", VoteSettings.approvals_required),
                confiance_eligibility_days=env.int("CONFIANCE_ELIGIBILITY_DAYS", VoteSettings.confiance_eligibility_days),
                confiance_cooldown_days=env.int("CONFIANCE_COOLDOWN_DAYS", VoteSettings.confiance_cooldown_days),
                confiance_scan_interval_hours=env.int(
                    "CONFIANCE_SCAN_INTERVAL_HOURS", VoteSettings.confiance_scan_interval_hours
                ),
                db_path=env.str("VOTES_DB_PATH", VoteSettings.db_path),
            ),
            shameless=ShamelessSettings(
                webhook_secret=env.optional_str("SHAMELESS_WEBHOOK_SECRET"),
                db_path=env.str("SHAMELESS_DB_PATH", ShamelessSettings.db_path),
                webhook_tolerance_seconds=env.int(
                    "SHAMELESS_WEBHOOK_TOLERANCE_SECONDS", ShamelessSettings.webhook_tolerance_seconds
                ),
                handler_timeout_seconds=env.float(
                    "SHAMELESS_HANDLER_TIMEOUT_SECONDS", ShamelessSettings.handler_timeout_seconds
                ),
                claim_lease_seconds=env.float("SHAMELESS_CLAIM_LEASE_SECONDS", ShamelessSettings.claim_lease_seconds),
                bot_api_key=env.optional_str("SHAMELESS_BOT_API_KEY"),
                guild_id=env.optional_int("SHAMELESS_GUILD_ID"),
                team1_voice_id=env.optional_int("SHAMELESS_TEAM1_VOICE_ID"),
                team2_voice_id=env.optional_int("SHAMELESS_TEAM2_VOICE_ID"),
                announce_channel_id=env.optional_int("SHAMELESS_ANNOUNCE_CHANNEL_ID"),
                web_url=env.optional_str("SHAMELESS_WEB_URL"),
            ),
        )
        env.raise_if_errors()
        return settings


class _EnvReader:
    """Lit le mapping en accumulant les erreurs ; une valeur vide compte comme absente."""

    def __init__(self, environ: Mapping[str, str]):
        self._environ = environ
        self._missing: list[str] = []
        self._invalid: list[str] = []

    def _raw(self, name: str) -> str | None:
        value = (self._environ.get(name) or "").strip()
        return value or None

    def required_str(self, name: str) -> str:
        value = self._raw(name)
        if value is None:
            self._missing.append(name)
            return ""
        return value

    def optional_str(self, name: str) -> str | None:
        return self._raw(name)

    def str(self, name: str, default: str) -> str:
        return self._raw(name) or default

    def _convert(self, name: str, kind, default):
        """Valeur convertie, `default` si absente ; une valeur invalide est notée."""
        raw = self._raw(name)
        if raw is None:
            return default
        try:
            return kind(raw)
        except ValueError:
            self._invalid.append(name)
            return default

    def required_int(self, name: str) -> int:
        if self._raw(name) is None:
            self._missing.append(name)
            return 0
        return self._convert(name, int, 0)

    def optional_int(self, name: str) -> int | None:
        return self._convert(name, int, None)

    def int(self, name: str, default: int) -> int:
        return self._convert(name, int, default)

    def float(self, name: str, default: float) -> float:
        return self._convert(name, float, default)

    def raise_if_errors(self) -> None:
        if self._missing or self._invalid:
            raise SettingsError(self._missing, self._invalid)

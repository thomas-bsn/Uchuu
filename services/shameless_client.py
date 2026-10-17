"""Client HTTP du bot vers l'API Shameless (routes `/bot/...`, ADR 0013 de Shameless).

Seul endroit qui connaît `SHAMELESS_API_URL` et `SHAMELESS_BOT_TO_API_KEY` : la clé part en
`Authorization: Bearer` et n'apparaît jamais dans un message d'erreur. Les handlers Discord
reçoivent une `ShamelessApiError` : `is_permanent` dit si un retry peut encore réparer
(payload refusé, votes clos) ou non (panne réseau, 5xx, clé à corriger).

Config absente -> l'appel échoue (`ShamelessApiError` sans statut) : l'event n'est pas
acquitté, Shameless retente une fois la config corrigée.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import httpx

# Statuts qu'un retry peut résoudre : clé à corriger (401), timeout (408), quota (429).
RETRYABLE_STATUSES = frozenset({401, 408, 429})
DEFAULT_TIMEOUT_SECONDS = 10.0


class ShamelessApiError(RuntimeError):
    """Appel à l'API Shameless impossible ou refusé. Ne contient jamais la clé."""

    def __init__(self, message: str, *, status: int | None = None):
        super().__init__(message)
        self.status = status

    @property
    def is_permanent(self) -> bool:
        """Un retry ne réparerait rien : payload refusé (400), votes déjà clos (409),
        Game inconnue (404)... Les pannes réseau et les 5xx restent, elles, à retenter."""
        return (
            self.status is not None
            and 400 <= self.status < 500
            and self.status not in RETRYABLE_STATUSES
        )


class ShamelessApiClient:
    """Routes `/bot/...` de l'API Shameless, partagé par les handlers Discord."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout_seconds,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def put_spectateurs(self, game_id: int, discord_ids: Iterable[str]) -> None:
        """`PUT /bot/games/{id}/spectateurs` : remplace l'ensemble des Spectateurs côté API
        (rejouable sans doublon)."""
        await self._request(
            "PUT",
            f"/bot/games/{game_id}/spectateurs",
            json={"discordIds": sorted(set(discord_ids))},
        )

    async def _request(self, method: str, path: str, *, json: Any = None) -> httpx.Response:
        if not path.startswith("/bot/"):
            # ADR 0013 : la clé machine n'ouvre QUE les routes du bot — jamais ailleurs
            raise ValueError(f"ce client ne parle qu'aux routes /bot : {method} {path}")
        try:
            response = await self._http.request(method, path, json=json)
        except httpx.HTTPError as error:
            raise ShamelessApiError(f"API Shameless injoignable ({method} {path}) : {error}") from error
        if not response.is_success:
            raise ShamelessApiError(
                f"API Shameless a refusé {method} {path} ({response.status_code}) : {_error_detail(response)}",
                status=response.status_code,
            )
        return response


def _error_detail(response: httpx.Response) -> str:
    """`detail` (ou `title`) du ProblemDetails de l'API, sinon un bout de corps brut."""
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        for field in ("detail", "title"):
            if body.get(field):
                return str(body[field])
    return (response.text or "").strip()[:200] or "sans détail"


def client_from_settings(settings) -> ShamelessApiClient:
    """Client configuré par `SHAMELESS_API_URL` + `SHAMELESS_BOT_TO_API_KEY`.

    Config absente -> `ShamelessApiError` (pas de statut) : l'appel échoue, l'event n'est pas
    acquitté, Shameless retente une fois la config corrigée.
    """
    if not settings.api_url or not settings.bot_to_api_key:
        raise ShamelessApiError(
            "SHAMELESS_API_URL et SHAMELESS_BOT_TO_API_KEY sont requis pour appeler l'API Shameless"
        )
    return ShamelessApiClient(settings.api_url, settings.bot_to_api_key)

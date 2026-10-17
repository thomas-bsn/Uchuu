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

    async def get_series_pronostics(self, series_id: int) -> dict[str, Any]:
        """`GET /bot/series/{id}/pronostics` : la Game ouverte (`gameNumber` null si
        verrouillée / Série terminée) et la composition courante."""
        response = await self._request("GET", f"/bot/series/{series_id}/pronostics")
        return response.json()

    async def put_pronostic(
        self,
        series_id: int,
        *,
        discord_id: str,
        nom: str | None,
        game_number: int,
        equipe_gagnante: str | None = None,
        mvp_player_id: int | None = None,
        dofd_player_id: int | None = None,
    ) -> dict[str, Any]:
        """`PUT /bot/series/{id}/pronostics` : remplace le pronostic du Spectateur (les
        trois choix à `null` le retirent). Tous les champs du contrat sont envoyés."""
        response = await self._request(
            "PUT",
            f"/bot/series/{series_id}/pronostics",
            json={
                "pronostiqueurDiscordId": str(discord_id),
                "pronostiqueurNom": nom,
                "gameNumber": game_number,
                "equipeGagnante": equipe_gagnante,
                "mvpPlayerId": mvp_player_id,
                "dofdPlayerId": dofd_player_id,
            },
        )
        return response.json()

    async def get_game_pronostics(self, game_id: int) -> dict[str, Any]:
        """`GET /bot/games/{id}/pronostics` : les pronostics évalués d'une Game (chaque
        `correct` arrive quand son résultat est connu)."""
        response = await self._request("GET", f"/bot/games/{game_id}/pronostics")
        return response.json()

    async def post_clip(
        self,
        *,
        message_id: str,
        attachment_id: str,
        auteur_id: str,
        auteur_nom: str,
        publie_le: str,
        fichier: bytes,
        filename: str,
        content_type: str,
    ) -> dict[str, Any]:
        """`POST /bot/clips` en multipart/form-data (ADR 0014) : la vidéo et les métadonnées
        Discord du message. Idempotent côté API sur `attachmentId` (201 au premier dépôt,
        200 au rejeu, vidéo non réécrite) : un clip peut donc être retransmis sans doublon.

        Renvoie le `ClipDuBot` (`clipId`, `gameId`, `rattachement`) : c'est la confirmation du
        dépôt. Le stockage et le rattachement à une Game restent à l'API (Game unique plausible).
        """
        response = await self._request(
            "POST",
            "/bot/clips",
            data={
                "messageId": message_id,
                "attachmentId": attachment_id,
                "auteurDiscordId": auteur_id,
                "auteurNom": auteur_nom,
                "publieLe": publie_le,
            },
            files={"fichier": (filename, fichier, content_type)},
        )
        try:
            body = response.json()
        except ValueError:
            return {}
        return body if isinstance(body, dict) else {}

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        data: Any = None,
        files: Any = None,
    ) -> httpx.Response:
        if not path.startswith("/bot/"):
            # ADR 0013 : la clé machine n'ouvre QUE les routes du bot — jamais ailleurs
            raise ValueError(f"ce client ne parle qu'aux routes /bot : {method} {path}")
        try:
            response = await self._http.request(method, path, json=json, data=data, files=files)
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

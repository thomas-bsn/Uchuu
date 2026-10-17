"""Dépôt des clips de #clips sur l'API Shameless (ADR 0014 de Shameless).

Le bot télécharge chaque pièce jointe vidéo du salon, puis la dépose sur `POST /bot/clips`
(multipart, `Authorization: Bearer <SHAMELESS_BOT_TO_API_KEY>`). L'API est idempotente sur
`attachmentId` : rejouer un dépôt est sans risque. Rien n'est gardé en local : la vidéo passe
par un fichier temporaire, supprimé après le dépôt.
"""
from __future__ import annotations

import asyncio
import logging
import tempfile
from dataclasses import dataclass
from typing import Any

import httpx

from shameless_config import ShamelessSettings

logger = logging.getLogger(__name__)

VIDEO_TYPES = frozenset({"video/mp4", "video/webm", "video/quicktime"})
ATTEMPTS = 3
RETRY_DELAY_SECONDS = 2.0
# Refus définitifs de l'API : rejouer ne changerait rien (400 requête, 401 clé, 409 conflit, 413 taille)
PERMANENT_REFUSALS = frozenset({400, 401, 409, 413})


def video_content_type(attachment: Any) -> str | None:
    """Type vidéo accepté de la pièce jointe (sans paramètres), None sinon."""
    content_type = (attachment.content_type or "").split(";")[0].strip().lower()
    return content_type if content_type in VIDEO_TYPES else None


@dataclass(frozen=True)
class ClipDeposited:
    clip_id: int
    game_id: int | None
    created: bool


class ClipsDepositor:
    def __init__(self, settings: ShamelessSettings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=10.0))

    @property
    def configured(self) -> bool:
        s = self.settings
        return bool(s.clips_channel_id and s.api_url and s.bot_to_api_key)

    async def close(self) -> None:
        await self._client.aclose()

    async def handle_message(self, message: Any) -> list[ClipDeposited]:
        """Dépose les vidéos du message si c'est un message humain du salon des clips."""
        if not self.configured or message.author.bot or message.channel.id != self.settings.clips_channel_id:
            return []
        deposited = []
        for attachment in message.attachments:
            content_type = video_content_type(attachment)
            if content_type is None:
                continue
            if attachment.size > self.settings.clips_max_bytes:
                logger.warning("Clip %s ignoré : %s octets > %s", attachment.id, attachment.size, self.settings.clips_max_bytes)
                continue
            try:
                clip = await self._deposit(message, attachment, content_type)
                logger.info("Clip %s (message %s) %s : clip %s, game %s", attachment.id, message.id,
                            "déposé" if clip.created else "déjà déposé", clip.clip_id, clip.game_id or "aucune")
                deposited.append(clip)
            except httpx.HTTPError as error:
                logger.error("Dépôt du clip %s (message %s) abandonné : %r", attachment.id, message.id, error)
            except Exception:
                logger.exception("Dépôt du clip %s (message %s) abandonné", attachment.id, message.id)
        return deposited

    async def _deposit(self, message: Any, attachment: Any, content_type: str) -> ClipDeposited:
        with tempfile.TemporaryFile() as video:
            await self._download(attachment.url, video)
            url = f"{self.settings.api_url.rstrip('/')}/bot/clips"
            for attempt in range(1, ATTEMPTS + 1):
                video.seek(0)
                try:
                    return await self._post(message, attachment, content_type, video)
                except httpx.HTTPStatusError as error:
                    logger.warning("Clip %s : l'API répond %s (tentative %s/%s) : %s", attachment.id,
                                   error.response.status_code, attempt, ATTEMPTS, error.response.text[:300])
                    if error.response.status_code in PERMANENT_REFUSALS or attempt == ATTEMPTS:
                        raise
                except httpx.TransportError as error:
                    # coupure avant réponse : souvent une réponse d'erreur (ex. 401) de l'API ou du proxy
                    # arrivée pendant l'envoi du corps, ou une limite de taille / un timeout du proxy
                    logger.warning("Clip %s : %s sans réponse de l'API (%s, tentative %s/%s)", attachment.id,
                                   type(error).__name__, url, attempt, ATTEMPTS)
                    if attempt == ATTEMPTS:
                        raise
                await asyncio.sleep(RETRY_DELAY_SECONDS * attempt)
        raise AssertionError("unreachable")

    async def _download(self, url: str, destination) -> None:
        """Flux vers un fichier temporaire : jamais 500 Mo en mémoire."""
        async with self._client.stream("GET", url) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes():
                destination.write(chunk)

    async def _post(self, message: Any, attachment: Any, content_type: str, video) -> ClipDeposited:
        response = await self._client.post(
            f"{self.settings.api_url.rstrip('/')}/bot/clips",
            headers={"Authorization": f"Bearer {self.settings.bot_to_api_key}"},
            data={
                "messageId": str(message.id),
                "attachmentId": str(attachment.id),
                "auteurDiscordId": str(message.author.id),
                "auteurNom": message.author.display_name,
                "publieLe": message.created_at.isoformat(),
            },
            files={"fichier": (attachment.filename, video, content_type)},
        )
        response.raise_for_status()
        body = response.json()
        return ClipDeposited(body["clipId"], body.get("gameId"), created=response.status_code == 201)

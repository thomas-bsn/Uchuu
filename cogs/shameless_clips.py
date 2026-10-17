"""Cog Shameless « Clips » (#17) : dépôt des vidéos publiées dans `#clips` vers l'API (ADR 0014).

Le bot ne stocke rien : il télécharge la pièce jointe du salon configuré et la transmet
au plus vite en multipart à `POST /bot/clips`, qui garde la vidéo et décide seul du
rattachement à une Game (uniquement si une Game unique est plausible).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from discord.ext import commands

from services.shameless_client import ShamelessApiClient, ShamelessApiError, client_from_settings
from services.shameless_clips import ClipRefused, published_at_iso, video_of
from shameless_config import ShamelessSettings

logger = logging.getLogger(__name__)

# Rejeu du même `attachmentId` sur une panne transitoire : borné, l'API restant idempotente
REPLAY_ATTEMPTS = 3
REPLAY_DELAY_SECONDS = 2.0


def _failure_message(error: ShamelessApiError) -> str:
    """Ce que l'auteur lit dans Discord quand l'API n'a pas pris le clip.

    Un refus définitif (type, taille, payload) ne se répare pas en réessayant. Une panne
    (réseau, 5xx, clé) est, elle, rejouée par le bot avec le **même** `attachmentId` : l'API
    est idempotente dessus, le rejeu ne crée donc pas de doublon. Au-delà des rejeux, l'auteur
    doit réessayer plus tard — republier son message créerait un **nouvel** `attachmentId`,
    que l'API ne saurait pas dédupliquer.
    """
    if error.is_permanent:
        return f"Le transfert du clip a été refusé : {error}"
    return f"Le transfert du clip a échoué après plusieurs tentatives, réessaie plus tard : {error}"


class ShamelessClips(commands.Cog):
    def __init__(
        self,
        bot,
        settings: ShamelessSettings,
        api: ShamelessApiClient | None = None,
        *,
        replay_attempts: int = REPLAY_ATTEMPTS,
        replay_delay_seconds: float = REPLAY_DELAY_SECONDS,
    ):
        self.bot = bot
        self.settings = settings
        # client injecté en test ; sinon construit au premier dépôt depuis la config
        self._api = api
        self._replay_attempts = replay_attempts
        self._replay_delay_seconds = replay_delay_seconds

    async def cog_unload(self):
        if self._api is not None:
            await self._api.aclose()

    @commands.Cog.listener()
    async def on_message(self, message):
        """Chaque vidéo publiée dans `SHAMELESS_CLIPS_CHANNEL_ID` part vers l'API."""
        if self.settings.clips_channel_id is None:
            return  # salon non configuré : dépôt des clips désactivé
        if getattr(message.channel, "id", None) != self.settings.clips_channel_id:
            return
        author = getattr(message, "author", None)
        if author is None or getattr(author, "bot", False):
            return  # jamais ses propres messages (ni ceux d'un autre bot)
        for attachment in message.attachments:
            await self._deposit(message, attachment)

    async def _deposit(self, message, attachment) -> None:
        try:
            video = video_of(
                filename=getattr(attachment, "filename", None),
                content_type=getattr(attachment, "content_type", None),
                size=attachment.size,
                max_bytes=self.settings.clips_max_bytes,
            )
        except ClipRefused as refusal:
            # refus local (type, taille, vidéo vide) : rien à télécharger ni à transmettre
            await message.reply(str(refusal))
            return

        # la pièce jointe est lue une seule fois : les rejeux réutilisent les mêmes octets
        content = await attachment.read()
        try:
            deposited = await self._post_clip_with_replay(message, attachment, video, content)
        except ShamelessApiError as error:
            # listener (pas de retry côté Shameless) : l'auteur est prévenu après les rejeux
            logger.warning("shameless: dépôt du clip %s impossible : %s", attachment.id, error)
            await message.reply(_failure_message(error))
            return

        # 2xx (201, ou 200 au rejeu) = dépôt confirmé : l'API garde la vidéo et décide seule du
        # rattachement (automatique uniquement si une Game unique est plausible, ADR 0014)
        logger.info(
            "shameless: clip %s déposé (clipId=%s, gameId=%s, rattachement=%s)",
            attachment.id,
            deposited.get("clipId"),
            deposited.get("gameId"),
            deposited.get("rattachement"),
        )

    async def _post_clip_with_replay(self, message, attachment, video, content: bytes) -> dict[str, Any]:
        """Dépose le clip, en rejouant le **même** `attachmentId` sur une panne transitoire.

        Le rejeu réutilise les octets déjà lus et les mêmes métadonnées : l'API, idempotente sur
        `attachmentId`, ne crée pas de doublon. Un refus définitif (400/413/409) n'est pas rejoué."""
        error: ShamelessApiError | None = None
        for attempt in range(1, self._replay_attempts + 1):
            try:
                return await self._api_client().post_clip(
                    message_id=str(message.id),
                    attachment_id=str(attachment.id),
                    auteur_id=str(message.author.id),
                    auteur_nom=message.author.display_name,
                    publie_le=published_at_iso(message.created_at),
                    fichier=content,
                    filename=video.filename,
                    content_type=video.content_type,
                )
            except ShamelessApiError as failure:
                if failure.is_permanent:
                    raise  # un refus (type, taille, payload) ne se répare pas en rejouant
                error = failure
                if attempt < self._replay_attempts:
                    logger.warning(
                        "shameless: dépôt du clip %s échoué (tentative %s/%s), rejeu du même attachmentId : %s",
                        attachment.id, attempt, self._replay_attempts, failure,
                    )
                    if self._replay_delay_seconds:
                        await asyncio.sleep(self._replay_delay_seconds)
        assert error is not None  # la boucle ne sort que via un retour ou une exception
        raise error

    def _api_client(self) -> ShamelessApiClient:
        # config absente -> ShamelessApiError : dit à l'auteur, ne casse pas le listener
        if self._api is None:
            self._api = client_from_settings(self.settings)
        return self._api


async def setup(bot):
    await bot.add_cog(ShamelessClips(bot, bot.settings.shameless))

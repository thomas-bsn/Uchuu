"""#17 Clips : validation des vidéos publiées dans le salon `#clips`.

Pur et sans I/O (comme `shameless_recap`) : le cog télécharge la pièce jointe et la
transmet ; ici on décide seulement ce qui est déposable et sous quelle forme. Types
acceptés et limite sont ceux de l'API (`ClipsOptions.Formats` / `Clips:MaxFileSizeBytes`,
ADR 0014) : on refuse localement ce que l'API refuserait, sans rien télécharger pour rien.
Les messages de refus sont affichés tels quels à l'auteur du clip.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import PurePosixPath

# `Clips:MaxFileSizeBytes` par défaut côté API : 500 Mo (limite de pièce jointe Discord Nitro)
MAX_BYTES_DEFAULT = 500 * 1024 * 1024

# Content-Type accepté par l'API -> extension stockée (`ClipsOptions.Formats`)
ACCEPTED_TYPES = {
    "video/mp4": "mp4",
    "video/webm": "webm",
    "video/quicktime": "mov",
}

# Les mêmes, devinés depuis l'extension quand Discord n'a pas su typer la pièce jointe
CONTENT_TYPE_BY_EXTENSION = {extension: content_type for content_type, extension in ACCEPTED_TYPES.items()}

# Types « je ne sais pas » de Discord : ni précis ni exploitables, l'extension décide alors
GENERIC_TYPES = frozenset({"application/octet-stream", "binary/octet-stream"})


@dataclass(frozen=True)
class ClipVideo:
    """Vidéo déposable : le fichier tel qu'il partira en multipart."""

    filename: str
    content_type: str
    size: int


class ClipRefused(Exception):
    """Pièce jointe non déposable : le message est publié tel quel dans Discord."""


def video_of(
    *,
    filename: str | None,
    content_type: str | None,
    size: int,
    max_bytes: int = MAX_BYTES_DEFAULT,
) -> ClipVideo:
    """La vidéo à déposer, sinon `ClipRefused` (message prêt pour l'auteur).

    Le type vient du `Content-Type` vu par Discord — un type précis fait foi — et à défaut
    (absent ou « octet-stream ») de l'extension du fichier. Le Content-Type transmis est
    celui du contrat de l'API (`ClipsOptions.Formats`), jamais celui de Discord tel quel.
    """
    accepted = _accepted_content_type(content_type)
    if accepted is None and _is_generic(content_type):
        accepted = CONTENT_TYPE_BY_EXTENSION.get(_extension(filename))
    if accepted is None:
        raise ClipRefused("Ce fichier n'est pas une vidéo : seuls les clips mp4, webm et mov sont transférés.")
    if size > max_bytes:
        raise ClipRefused(f"Un clip ne dépasse pas {max_bytes // (1024 * 1024)} Mo.")
    if size < 1:
        raise ClipRefused("La vidéo du clip est vide.")
    return ClipVideo(filename=filename or f"clip.{ACCEPTED_TYPES[accepted]}", content_type=accepted, size=size)


def _accepted_content_type(raw: str | None) -> str | None:
    """Content-Type normalisé (`video/mp4; charset=…` -> `video/mp4`) s'il est accepté."""
    if not raw:
        return None
    content_type = raw.split(";", 1)[0].strip().lower()
    return content_type if content_type in ACCEPTED_TYPES else None


def _is_generic(raw: str | None) -> bool:
    """Absent ou « octet-stream » : Discord n'a rien su dire du contenu."""
    return not raw or raw.split(";", 1)[0].strip().lower() in GENERIC_TYPES


def _extension(filename: str | None) -> str:
    return PurePosixPath(filename or "").suffix.lstrip(".").lower()


def published_at_iso(created_at: datetime) -> str:
    """`publieLe` : l'heure de publication du message, ISO 8601 UTC (`...Z`)."""
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return created_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

"""Événements webhook Shameless : enveloppe, signature, dispatcher type -> handler.

Seam pour les handlers Discord (#4 teams_formed, #5 game_started / game_completed) :

    from services.shameless_events import get_dispatcher

    async def on_teams_formed(event: ShamelessEvent) -> None: ...
    get_dispatcher(bot).register("teams_formed", on_teams_formed)

Les handlers tournent sur bot.runtime_loop (là où discord.py vit), pas sur la boucle uvicorn.
Dédup SQLite par event_id (cf. shameless_store) : jamais rejoués une fois réussis, mais
ré-exécutés après échec, timeout ou crash -> un handler doit être idempotent.
"""
from __future__ import annotations

import hashlib
import hmac
import threading
import time
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, Field

SUPPORTED_VERSIONS = {1}

EVENT_TEAMS_FORMED = "teams_formed"
EVENT_GAME_STARTED = "game_started"
EVENT_GAME_COMPLETED = "game_completed"


class ShamelessEvent(BaseModel):
    """Enveloppe versionnée. `data` = snapshot propre au type d'event."""

    version: int
    event_id: str = Field(min_length=1, max_length=200)
    type: str = Field(min_length=1)
    occurred_at: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


Handler = Callable[[ShamelessEvent], Awaitable[None]]


class ShamelessEventDispatcher:
    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = {}

    def register(self, event_type: str, handler: Handler) -> None:
        # plusieurs cogs peuvent écouter le même type (ex. #15 Votes en plus de #5 Games) ;
        # un reload de cog ré-enregistre le MÊME handler : pas de doublon.
        handlers = self._handlers.setdefault(event_type, [])
        if handler not in handlers:
            handlers.append(handler)

    def unregister(self, event_type: str, handler: Handler | None = None) -> None:
        """Sans `handler`, retire tous les handlers du type (comportement historique)."""
        if handler is None:
            self._handlers.pop(event_type, None)
            return
        remaining = [h for h in self._handlers.get(event_type, []) if h != handler]
        if remaining:
            self._handlers[event_type] = remaining
        else:
            self._handlers.pop(event_type, None)

    def handlers_for(self, event_type: str) -> list[Handler]:
        """Tous les handlers du type, dans l'ordre d'enregistrement."""
        return list(self._handlers.get(event_type, ()))

    def handler_for(self, event_type: str) -> Handler | None:
        handlers = self._handlers.get(event_type)
        return handlers[0] if handlers else None


_dispatcher_lock = threading.Lock()


def get_dispatcher(bot) -> ShamelessEventDispatcher:
    """Dispatcher unique attaché au bot (créé à la demande ; appelé depuis le thread
    du bot ET celui d'uvicorn, d'où le lock)."""
    with _dispatcher_lock:
        dispatcher = getattr(bot, "shameless_dispatcher", None)
        if dispatcher is None:
            dispatcher = ShamelessEventDispatcher()
            bot.shameless_dispatcher = dispatcher
        return dispatcher


def verify_signature(
    *,
    secret: str,
    body: bytes,
    timestamp: str | None,
    signature: str | None,
    tolerance_seconds: int,
    now: float | None = None,
) -> bool:
    """Signature = "sha256=" + hex(HMAC-SHA256(secret, f"{timestamp}.{body}"))."""
    if not timestamp or not signature:
        return False
    try:
        ts = int(timestamp)
    except ValueError:
        return False
    current = time.time() if now is None else now
    if abs(current - ts) > tolerance_seconds:
        return False
    expected = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import ValidationError
import asyncio
import logging

from services.shameless_events import (
    SUPPORTED_VERSIONS,
    ShamelessEvent,
    get_dispatcher,
    verify_signature,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal/shameless", tags=["internal-shameless"])


async def run_on_bot_loop(bot, coro, timeout: float):
    """Exécute la coroutine sur la boucle discord.py (thread du bot) et attend le résultat.
    Réutilisable par les autres routes Shameless qui touchent à Discord."""
    future = asyncio.run_coroutine_threadsafe(coro, bot.runtime_loop)
    return await asyncio.wait_for(asyncio.wrap_future(future), timeout=timeout)


@router.post("/webhook")
async def receive_webhook(
    request: Request,
    x_shameless_timestamp: str | None = Header(default=None),
    x_shameless_signature: str | None = Header(default=None),
):
    settings = request.app.state.shameless_settings
    if not settings.webhook_secret:
        raise HTTPException(status_code=503, detail="webhook not configured")

    # Signature calculée sur le body brut, avant tout parsing
    body = await request.body()
    if not verify_signature(
        secret=settings.webhook_secret,
        body=body,
        timestamp=x_shameless_timestamp,
        signature=x_shameless_signature,
        tolerance_seconds=settings.webhook_tolerance_seconds,
    ):
        raise HTTPException(status_code=401, detail="invalid or expired signature")

    try:
        event = ShamelessEvent.model_validate_json(body)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors(include_url=False, include_context=False))
    if event.version not in SUPPORTED_VERSIONS:
        raise HTTPException(status_code=422, detail=f"unsupported version {event.version}")

    bot = request.app.state.bot
    handler = get_dispatcher(bot).handler_for(event.type)
    if handler is None:
        return {"status": "ignored", "event_id": event.event_id}

    if getattr(bot, "runtime_loop", None) is None:
        raise HTTPException(status_code=503, detail="bot not ready yet")

    # Réservation persistée AVANT d'exécuter / acquitter
    store = request.app.state.shameless_events_store
    if not store.claim(event.event_id, event.type):
        return {"status": "duplicate", "event_id": event.event_id}

    try:
        await run_on_bot_loop(bot, handler(event), settings.handler_timeout_seconds)
    except asyncio.TimeoutError:
        # état Discord inconnu -> on garde la réservation, pas de rejeu
        logger.exception("shameless webhook %s (%s) timed out", event.event_id, event.type)
        raise HTTPException(status_code=504, detail="handler timed out")
    except Exception:
        store.release(event.event_id)
        logger.exception("shameless webhook %s (%s) failed", event.event_id, event.type)
        raise HTTPException(status_code=500, detail="handler failed")

    store.mark_done(event.event_id)
    return {"status": "processed", "event_id": event.event_id}

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import ValidationError
import asyncio
import hmac
import logging

from services.shameless_events import (
    SUPPORTED_VERSIONS,
    ShamelessEvent,
    get_dispatcher,
    verify_signature,
)
from services.shameless_store import DONE, IN_PROGRESS
from services.shameless_voice import pick_voice_candidates

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal/shameless", tags=["internal-shameless"])


async def run_on_bot_loop(bot, coro, timeout: float | None = None):
    """Exécute la coroutine sur la boucle discord.py (thread du bot) et attend le résultat.
    Réutilisable par les autres routes Shameless qui touchent à Discord."""
    future = asyncio.run_coroutine_threadsafe(coro, bot.runtime_loop)
    return await asyncio.wait_for(asyncio.wrap_future(future), timeout=timeout)


def require_bot_ready(request: Request):
    if getattr(request.app.state.bot, "runtime_loop", None) is None:
        raise HTTPException(status_code=503, detail="bot not ready yet")


# =========================
# API -> bot (requêtes authentifiées)
# =========================

def require_shameless_api(request: Request, authorization: str | None = Header(default=None)):
    # Identité machine de l'API Shameless; le navigateur ne voit jamais ce credential
    expected = request.app.state.settings.shameless.bot_api_key
    scheme, _, token = (authorization or "").partition(" ")
    if not expected or scheme != "Bearer" or not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="invalid shameless api key")


@router.get("/voice-candidates", dependencies=[Depends(require_shameless_api), Depends(require_bot_ready)])
async def get_voice_candidates(request: Request):
    bot = request.app.state.bot
    guild_id = request.app.state.settings.shameless.guild_id

    async def _lookup():
        # lecture du cache discord.py sur la loop du bot
        guild = bot.get_guild(guild_id)
        if guild is None:
            return None
        return pick_voice_candidates(guild)

    result = await run_on_bot_loop(bot, _lookup())
    if result is None:
        raise HTTPException(status_code=503, detail="shameless guild unavailable")
    return result


# =========================
# Webhooks signés API -> bot
# =========================

@router.post("/webhook")
async def receive_webhook(
    request: Request,
    x_shameless_timestamp: str | None = Header(default=None),
    x_shameless_signature: str | None = Header(default=None),
):
    settings = request.app.state.settings.shameless
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

    require_bot_ready(request)

    # Réservation persistée AVANT d'exécuter / acquitter. Seul "done" est un doublon :
    # une livraison encore en cours répond 409 pour que Shameless retente plus tard.
    store = request.app.state.shameless_events_store
    claim = await asyncio.to_thread(store.claim, event.event_id, event.type, settings.claim_lease_seconds)
    if claim == DONE:
        return {"status": "duplicate", "event_id": event.event_id}
    if claim == IN_PROGRESS:
        raise HTTPException(status_code=409, detail="in_progress")

    try:
        await run_on_bot_loop(bot, handler(event), settings.handler_timeout_seconds)
    except asyncio.TimeoutError:
        # handler annulé mais état Discord incertain -> la réservation expire après le
        # lease, puis un retry la reprend (effets des handlers idempotents)
        logger.exception("shameless webhook %s (%s) timed out", event.event_id, event.type)
        raise HTTPException(status_code=504, detail="handler timed out")
    except Exception:
        await asyncio.to_thread(store.release, event.event_id)
        logger.exception("shameless webhook %s (%s) failed", event.event_id, event.type)
        raise HTTPException(status_code=500, detail="handler failed")

    await asyncio.to_thread(store.mark_done, event.event_id)
    return {"status": "processed", "event_id": event.event_id}

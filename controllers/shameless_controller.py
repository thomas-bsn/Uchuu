from fastapi import APIRouter, Depends, Header, HTTPException, Request
import asyncio
import hmac

import shameless_config as sc
from services.shameless_voice import pick_voice_candidates

router = APIRouter(prefix="/internal/shameless", tags=["internal-shameless"])


def require_shameless_api(authorization: str | None = Header(default=None)):
    # Identité machine de l'API Shameless; le navigateur ne voit jamais ce credential
    expected = sc.SHAMELESS_BOT_API_KEY
    scheme, _, token = (authorization or "").partition(" ")
    if not expected or scheme != "Bearer" or not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="invalid shameless api key")


@router.get("/voice-candidates", dependencies=[Depends(require_shameless_api)])
async def get_voice_candidates(request: Request):
    bot = request.app.state.bot
    bot_loop = getattr(bot, "runtime_loop", None)
    if bot_loop is None:
        raise HTTPException(status_code=503, detail="bot not ready yet")

    async def _lookup():
        # lecture du cache discord.py sur la loop du bot
        guild = bot.get_guild(sc.SHAMELESS_GUILD_ID)
        if guild is None:
            return None
        return pick_voice_candidates(guild)

    result = await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(_lookup(), bot_loop))
    if result is None:
        raise HTTPException(status_code=503, detail="shameless guild unavailable")
    return result

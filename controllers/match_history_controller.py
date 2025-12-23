from fastapi import APIRouter, Header, HTTPException, Request, UploadFile, File, Form
import asyncio
import io
import discord

import discord_config as dc
import runtime_config as rt

router = APIRouter(prefix="/internal/matches", tags=["internal-matches"])


@router.post("/history-image")
async def post_match_history_image(
    request: Request,
    image: UploadFile = File(...),
    channel_id: int | None = Form(default=1453034456460951552),
    caption: str | None = Form(default=None),
    x_internal_key: str = Header(...),
):
    # Auth interne
    if x_internal_key != rt.INTERNAL_API_KEY:
        raise HTTPException(status_code=401, detail="invalid internal key")

    # Vérif type fichier (basique)
    if image.content_type not in ("image/png", "image/jpeg"):
        raise HTTPException(status_code=400, detail="unsupported image type")

    bot = request.app.state.bot
    bot_loop = getattr(bot, "runtime_loop", None)
    if bot_loop is None:
        raise HTTPException(status_code=503, detail="bot not ready yet")

    target_channel_id = channel_id or dc.CHANNEL_LOGS_ID

    # Lire l’image en mémoire
    image_bytes = await image.read()
    filename = image.filename or "scoreboard.png"

    async def _send():
        channel = bot.get_channel(target_channel_id) or await bot.fetch_channel(target_channel_id)

        file = discord.File(
            fp=io.BytesIO(image_bytes),
            filename=filename
        )

        # Caption optionnelle (texte au-dessus de l’image)
        content = caption if caption else None

        await channel.send(content=content, file=file)

    asyncio.run_coroutine_threadsafe(_send(), bot_loop)
    return {"status": "accepted"}

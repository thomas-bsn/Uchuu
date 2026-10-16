"""Harness partagé Shameless : env de test, fake bot, SQLite temporaire, client HTTP
monté via create_internal_api(bot), envoi de webhooks signés."""
import asyncio
import os
import threading

# Env AVANT tout import du code du bot (runtime_config raise sans DISCORD_TOKEN)
os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("SHAMELESS_GUILD_ID", "1000")
os.environ.setdefault("SHAMELESS_BOT_API_KEY", "test-bot-api-key")

import httpx  # noqa: E402
import pytest  # noqa: E402

from internal_api import create_internal_api  # noqa: E402
from shameless_config import ShamelessSettings  # noqa: E402
from tests.fakes import WEBHOOK_PATH, WEBHOOK_SECRET, FakeBot, encode_event, sign_webhook  # noqa: E402

SHAMELESS_GUILD_ID = int(os.environ["SHAMELESS_GUILD_ID"])
SHAMELESS_BOT_API_KEY = os.environ["SHAMELESS_BOT_API_KEY"]


@pytest.fixture
def shameless_db_path(tmp_path):
    return tmp_path / "shameless.sqlite3"


@pytest.fixture
def shameless_settings(shameless_db_path):
    """Settings de test (SQLite temporaire). Variante : dataclasses.replace(shameless_settings, ...)."""
    return ShamelessSettings(
        webhook_secret=WEBHOOK_SECRET,
        db_path=str(shameless_db_path),
        guild_id=SHAMELESS_GUILD_ID,
        bot_api_key=SHAMELESS_BOT_API_KEY,
        shared_voice_id=2000,
        team1_voice_id=2001,
        team2_voice_id=2002,
        announce_channel_id=3000,
        web_url="https://shameless.example",
    )


@pytest.fixture
def fake_bot():
    """Bot par défaut de make_client() ; runtime_loop = boucle du test si non fournie."""
    return FakeBot()


@pytest.fixture
def bot_loop():
    """Boucle "discord.py" dans un thread séparé, comme en prod (uvicorn et le bot
    ne partagent pas de boucle). FakeBot(runtime_loop=bot_loop) pour l'utiliser."""
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    yield loop
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=5)
    loop.close()


@pytest.fixture
async def make_client(fake_bot, shameless_settings):
    """await make_client(bot=None, settings=None) -> httpx.AsyncClient sur create_internal_api(bot).

    Rappeler make_client() = "redémarrage" : nouvelle app, même SQLite. Les handlers
    vivent sur le bot (ré-enregistrés par les cogs au boot) -> passer un FakeBot neuf.
    """
    clients = []

    async def _make(bot=None, settings=None):
        bot = bot or fake_bot
        if bot.runtime_loop is None:
            bot.runtime_loop = asyncio.get_running_loop()
        app = create_internal_api(bot, shameless_settings=settings or shameless_settings)
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://bot")
        clients.append(client)
        return client

    yield _make
    for client in clients:
        await client.aclose()


@pytest.fixture
async def client(make_client):
    return await make_client()


@pytest.fixture
def post_event():
    """await post_event(client, event, secret=..., timestamp=...) -> Response, signée par défaut."""

    async def _post(client, event, *, secret=WEBHOOK_SECRET, timestamp=None, headers=None):
        body = encode_event(event)
        signed = sign_webhook(body, secret, timestamp=timestamp)
        signed.update(headers or {})
        return await client.post(WEBHOOK_PATH, content=body, headers=signed)

    return _post

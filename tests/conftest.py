"""Harness partagé : BotSettings de test (dict d'env, jamais os.environ), fake bot,
SQLite temporaire, client HTTP monté via create_internal_api(bot, settings), webhooks signés."""
import asyncio
import threading
from dataclasses import replace

import httpx
import pytest

from bot_settings import BotSettings
from internal_api import create_internal_api
from tests.fakes import WEBHOOK_PATH, WEBHOOK_SECRET, FakeBot, encode_event, sign_webhook

SHAMELESS_GUILD_ID = 1000
SHAMELESS_BOT_API_KEY = "test-bot-api-key"

TEST_ENV = {
    "DISCORD_TOKEN": "test-token",
    "INTERNAL_API_KEY": "test-internal-key",
    "CHANNEL_MATCH_HISTORY_ID": "22",
    "SHAMELESS_WEBHOOK_SECRET": WEBHOOK_SECRET,
    "SHAMELESS_GUILD_ID": str(SHAMELESS_GUILD_ID),
    "SHAMELESS_BOT_API_KEY": SHAMELESS_BOT_API_KEY,
    "SHAMELESS_TEAM1_VOICE_ID": "2001",
    "SHAMELESS_TEAM2_VOICE_ID": "2002",
    "SHAMELESS_ANNOUNCE_CHANNEL_ID": "3000",
    "SHAMELESS_WEB_URL": "https://shameless.example",
}


@pytest.fixture
def shameless_db_path(tmp_path):
    return tmp_path / "shameless.sqlite3"


@pytest.fixture
def bot_settings(tmp_path, shameless_db_path):
    """Config complète de test, construite comme en prod par from_env (SQLite temporaires)."""
    return BotSettings.from_env({
        **TEST_ENV,
        "SHAMELESS_DB_PATH": str(shameless_db_path),
    })


@pytest.fixture
def shameless_settings(bot_settings):
    """Sous-section Shameless. Variante : dataclasses.replace(shameless_settings, ...)."""
    return bot_settings.shameless


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
async def make_client(fake_bot, bot_settings):
    """await make_client(bot=None, settings=None) -> httpx.AsyncClient sur create_internal_api(bot, settings).

    `settings` = variante de la sous-section Shameless, injectée dans bot_settings.

    Rappeler make_client() = "redémarrage" : nouvelle app, même SQLite. Les handlers
    vivent sur le bot (ré-enregistrés par les cogs au boot) -> passer un FakeBot neuf.
    """
    clients = []

    async def _make(bot=None, settings=None):
        bot = bot or fake_bot
        if bot.runtime_loop is None:
            bot.runtime_loop = asyncio.get_running_loop()
        app = create_internal_api(bot, replace(bot_settings, shameless=settings) if settings else bot_settings)
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

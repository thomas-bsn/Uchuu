"""Harness partagé : BotSettings de test (dict d'env, jamais os.environ), fake bot,
SQLite temporaire, faux serveur vocal (cog Shameless Games), fausse API Shameless,
client HTTP monté via create_internal_api(bot, settings), webhooks signés."""
import asyncio
import threading
from dataclasses import replace

import httpx
import pytest

from bot_settings import BotSettings
from internal_api import create_internal_api
from tests.fakes import (
    ANNOUNCE,
    FOREIGN_VOICE,
    GUILD_ID,
    OTHER_GUILD_ID,
    OTHER_VOICE,
    SHARED,
    TEAM1,
    TEAM2,
    VOTE,
    WEBHOOK_PATH,
    WEBHOOK_SECRET,
    FakeBot,
    FakeShamelessApi,
    encode_event,
    sign_webhook,
)

SHAMELESS_GUILD_ID = GUILD_ID  # le serveur des fixtures Shameless Games (fakes.py)
SHAMELESS_BOT_API_KEY = "test-bot-api-key"

TEST_ENV = {
    "DISCORD_TOKEN": "test-token",
    "INTERNAL_API_KEY": "test-internal-key",
    "CHANNEL_MATCH_HISTORY_ID": "22",
    "SHAMELESS_WEBHOOK_SECRET": WEBHOOK_SECRET,
    "SHAMELESS_GUILD_ID": str(SHAMELESS_GUILD_ID),
    "SHAMELESS_BOT_API_KEY": SHAMELESS_BOT_API_KEY,
    "SHAMELESS_TEAM1_VOICE_ID": str(TEAM1),
    "SHAMELESS_TEAM2_VOICE_ID": str(TEAM2),
    "SHAMELESS_ANNOUNCE_CHANNEL_ID": str(ANNOUNCE),
    "SHAMELESS_VOTE_CHANNEL_ID": str(VOTE),
    "SHAMELESS_WEB_URL": "https://shameless.example",
    "SHAMELESS_API_URL": "https://api.shameless.example",
    "SHAMELESS_BOT_TO_API_KEY": "test-bot-to-api-key",
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
def fake_api():
    """Fausse API Shameless (routes /bot) : les handlers y poussent leurs appels."""
    return FakeShamelessApi()


@pytest.fixture
def guild(fake_bot):
    """Serveur Shameless avec ses vocaux (dont un non configuré), son salon d'annonce
    et son salon de bulletins de vote."""
    guild = fake_bot.add_guild(GUILD_ID)
    for channel_id in (SHARED, TEAM1, TEAM2, OTHER_VOICE):
        guild.add_voice_channel(channel_id)
    guild.add_text_channel(ANNOUNCE)
    guild.add_text_channel(VOTE)
    return guild


@pytest.fixture
def other_guild(fake_bot):
    """Un autre serveur où le bot est aussi présent : ses vocaux ne comptent pas."""
    guild = fake_bot.add_guild(OTHER_GUILD_ID)
    guild.add_voice_channel(FOREIGN_VOICE)
    return guild


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

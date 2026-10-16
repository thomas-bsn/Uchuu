import asyncio
import os

# Env AVANT tout import du code du bot (runtime_config raise sans DISCORD_TOKEN)
os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("SHAMELESS_GUILD_ID", "1000")
os.environ.setdefault("SHAMELESS_BOT_API_KEY", "test-bot-api-key")

import httpx
import pytest

from internal_api import create_internal_api

SHAMELESS_GUILD_ID = int(os.environ["SHAMELESS_GUILD_ID"])
SHAMELESS_BOT_API_KEY = os.environ["SHAMELESS_BOT_API_KEY"]


@pytest.fixture
async def make_client():
    """Construit un client HTTP sur create_internal_api(bot) pour un faux bot."""
    clients = []

    async def _make(bot):
        if bot.runtime_loop is None:
            bot.runtime_loop = asyncio.get_running_loop()
        app = create_internal_api(bot)
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://bot")
        clients.append(client)
        return client

    yield _make
    for client in clients:
        await client.aclose()

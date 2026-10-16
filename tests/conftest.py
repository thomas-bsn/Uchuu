"""Harness partagé : env de test, boucle "Discord" en thread, fake bot, SQLite temporaire,
client FastAPI monté via create_internal_api(bot) et envoi de webhooks signés."""
import asyncio
import os
import sys
import threading
from pathlib import Path

import pytest

# runtime_config lève à l'import sans DISCORD_TOKEN -> env AVANT tout import du code du bot
os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("INTERNAL_API_KEY", "test-internal-key")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from internal_api import create_internal_api  # noqa: E402
from shameless_config import ShamelessSettings  # noqa: E402
from tests.fakes import WEBHOOK_PATH, WEBHOOK_SECRET, FakeBot, encode_event, sign_webhook  # noqa: E402


@pytest.fixture
def bot_loop():
    """Vraie boucle asyncio dans un thread, comme bot.runtime_loop en prod
    (l'API tourne dans un autre thread que le bot)."""
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    yield loop
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=5)
    loop.close()


@pytest.fixture
def fake_bot(bot_loop):
    return FakeBot(runtime_loop=bot_loop)


@pytest.fixture
def shameless_db_path(tmp_path):
    return tmp_path / "shameless.sqlite3"


@pytest.fixture
def shameless_settings(shameless_db_path):
    """Settings de test. Étendre via dataclasses.replace(shameless_settings, ...) dans les tests."""
    return ShamelessSettings(
        webhook_secret=WEBHOOK_SECRET,
        db_path=str(shameless_db_path),
        guild_id=1000,
        bot_api_key="test-bot-api-key",
        shared_voice_id=2000,
        team1_voice_id=2001,
        team2_voice_id=2002,
        announce_channel_id=3000,
        web_url="https://shameless.example",
    )


@pytest.fixture
def make_client(fake_bot, shameless_settings):
    """Fabrique d'app : rappeler make_client() = "redémarrage" (nouvelle app, même SQLite).
    Les handlers enregistrés sur le bot ne survivent pas au redémarrage (comme en prod,
    les cogs se ré-enregistrent) -> passer `bot=` pour en simuler un neuf."""
    clients = []

    def _make(bot=None, settings=None):
        app = create_internal_api(bot or fake_bot, shameless_settings=settings or shameless_settings)
        client = TestClient(app)
        clients.append(client)
        return client

    yield _make
    for client in clients:
        client.close()


@pytest.fixture
def client(make_client):
    return make_client()


@pytest.fixture
def post_event():
    """post_event(client, event, secret=..., timestamp=...) -> Response, signée par défaut."""

    def _post(client, event, *, secret=WEBHOOK_SECRET, timestamp=None, headers=None):
        body = encode_event(event)
        signed = sign_webhook(body, secret, timestamp=timestamp)
        signed.update(headers or {})
        return client.post(WEBHOOK_PATH, content=body, headers=signed)

    return _post

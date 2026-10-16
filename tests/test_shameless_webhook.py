"""Transport webhook Shameless (#2) : signature, enveloppe, déduplication SQLite."""
import threading
import time
from dataclasses import replace

from services.shameless_events import get_dispatcher
from tests.fakes import WEBHOOK_PATH, WEBHOOK_SECRET, FakeBot, encode_event, make_event, sign_webhook


def record_calls(bot, event_type):
    """Enregistre un handler qui note les events reçus + le thread d'exécution."""
    calls = []

    async def handler(event):
        calls.append((event, threading.current_thread()))

    get_dispatcher(bot).register(event_type, handler)
    return calls


def test_valid_signed_event_runs_its_handler_on_the_bot_loop(fake_bot, client, post_event):
    calls = record_calls(fake_bot, "teams_formed")
    event = make_event("teams_formed", {"series_id": "s-1"})

    response = post_event(client, event)

    assert response.status_code == 200
    assert response.json() == {"status": "processed", "event_id": event["event_id"]}
    assert len(calls) == 1
    received, thread = calls[0]
    assert received.event_id == event["event_id"]
    assert received.type == "teams_formed"
    assert received.data == {"series_id": "s-1"}
    assert thread is not threading.main_thread()


def test_event_signed_with_wrong_secret_is_rejected_without_running_handler(fake_bot, client, post_event):
    calls = record_calls(fake_bot, "teams_formed")

    response = post_event(client, make_event("teams_formed"), secret="not-the-secret")

    assert response.status_code == 401
    assert calls == []


def test_expired_signature_is_rejected(fake_bot, client, post_event):
    calls = record_calls(fake_bot, "teams_formed")
    ten_minutes_ago = int(time.time()) - 600

    response = post_event(client, make_event("teams_formed"), timestamp=ten_minutes_ago)

    assert response.status_code == 401
    assert calls == []


def test_tampered_body_is_rejected(fake_bot, client):
    calls = record_calls(fake_bot, "teams_formed")
    body = encode_event(make_event("teams_formed", {"series_id": "s-1"}))
    headers = sign_webhook(body, WEBHOOK_SECRET)

    response = client.post(WEBHOOK_PATH, content=body.replace(b"s-1", b"s-2"), headers=headers)

    assert response.status_code == 401
    assert calls == []


def test_unsigned_request_is_rejected(client):
    response = client.post(WEBHOOK_PATH, json=make_event("teams_formed"))

    assert response.status_code == 401


def test_redelivered_event_is_acknowledged_without_rerunning_handler(fake_bot, client, post_event):
    calls = record_calls(fake_bot, "teams_formed")
    event = make_event("teams_formed")

    first = post_event(client, event)
    second = post_event(client, event)

    assert first.json()["status"] == "processed"
    assert second.status_code == 200
    assert second.json() == {"status": "duplicate", "event_id": event["event_id"]}
    assert len(calls) == 1


def test_redelivered_event_after_restart_is_not_replayed(bot_loop, make_client, post_event):
    event = make_event("game_completed", {"game_id": "g-1"})
    bot_before = FakeBot(runtime_loop=bot_loop)
    calls_before = record_calls(bot_before, "game_completed")
    post_event(make_client(bot=bot_before), event)

    # redémarrage : nouveau bot (cogs ré-enregistrés), nouvelle app, même SQLite
    bot_after = FakeBot(runtime_loop=bot_loop)
    calls_after = record_calls(bot_after, "game_completed")
    response = post_event(make_client(bot=bot_after), event)

    assert response.json()["status"] == "duplicate"
    assert len(calls_before) == 1
    assert calls_after == []


def test_distinct_events_are_each_processed(fake_bot, client, post_event):
    calls = record_calls(fake_bot, "game_completed")

    post_event(client, make_event("game_completed", {"game_id": "g-1"}))
    post_event(client, make_event("game_completed", {"game_id": "g-2"}))

    assert [event.data["game_id"] for event, _ in calls] == ["g-1", "g-2"]


def test_failed_handler_returns_error_so_shameless_can_retry(fake_bot, client, post_event):
    attempts = []

    async def flaky(event):
        attempts.append(event.event_id)
        if len(attempts) == 1:
            raise RuntimeError("discord down")

    get_dispatcher(fake_bot).register("game_started", flaky)
    event = make_event("game_started")

    first = post_event(client, event)
    retry = post_event(client, event)

    assert first.status_code == 500
    assert retry.json()["status"] == "processed"
    assert len(attempts) == 2


def test_event_without_handler_is_acknowledged_as_ignored(client, post_event):
    event = make_event("something_new")

    response = post_event(client, event)

    assert response.status_code == 200
    assert response.json() == {"status": "ignored", "event_id": event["event_id"]}


def test_envelope_without_event_id_is_rejected(fake_bot, client, post_event):
    calls = record_calls(fake_bot, "teams_formed")
    event = make_event("teams_formed")
    del event["event_id"]

    response = post_event(client, event)

    assert response.status_code == 422
    assert calls == []


def test_unsupported_envelope_version_is_rejected(fake_bot, client, post_event):
    calls = record_calls(fake_bot, "teams_formed")

    response = post_event(client, make_event("teams_formed", version=99))

    assert response.status_code == 422
    assert calls == []


def test_webhook_is_unavailable_when_no_secret_is_configured(make_client, shameless_settings, post_event):
    client = make_client(settings=replace(shameless_settings, webhook_secret=None))

    response = post_event(client, make_event("teams_formed"))

    assert response.status_code == 503

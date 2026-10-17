"""Dépôt des clips de #clips sur l'API Shameless (ADR 0014) : ce que l'API reçoit, pas le code."""
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone

import httpx
import pytest

import services.shameless_clips as clips_module
from services.shameless_clips import ClipsDepositor

CLIPS_CHANNEL_ID = 4000
VIDEO = b"\x00\x00\x00 ftypmp42-video-bytes"


@dataclass
class FakeAttachment:
    id: int = 7001
    filename: str = "ace.mp4"
    content_type: str | None = "video/mp4"
    size: int = len(VIDEO)
    url: str = "https://cdn.discord.test/ace.mp4"


@dataclass
class FakeAuthor:
    id: int = 555
    display_name: str = "Zoé"
    bot: bool = False


@dataclass
class FakeChannel:
    id: int = CLIPS_CHANNEL_ID


@dataclass
class FakeMessage:
    id: int = 9001
    author: FakeAuthor = field(default_factory=FakeAuthor)
    channel: FakeChannel = field(default_factory=FakeChannel)
    attachments: list = field(default_factory=lambda: [FakeAttachment()])
    created_at: datetime = datetime(2026, 10, 17, 21, 30, tzinfo=timezone.utc)


class FakeApi:
    """Discord CDN + API Shameless derrière un MockTransport ; garde les dépôts reçus."""

    def __init__(self, *statuses: int):
        self.statuses = list(statuses) or [201]
        self.posts: list[httpx.Request] = []
        self.downloads: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            self.downloads.append(str(request.url))
            return httpx.Response(200, content=VIDEO)
        self.posts.append(request)
        status = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
        if status >= 400:
            return httpx.Response(status, json={"detail": "refus"})
        return httpx.Response(status, json={"clipId": 12, "gameId": 3, "rattachement": "automatique"})


@pytest.fixture(autouse=True)
def no_retry_delay(monkeypatch):
    monkeypatch.setattr(clips_module, "RETRY_DELAY_SECONDS", 0)


@pytest.fixture
def clips_settings(shameless_settings):
    return replace(
        shameless_settings,
        api_url="https://shameless.example/api/",
        bot_to_api_key="bot-to-api",
        clips_channel_id=CLIPS_CHANNEL_ID,
    )


def depositor(settings, api: FakeApi) -> ClipsDepositor:
    return ClipsDepositor(settings, httpx.AsyncClient(transport=httpx.MockTransport(api)))


async def test_a_video_in_the_clips_channel_is_deposited_with_its_metadata(clips_settings):
    api = FakeApi(201)

    result = await depositor(clips_settings, api).handle_message(FakeMessage())

    assert [(c.clip_id, c.game_id, c.created) for c in result] == [(12, 3, True)]
    (post,) = api.posts
    assert str(post.url) == "https://shameless.example/api/bot/clips"
    assert post.headers["authorization"] == "Bearer bot-to-api"
    body = post.content
    assert VIDEO in body
    for expected in (b'name="messageId"\r\n\r\n9001', b'name="attachmentId"\r\n\r\n7001',
                     b'name="auteurDiscordId"\r\n\r\n555', "Zoé".encode(),
                     b"2026-10-17T21:30:00+00:00", b"Content-Type: video/mp4"):
        assert expected in body


async def test_an_already_deposited_clip_is_reported_as_not_created(clips_settings):
    result = await depositor(clips_settings, FakeApi(200)).handle_message(FakeMessage())

    assert [c.created for c in result] == [False]


@pytest.mark.parametrize("message", [
    FakeMessage(channel=FakeChannel(id=1)),
    FakeMessage(author=FakeAuthor(bot=True)),
    FakeMessage(attachments=[FakeAttachment(content_type="image/png", filename="a.png")]),
    FakeMessage(attachments=[FakeAttachment(content_type=None)]),
    FakeMessage(attachments=[]),
], ids=["other-channel", "bot-author", "image", "unknown-type", "no-attachment"])
async def test_nothing_is_deposited_for_messages_that_are_not_clips(clips_settings, message):
    api = FakeApi()

    assert await depositor(clips_settings, api).handle_message(message) == []
    assert api.downloads == [] and api.posts == []


@pytest.mark.parametrize("missing", ["api_url", "bot_to_api_key", "clips_channel_id"])
async def test_without_complete_config_nothing_is_deposited(clips_settings, missing):
    api = FakeApi()

    assert await depositor(replace(clips_settings, **{missing: None}), api).handle_message(FakeMessage()) == []
    assert api.posts == []


async def test_a_video_over_the_size_limit_is_not_even_downloaded(clips_settings):
    api = FakeApi()
    settings = replace(clips_settings, clips_max_bytes=10)

    assert await depositor(settings, api).handle_message(FakeMessage()) == []
    assert api.downloads == []


async def test_content_type_parameters_are_ignored(clips_settings):
    message = FakeMessage(attachments=[FakeAttachment(content_type="video/webm; codecs=vp9")])

    result = await depositor(clips_settings, FakeApi(201)).handle_message(message)

    assert len(result) == 1


async def test_each_video_of_a_message_is_deposited(clips_settings):
    api = FakeApi(201)
    message = FakeMessage(attachments=[FakeAttachment(id=1), FakeAttachment(id=2)])

    await depositor(clips_settings, api).handle_message(message)

    assert len(api.posts) == 2


async def test_a_server_error_is_retried_with_the_same_video(clips_settings):
    api = FakeApi(503, 201)

    result = await depositor(clips_settings, api).handle_message(FakeMessage())

    assert len(result) == 1
    assert len(api.posts) == 2 and all(VIDEO in p.content for p in api.posts)
    assert len(api.downloads) == 1


async def test_a_permanent_refusal_is_not_retried(clips_settings):
    api = FakeApi(413)

    assert await depositor(clips_settings, api).handle_message(FakeMessage()) == []
    assert len(api.posts) == 1


async def test_a_failing_video_does_not_stop_the_next_one(clips_settings):
    api = FakeApi(400, 201)
    message = FakeMessage(attachments=[FakeAttachment(id=1), FakeAttachment(id=2)])

    result = await depositor(clips_settings, api).handle_message(message)

    assert len(result) == 1


async def test_retries_stop_after_three_attempts(clips_settings):
    api = FakeApi(500)

    assert await depositor(clips_settings, api).handle_message(FakeMessage()) == []
    assert len(api.posts) == 3

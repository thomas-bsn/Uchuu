"""#17 Clips : dépôt des vidéos publiées dans `#clips` vers l'API Shameless (ADR 0014).

Tout se vérifie sans vraie vidéo : pièces jointes Discord factices (quelques octets) et
fausse API Shameless (vraie app FastAPI montée sur un transport httpx).
"""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import logging

import pytest

from bot_settings import BotSettings
from services.shameless_client import ShamelessApiClient, ShamelessApiError
from services.shameless_clips import MAX_BYTES_DEFAULT, ClipRefused, published_at_iso, video_of
from tests.fakes import (
    ANNOUNCE,
    CLIP_FILE,
    CLIP_TIME,
    CLIPS,
    FakeMember,
    clip_attachment,
    clip_message,
    load_clips,
)


def api_client(fake_api):
    return ShamelessApiClient(fake_api.base_url, fake_api.api_key, transport=fake_api.transport)


async def deposit(client, **overrides):
    """Dépôt d'un clip de test, métadonnées réalistes surchargeables."""
    params = {
        "message_id": "9001",
        "attachment_id": "7001",
        "auteur_id": "8001",
        "auteur_nom": "Buster",
        "publie_le": "2026-10-17T20:00:00Z",
        "fichier": CLIP_FILE,
        "filename": "clip.mp4",
        "content_type": "video/mp4",
        **overrides,
    }
    return await client.post_clip(**params)


# =========================
# CLIENT : POST /bot/clips
# =========================

async def test_a_video_is_posted_as_multipart_with_the_message_metadata(fake_api):
    client = api_client(fake_api)

    await client.post_clip(
        message_id="9001",
        attachment_id="7001",
        auteur_id="8001",
        auteur_nom="Buster",
        publie_le="2026-10-17T20:00:00Z",
        fichier=CLIP_FILE,
        filename="clip.mp4",
        content_type="video/mp4",
    )
    await client.aclose()

    call = fake_api.calls[0]
    assert (call.method, call.path) == ("POST", "/bot/clips")
    assert call.authorization == f"Bearer {fake_api.api_key}"
    assert call.payload["messageId"] == "9001"
    assert call.payload["attachmentId"] == "7001"
    assert call.payload["auteurDiscordId"] == "8001"
    assert call.payload["auteurNom"] == "Buster"
    assert call.payload["publieLe"] == "2026-10-17T20:00:00Z"
    assert call.payload["fichier"] == {
        "filename": "clip.mp4",
        "content_type": "video/mp4",
        "content": CLIP_FILE,
    }
    assert fake_api.clips["7001"] == {"clipId": 1, "gameId": None, "rattachement": None}


async def test_the_deposit_response_carries_the_game_the_api_attached(fake_api):
    # ADR 0014 : le bot ne rattache jamais lui-même ; il lit ce que l'API a décidé
    fake_api.clip_game_id = 42
    fake_api.clip_rattachement = "automatique"
    client = api_client(fake_api)

    result = await deposit(client)
    await client.aclose()

    assert result == {"clipId": 1, "gameId": 42, "rattachement": "automatique"}


@pytest.mark.parametrize("status", [400, 413])
async def test_a_clip_refused_by_the_api_is_a_permanent_error_with_a_readable_reason(fake_api, status):
    fake_api.status = status
    fake_api.detail = "Un clip est une vidéo mp4, webm ou mov."
    client = api_client(fake_api)

    with pytest.raises(ShamelessApiError) as error:
        await deposit(client)
    await client.aclose()

    assert error.value.is_permanent and error.value.status == status
    assert "Un clip est une vidéo mp4, webm ou mov." in str(error.value)
    assert fake_api.api_key not in str(error.value)


@pytest.mark.parametrize("status", [401, 429, 500, 503])
async def test_a_clip_deposit_a_retry_can_fix_stays_retryable(fake_api, status):
    fake_api.status = status
    client = api_client(fake_api)

    with pytest.raises(ShamelessApiError) as error:
        await deposit(client)
    await client.aclose()

    assert not error.value.is_permanent
    assert fake_api.api_key not in str(error.value)


async def test_an_unreachable_api_makes_the_clip_deposit_retryable(fake_api):
    client = ShamelessApiClient(fake_api.base_url, fake_api.api_key, transport=fake_api.unreachable_transport())

    with pytest.raises(ShamelessApiError) as error:
        await deposit(client)
    await client.aclose()

    assert not error.value.is_permanent and error.value.status is None
    assert fake_api.api_key not in str(error.value)


# =========================
# VALIDATION (pure) : types, taille, heure de publication
# =========================

def test_the_default_size_limit_is_the_500_mb_of_the_api():
    assert MAX_BYTES_DEFAULT == 500 * 1024 * 1024


@pytest.mark.parametrize(
    ("content_type", "filename"),
    [("video/mp4", "clip.mp4"), ("video/webm", "clip.webm"), ("video/quicktime", "clip.mov")],
)
def test_the_three_video_types_accepted_by_the_api_are_deposited_as_is(content_type, filename):
    video = video_of(filename=filename, content_type=content_type, size=1024)

    assert (video.filename, video.content_type, video.size) == (filename, content_type, 1024)


def test_the_type_is_guessed_from_the_extension_when_discord_does_not_provide_one():
    video = video_of(filename="Baron Nashor.webm", content_type=None, size=2048)

    assert (video.filename, video.content_type) == ("Baron Nashor.webm", "video/webm")


def test_a_generic_content_type_falls_back_to_the_extension():
    # Discord ne type pas toujours une pièce jointe (« octet-stream ») : le nom du fichier
    # tranche, à condition qu'il annonce une vidéo acceptée
    video = video_of(filename="clip.mp4", content_type="application/octet-stream", size=1024)

    assert video.content_type == "video/mp4"


@pytest.mark.parametrize(
    ("filename", "content_type"),
    [
        ("capture.png", "image/png"),
        ("replay.mkv", "video/x-matroska"),
        ("clip", None),
        ("capture.png", "application/octet-stream"),  # extension non vidéo : rien à deviner
        ("clip.mp4", "image/png"),  # un type précis vu par Discord prime sur le nom du fichier
    ],
)
def test_anything_that_is_not_an_accepted_video_is_refused(filename, content_type):
    with pytest.raises(ClipRefused) as refusal:
        video_of(filename=filename, content_type=content_type, size=1024)

    assert str(refusal.value) == "Ce fichier n'est pas une vidéo : seuls les clips mp4, webm et mov sont transférés."


def test_a_video_over_the_limit_is_refused_with_the_api_wording():
    with pytest.raises(ClipRefused) as refusal:
        video_of(filename="clip.mp4", content_type="video/mp4", size=MAX_BYTES_DEFAULT + 1)

    assert str(refusal.value) == "Un clip ne dépasse pas 500 Mo."


def test_the_limit_is_configurable():
    limit = 10 * 1024 * 1024

    with pytest.raises(ClipRefused) as refusal:
        video_of(filename="clip.mp4", content_type="video/mp4", size=limit + 1, max_bytes=limit)

    assert str(refusal.value) == "Un clip ne dépasse pas 10 Mo."
    assert video_of(filename="clip.mp4", content_type="video/mp4", size=limit, max_bytes=limit).size == limit


def test_an_empty_video_is_refused_like_the_api_does():
    with pytest.raises(ClipRefused) as refusal:
        video_of(filename="clip.mp4", content_type="video/mp4", size=0)

    assert str(refusal.value) == "La vidéo du clip est vide."


def test_the_publication_time_is_sent_as_utc_iso8601():
    assert published_at_iso(CLIP_TIME) == "2026-10-17T20:00:00Z"


def test_a_publication_time_with_an_offset_is_converted_to_utc():
    paris_summer = timezone(timedelta(hours=2))

    assert published_at_iso(datetime(2026, 10, 17, 22, 0, tzinfo=paris_summer)) == "2026-10-17T20:00:00Z"


def test_a_naive_publication_time_is_read_as_utc():
    assert published_at_iso(datetime(2026, 10, 17, 20, 0)) == "2026-10-17T20:00:00Z"


# =========================
# COG : le salon #clips configuré
# =========================

@pytest.fixture
def clips_channel(guild):
    return guild.add_text_channel(CLIPS, name="clips")


@pytest.fixture
def settings(shameless_settings):
    return replace(shameless_settings, clips_channel_id=CLIPS)


@pytest.fixture
async def clips(fake_bot, settings, fake_api):
    """Le cog branché sur la fausse API : rien ne sort de la machine."""
    return await load_clips(fake_bot, settings, api=api_client(fake_api))


async def test_a_video_dropped_in_the_clips_channel_is_deposited_to_the_api(clips, clips_channel, fake_api):
    attachment = clip_attachment(7001)

    await clips.on_message(clip_message(clips_channel, attachments=[attachment]))

    call = fake_api.calls[0]
    assert (call.method, call.path) == ("POST", "/bot/clips")
    assert call.payload["messageId"] == "9001"
    assert call.payload["attachmentId"] == "7001"
    assert call.payload["auteurDiscordId"] == "8001"
    assert call.payload["auteurNom"] == "Buster"
    assert call.payload["publieLe"] == "2026-10-17T20:00:00Z"
    assert call.payload["fichier"]["content"] == CLIP_FILE
    assert attachment.reads == 1
    assert clips_channel.sent == []  # dépôt confirmé : rien à signaler dans Discord


async def test_every_attachment_of_the_message_is_deposited(clips, clips_channel, fake_api):
    await clips.on_message(clip_message(clips_channel, attachments=[clip_attachment(7001), clip_attachment(7002)]))

    assert [call.payload["attachmentId"] for call in fake_api.calls] == ["7001", "7002"]
    assert sorted(fake_api.clips) == ["7001", "7002"]


async def test_messages_outside_the_clips_channel_are_ignored(clips, clips_channel, guild, fake_api):
    await clips.on_message(clip_message(guild.get_channel(ANNOUNCE), attachments=[clip_attachment()]))

    assert fake_api.calls == []
    assert clips_channel.sent == []


async def test_nothing_happens_when_the_clips_channel_is_not_configured(fake_bot, shameless_settings, clips_channel, fake_api):
    # salon non configuré = dépôt des clips désactivé (pas une erreur au démarrage)
    clips = await load_clips(fake_bot, shameless_settings, api=api_client(fake_api))

    await clips.on_message(clip_message(clips_channel, attachments=[clip_attachment()]))

    assert fake_api.calls == []


async def test_the_bot_does_not_deposit_its_own_messages(clips, clips_channel, fake_api):
    author = FakeMember(id=1, bot=True, name="Shameless")

    await clips.on_message(clip_message(clips_channel, author=author, attachments=[clip_attachment()]))

    assert fake_api.calls == []


async def test_a_message_without_attachment_does_nothing(clips, clips_channel, fake_api):
    await clips.on_message(clip_message(clips_channel, content="bien joué les reufs"))

    assert fake_api.calls == []
    assert clips_channel.sent == []


@pytest.mark.parametrize(
    ("content_type", "filename"),
    [("video/mp4", "clip.mp4"), ("video/webm", "clip.webm"), ("video/quicktime", "clip.mov")],
)
async def test_the_three_video_types_are_transmitted_with_their_contract_content_type(
    clips, clips_channel, fake_api, content_type, filename
):
    await clips.on_message(clip_message(clips_channel, attachments=[clip_attachment(7001, filename=filename, content_type=content_type)]))

    assert fake_api.calls[0].payload["fichier"]["content_type"] == content_type


async def test_a_non_video_attachment_is_refused_to_its_author_without_any_download(clips, clips_channel, fake_api):
    attachment = clip_attachment(7001, filename="capture.png", content_type="image/png")

    await clips.on_message(clip_message(clips_channel, attachments=[attachment]))

    assert fake_api.calls == []
    assert attachment.reads == 0  # refus avant tout téléchargement
    assert clips_channel.sent == [
        {
            "content": "Ce fichier n'est pas une vidéo : seuls les clips mp4, webm et mov sont transférés.",
            "reply_to": 9001,
        }
    ]


async def test_a_video_over_the_configured_limit_is_refused_without_any_download(
    fake_bot, clips_channel, shameless_settings, fake_api
):
    limit = 10 * 1024 * 1024
    clips = await load_clips(
        fake_bot, replace(shameless_settings, clips_channel_id=CLIPS, clips_max_bytes=limit), api=api_client(fake_api)
    )
    attachment = clip_attachment(7001, size=limit + 1)

    await clips.on_message(clip_message(clips_channel, attachments=[attachment]))

    assert fake_api.calls == []
    assert attachment.reads == 0
    assert clips_channel.sent[0]["content"] == "Un clip ne dépasse pas 10 Mo."


async def test_an_empty_video_is_refused_to_its_author(clips, clips_channel, fake_api):
    attachment = clip_attachment(7001, data=b"")

    await clips.on_message(clip_message(clips_channel, attachments=[attachment]))

    assert fake_api.calls == []
    assert clips_channel.sent[0]["content"] == "La vidéo du clip est vide."


async def test_a_refused_attachment_does_not_prevent_the_others_from_being_deposited(clips, clips_channel, fake_api):
    refused = clip_attachment(7001, filename="capture.png", content_type="image/png")

    await clips.on_message(clip_message(clips_channel, attachments=[refused, clip_attachment(7002)]))

    assert [call.payload["attachmentId"] for call in fake_api.calls] == ["7002"]
    assert clips_channel.sent[0]["reply_to"] == 9001


async def test_a_clip_refused_by_the_api_is_reported_to_its_author(clips, clips_channel, fake_api):
    fake_api.status = 413
    fake_api.detail = "Un clip ne dépasse pas 500 Mo."

    await clips.on_message(clip_message(clips_channel, attachments=[clip_attachment(7001)]))

    message = clips_channel.sent[0]["content"]
    assert clips_channel.sent[0]["reply_to"] == 9001
    assert "413" in message and "Un clip ne dépasse pas 500 Mo." in message
    assert fake_api.clips == {}  # rien de stocké


async def test_a_broken_api_is_reported_to_its_author_and_the_clip_can_be_resent_without_duplicate(
    clips, clips_channel, fake_api
):
    fake_api.status = 503
    message = clip_message(clips_channel, attachments=[clip_attachment(7001)])

    await clips.on_message(message)

    fake_api.status = None  # l'API revient ; l'auteur republie le même clip
    await clips.on_message(message)

    assert "republie-le" in clips_channel.sent[0]["content"]  # la panne est signalée à l'auteur
    assert len(clips_channel.sent) == 1  # et le dépôt réussi ne dit rien de plus
    assert len(fake_api.calls) == 2  # deux tentatives, un seul clip (idempotence sur attachmentId)
    assert list(fake_api.clips) == ["7001"]
    assert fake_api.clip_files["7001"] == CLIP_FILE


async def test_a_missing_api_configuration_is_reported_instead_of_raising(
    fake_bot, clips_channel, shameless_settings, fake_api
):
    settings = replace(shameless_settings, clips_channel_id=CLIPS, api_url=None, bot_to_api_key=None)
    clips = await load_clips(fake_bot, settings, api=None)

    await clips.on_message(clip_message(clips_channel, attachments=[clip_attachment(7001)]))

    assert "SHAMELESS_API_URL" in clips_channel.sent[0]["content"]
    assert fake_api.calls == []


async def test_a_deposit_success_is_traced_without_ever_showing_the_key(clips, clips_channel, fake_api, caplog):
    fake_api.clip_game_id = 42
    fake_api.clip_rattachement = "automatique"

    with caplog.at_level(logging.INFO):
        await clips.on_message(clip_message(clips_channel, attachments=[clip_attachment(7001)]))

    assert "7001" in caplog.text  # le dépôt est vérifiable côté opérateur
    assert fake_api.api_key not in caplog.text
    assert len(fake_api.calls) == 1  # le rattachement à une Game reste à l'API


async def test_the_api_key_is_never_shown_in_discord_nor_in_logs(clips, clips_channel, fake_api, caplog):
    fake_api.status = 400
    fake_api.detail = "Le nom de l'auteur du clip est requis."

    with caplog.at_level(logging.WARNING):
        await clips.on_message(clip_message(clips_channel, attachments=[clip_attachment(7001)]))

    assert fake_api.api_key not in str(clips_channel.sent)
    assert fake_api.api_key not in caplog.text


# =========================
# CONFIG
# =========================

MINIMAL_ENV = {"DISCORD_TOKEN": "tok", "INTERNAL_API_KEY": "key", "CHANNEL_MATCH_HISTORY_ID": "22"}


def test_the_clips_channel_is_optional_so_the_deposit_can_stay_disabled():
    settings = BotSettings.from_env(MINIMAL_ENV)

    assert settings.shameless.clips_channel_id is None


def test_the_clips_channel_and_the_size_limit_come_from_the_environment():
    settings = BotSettings.from_env(
        {**MINIMAL_ENV, "SHAMELESS_CLIPS_CHANNEL_ID": "3001", "SHAMELESS_CLIPS_MAX_BYTES": "1048576"}
    )

    assert settings.shameless.clips_channel_id == 3001
    assert settings.shameless.clips_max_bytes == 1048576


def test_the_size_limit_defaults_to_the_500_mb_of_the_api():
    assert BotSettings.from_env(MINIMAL_ENV).shameless.clips_max_bytes == 500 * 1024 * 1024

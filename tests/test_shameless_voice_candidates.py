from tests.conftest import SHAMELESS_BOT_API_KEY, SHAMELESS_GUILD_ID
from tests.fakes import FakeBot, FakeGuild, FakeMember, FakeVoiceChannel

URL = "/internal/shameless/voice-candidates"
AUTH = {"Authorization": f"Bearer {SHAMELESS_BOT_API_KEY}"}


def humans(*ids):
    return [FakeMember(i) for i in ids]


async def test_returns_ids_from_most_populated_voice_channel(make_client):
    guild = FakeGuild(SHAMELESS_GUILD_ID, [
        FakeVoiceChannel(11, humans(1, 2)),
        FakeVoiceChannel(12, humans(3, 4, 5)),
        FakeVoiceChannel(13, humans(6)),
    ])
    client = await make_client(FakeBot([guild]))

    r = await client.get(URL, headers=AUTH)

    assert r.status_code == 200
    assert r.json() == {"channel_id": "12", "member_ids": ["3", "4", "5"]}


async def test_bot_accounts_neither_counted_nor_returned(make_client):
    guild = FakeGuild(SHAMELESS_GUILD_ID, [
        FakeVoiceChannel(11, humans(1) + [FakeMember(90, bot=True), FakeMember(91, bot=True)]),
        FakeVoiceChannel(12, humans(2, 3) + [FakeMember(92, bot=True)]),
    ])
    client = await make_client(FakeBot([guild]))

    r = await client.get(URL, headers=AUTH)

    assert r.json() == {"channel_id": "12", "member_ids": ["2", "3"]}


async def test_tie_goes_to_lowest_channel_id_whatever_the_order(make_client):
    guild = FakeGuild(SHAMELESS_GUILD_ID, [
        FakeVoiceChannel(30, humans(5, 6)),
        FakeVoiceChannel(20, humans(4, 3)),
        FakeVoiceChannel(40, humans(7, 8)),
    ])
    client = await make_client(FakeBot([guild]))

    r = await client.get(URL, headers=AUTH)

    assert r.json() == {"channel_id": "20", "member_ids": ["3", "4"]}


async def test_no_human_in_voice_returns_empty_candidates(make_client):
    guild = FakeGuild(SHAMELESS_GUILD_ID, [
        FakeVoiceChannel(11, []),
        FakeVoiceChannel(12, [FakeMember(90, bot=True)]),
    ])
    client = await make_client(FakeBot([guild]))

    r = await client.get(URL, headers=AUTH)

    assert r.status_code == 200
    assert r.json() == {"channel_id": None, "member_ids": []}


async def test_only_the_configured_guild_is_inspected(make_client):
    other = FakeGuild(SHAMELESS_GUILD_ID + 1, [FakeVoiceChannel(11, humans(1, 2, 3))])
    mine = FakeGuild(SHAMELESS_GUILD_ID, [FakeVoiceChannel(21, humans(4))])
    client = await make_client(FakeBot([other, mine]))

    r = await client.get(URL, headers=AUTH)

    assert r.json() == {"channel_id": "21", "member_ids": ["4"]}


async def test_configured_guild_not_in_cache_is_503(make_client):
    other = FakeGuild(SHAMELESS_GUILD_ID + 1, [FakeVoiceChannel(11, humans(1))])
    client = await make_client(FakeBot([other]))

    r = await client.get(URL, headers=AUTH)

    assert r.status_code == 503


async def test_rejects_missing_or_wrong_credential(make_client):
    guild = FakeGuild(SHAMELESS_GUILD_ID, [FakeVoiceChannel(11, humans(1))])
    client = await make_client(FakeBot([guild]))

    assert (await client.get(URL)).status_code == 401
    assert (await client.get(URL, headers={"Authorization": "Bearer nope"})).status_code == 401
    assert (await client.get(URL, headers={"Authorization": SHAMELESS_BOT_API_KEY})).status_code == 401

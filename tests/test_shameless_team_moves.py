"""teams_formed (#4) : placer les Joueurs liés et connectés dans les vocaux d'équipe."""
import discord
import pytest

from cogs.shameless_team_moves import ShamelessTeamMovesCog
from services.shameless_team_moves import register_team_moves
from tests.fakes import FakeBot, make_event

SHARED, TEAM1, TEAM2 = 2000, 2001, 2002


@pytest.fixture
async def voice_server(fake_bot, shameless_settings):
    """Serveur vocal configuré : commun + Team 1 + Team 2, handler branché par le cog
    comme au boot du bot."""
    guild = fake_bot.add_guild(shameless_settings.guild_id)
    channels = {cid: guild.add_voice_channel(cid) for cid in (SHARED, TEAM1, TEAM2)}
    await ShamelessTeamMovesCog(fake_bot, shameless_settings).cog_load()
    return guild, channels


def player(discord_id):
    return {"discord_id": None if discord_id is None else str(discord_id)}


def teams_formed(team_a, team_b, **kwargs):
    return make_event(
        "teams_formed",
        {
            "series_id": "s-1",
            "team_a": {"name": "Team A", "players": [player(i) for i in team_a]},
            "team_b": {"name": "Team B", "players": [player(i) for i in team_b]},
        },
        **kwargs,
    )


async def test_linked_connected_players_are_moved_to_their_team_voice(voice_server, client, post_event):
    guild, channels = voice_server
    a1 = guild.add_member(11, voice=channels[SHARED])
    a2 = guild.add_member(12, voice=channels[SHARED])
    b1 = guild.add_member(21, voice=channels[SHARED])

    response = await post_event(client, teams_formed([11, 12], [21]))

    assert response.status_code == 200
    assert response.json()["status"] == "processed"
    assert a1.moves == [TEAM1] and a2.moves == [TEAM1]
    assert b1.moves == [TEAM2]


async def test_only_connected_linked_members_move_spectators_and_unlinked_stay(voice_server, client, post_event):
    guild, channels = voice_server
    linked = guild.add_member(11, voice=channels[SHARED])
    spectator = guild.add_member(99, voice=channels[SHARED])
    offline = guild.add_member(12)  # lié mais pas en vocal

    # 13 : lié mais absent du serveur ; None : Joueur sans lien Discord
    response = await post_event(client, teams_formed([11, 12, None], [13, None]))

    assert response.status_code == 200
    assert linked.moves == [TEAM1]
    assert spectator.moves == [] and spectator.voice.channel is channels[SHARED]
    assert offline.moves == [] and offline.voice is None


async def test_a_member_that_cannot_be_moved_does_not_block_the_others(voice_server, client, post_event):
    guild, channels = voice_server
    stuck = guild.add_member(11, voice=channels[SHARED])
    other = guild.add_member(21, voice=channels[SHARED])

    async def forbidden(channel, *, reason=None):
        raise discord.Forbidden(_DiscordResponse(403), "Missing Permissions")

    stuck.move_to = forbidden

    response = await post_event(client, teams_formed([11], [21]))

    assert response.status_code == 200
    assert other.moves == [TEAM2]


async def test_member_already_in_their_team_voice_is_not_moved_again(voice_server, client, post_event):
    guild, channels = voice_server
    already_there = guild.add_member(11, voice=channels[TEAM1])

    await post_event(client, teams_formed([11], []))

    assert already_there.moves == []


async def test_missing_team_voice_disconnects_nobody_and_asks_for_a_retry(
    fake_bot, shameless_settings, make_client, post_event
):
    guild = fake_bot.add_guild(shameless_settings.guild_id)
    shared = guild.add_voice_channel(SHARED)
    guild.add_voice_channel(TEAM1)  # Team 2 introuvable (supprimé / mauvais ID)
    register_team_moves(fake_bot, shameless_settings)
    a1 = guild.add_member(11, voice=shared)
    b1 = guild.add_member(21, voice=shared)
    event = teams_formed([11], [21])

    response = await post_event(await make_client(), event)

    assert response.status_code == 500
    assert a1.moves == [] and b1.moves == []
    assert b1.voice.channel is shared

    # salon recréé -> le retry de Shameless (même event_id) passe
    guild.add_voice_channel(TEAM2)
    retry = await post_event(await make_client(), event)
    assert retry.json()["status"] == "processed"
    assert a1.moves == [TEAM1] and b1.moves == [TEAM2]


async def test_replayed_teams_formed_does_not_move_members_again(voice_server, client, post_event):
    guild, channels = voice_server
    a1 = guild.add_member(11, voice=channels[SHARED])
    event = teams_formed([11], [])
    await post_event(client, event)
    await a1.move_to(channels[SHARED])  # retour au vocal commun

    replay = await post_event(client, event)

    assert replay.json()["status"] == "duplicate"
    assert a1.voice.channel is channels[SHARED]


async def test_later_game_events_leave_players_where_they_chose_to_be(voice_server, client, post_event):
    guild, channels = voice_server
    a1 = guild.add_member(11, voice=channels[SHARED])
    b1 = guild.add_member(21, voice=channels[SHARED])
    await post_event(client, teams_formed([11], [21]))
    await a1.move_to(channels[SHARED])
    await b1.move_to(channels[SHARED])

    for event_type in ("game_started", "game_completed", "game_started"):
        response = await post_event(client, make_event(event_type, {"series_id": "s-1", "game_number": 2}))
        assert response.status_code == 200

    assert a1.voice.channel is channels[SHARED] and b1.voice.channel is channels[SHARED]


class _DiscordResponse:
    def __init__(self, status):
        self.status = status
        self.reason = "test"

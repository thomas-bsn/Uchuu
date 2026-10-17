"""#5 annonce de Série / récap de Game + présences Spectateurs par Game (US 24).

Tout passe par le webhook signé de create_internal_api(bot) et le listener vocal
du cog ; Discord est remplacé par les fakes.
"""
import asyncio
from dataclasses import replace

import pytest

from cogs.shameless_games import ShamelessGames
from services.shameless_games_store import GameAttendanceStore
from tests.fakes import FakeBot, FakeVoiceState, make_event

GUILD_ID = 1000
SHARED, TEAM1, TEAM2, OTHER_VOICE = 2000, 2001, 2002, 2999  # SHARED : vocal quelconque, non configuré
OTHER_GUILD_ID, FOREIGN_VOICE = 4000, 4001
ANNOUNCE = 3000


def team(name, side, players):
    return {"name": name, "side": side, "players": players}


def player(name, discord_id, **stats):
    return {"name": name, "discord_id": discord_id, **stats}


TEAM_A = team("Les Chauves", "blue", [player(f"A{i}", str(100 + i)) for i in range(1, 6)])
TEAM_B = team("Les Barbus", "red", [player(f"B{i}", str(200 + i)) for i in range(1, 6)])
PARTICIPANTS = [p["discord_id"] for p in TEAM_A["players"] + TEAM_B["players"]]


def game_started(game_id="g-1", game_number=1, series_id="s-1", **extra):
    data = {
        "series_id": series_id,
        "game_id": game_id,
        "game_number": game_number,
        "best_of": 3,
        # même forme de Teams que teams_formed (#4)
        "team_a": TEAM_A,
        "team_b": TEAM_B,
        "participant_discord_ids": PARTICIPANTS,
        **extra,
    }
    return make_event("game_started", data)


def game_completed(game_id="g-1", game_number=1, series_id="s-1", **overrides):
    data = {
        "series_id": series_id,
        "game_id": game_id,
        "game_number": game_number,
        "best_of": 3,
        "winner": "A",
        "series_score": {"A": 1, "B": 0},
        "duration_seconds": 1834,
        "recap_url": f"https://shameless.example/games/{game_id}",
        "team_a": team("Les Chauves", "blue", [
            player("Zed Main", "101", champion="Zed", role="MID", kills=12, deaths=3, assists=7,
                   cs=243, cs_per_min=7.9, kill_participation=0.61, damage=31250, performance_score=88),
        ]),
        "team_b": team("Les Barbus", "red", [
            player("Feeder", "201", champion="Yuumi", role="SUPPORT", kills=0, deaths=11, assists=4,
                   cs=12, cs_per_min=0.4, kill_participation=0.33, damage=4100, performance_score=12),
        ]),
        "participant_discord_ids": PARTICIPANTS,
    }
    data.update(overrides)
    return make_event("game_completed", data)


@pytest.fixture
def guild(fake_bot):
    guild = fake_bot.add_guild(GUILD_ID)
    for channel_id in (SHARED, TEAM1, TEAM2, OTHER_VOICE):
        guild.add_voice_channel(channel_id)
    guild.add_text_channel(ANNOUNCE)
    return guild


async def load_games(bot, settings):
    """Le cog tel que chargé au boot : cog_load enregistre ses handlers sur le dispatcher."""
    cog = ShamelessGames(bot, settings)
    await cog.cog_load()
    return cog


@pytest.fixture
def other_guild(fake_bot):
    """Un autre serveur où le bot est aussi présent : ses vocaux ne comptent pas."""
    guild = fake_bot.add_guild(OTHER_GUILD_ID)
    guild.add_voice_channel(FOREIGN_VOICE)
    return guild


@pytest.fixture
async def games(fake_bot, guild, shameless_settings):
    return await load_games(fake_bot, shameless_settings)


def announce_channel(guild):
    return guild.get_channel(ANNOUNCE)


# =========================
# ANNONCE DE SÉRIE
# =========================

async def test_first_game_start_announces_the_series_once(guild, games, client, post_event):
    event = game_started()

    first = await post_event(client, event)
    retry = await post_event(client, event)

    assert first.json()["status"] == "processed"
    assert retry.json()["status"] == "duplicate"
    sent = announce_channel(guild).sent
    assert len(sent) == 1
    embed = sent[0]["embed"]
    text = embed.title + (embed.description or "") + "".join(f.name + f.value for f in embed.fields)
    assert "Les Chauves" in text and "Les Barbus" in text
    assert "A1" in text and "B5" in text


async def test_later_game_starts_do_not_announce_again(guild, games, client, post_event):
    await post_event(client, game_started("g-1", 1))
    # même Game renvoyée avec un nouvel event_id (republication côté API)
    await post_event(client, game_started("g-1", 1))
    response = await post_event(client, game_started("g-2", 2))

    assert response.json()["status"] == "processed"
    assert len(announce_channel(guild).sent) == 1


async def test_series_first_seen_at_a_later_game_is_still_announced_once(guild, games, client, post_event):
    # game_started de la Game 1 jamais reçu (bot absent, event perdu côté API...)
    response = await post_event(client, game_started("g-2", 2))
    await post_event(client, game_started("g-3", 3))

    assert response.json()["status"] == "processed"
    sent = announce_channel(guild).sent
    assert len(sent) == 1
    assert "Les Chauves" in sent[0]["embed"].title


async def test_missing_announce_channel_config_fails_so_the_event_is_retried(
    guild, fake_bot, make_client, shameless_settings, post_event
):
    unconfigured = replace(shameless_settings, announce_channel_id=None)
    await load_games(fake_bot, unconfigured)
    event = game_completed("g-1")

    failed = await post_event(await make_client(settings=unconfigured), event)

    assert failed.status_code == 500
    assert announce_channel(guild).sent == []

    # config corrigée + redémarrage : le retry de Shameless publie le récap
    rebooted = FakeBot(guilds=[guild])
    await load_games(rebooted, shameless_settings)
    retry = await post_event(await make_client(rebooted), event)

    assert retry.json()["status"] == "processed"
    assert len(announce_channel(guild).sent) == 1


async def test_unreachable_announce_channel_fails_so_the_event_is_retried(
    guild, fake_bot, make_client, shameless_settings, post_event
):
    elsewhere = replace(shameless_settings, announce_channel_id=4242)  # salon supprimé / inaccessible
    await load_games(fake_bot, elsewhere)

    response = await post_event(await make_client(settings=elsewhere), game_started("g-1"))

    assert response.status_code == 500


async def test_series_announcement_survives_restart(guild, games, make_client, post_event, shameless_settings):
    await post_event(await make_client(), game_started("g-1", 1))

    rebooted = FakeBot(guilds=[guild])
    await load_games(rebooted, shameless_settings)
    await post_event(await make_client(rebooted), game_started("g-1", 1))

    assert len(announce_channel(guild).sent) == 1


# =========================
# RÉCAP DE GAME
# =========================

def embed_text(embed):
    parts = [embed.title or "", embed.description or "", embed.url or ""]
    parts += [f.name + "\n" + f.value for f in embed.fields]
    return "\n".join(parts)


async def test_completed_game_posts_one_recap_with_api_stats_and_web_link(guild, games, client, post_event):
    event = game_completed("g-1", series_score={"A": 1, "B": 0})

    await post_event(client, event)
    retry = await post_event(client, event)

    assert retry.json()["status"] == "duplicate"
    sent = announce_channel(guild).sent
    assert len(sent) == 1
    embed = sent[0]["embed"]
    text = embed_text(embed)
    assert embed.url == "https://shameless.example/games/g-1"
    assert "Victoire" in text and "Les Chauves" in text  # vainqueur = Team A
    assert "1 - 0" in text  # score de Série
    # stats #52 telles que fournies par l'API
    assert "Zed Main" in text and "Zed" in text and "MID" in text
    assert "12/3/7" in text
    assert "7.9 CS/min" in text
    assert "KP 61%" in text
    assert "31.2k" in text
    assert "88/100" in text
    assert "Feeder" in text and "0/11/4" in text and "12/100" in text
    # pas de vote MVP/DOFD en Phase 1d
    assert sent[0].get("view") is None
    assert "MVP" not in text and "DOFD" not in text


async def test_every_completed_game_of_a_series_gets_its_own_recap(guild, games, client, post_event):
    await post_event(client, game_completed("g-1", 1, series_score={"A": 1, "B": 0}))
    await post_event(client, game_completed("g-2", 2, winner="B", series_score={"A": 1, "B": 1}))
    # republication de g-2 avec un autre event_id : pas de second récap
    await post_event(client, game_completed("g-2", 2, winner="B", series_score={"A": 1, "B": 1}))

    sent = announce_channel(guild).sent
    assert len(sent) == 2
    assert "1 - 1" in embed_text(sent[1]["embed"])
    assert "Les Barbus" in sent[1]["embed"].title


async def test_recap_without_optional_fields_still_posts_readable_embed(guild, games, client, post_event):
    event = make_event("game_completed", {
        "game_id": "g-9",
        "team_a": {"players": [{"name": "Solo"}]},
        "team_b": {"players": [{"discord_id": "5"}]},
    })

    response = await post_event(client, event)

    assert response.json()["status"] == "processed"
    embed = announce_channel(guild).sent[0]["embed"]
    text = embed_text(embed)
    assert "Solo" in text and "Team B" in text
    assert "None" not in text
    # pas de recap_url -> lien construit depuis SHAMELESS_WEB_URL
    assert embed.url == "https://shameless.example/games/g-9"


async def test_recap_send_failure_lets_shameless_retry(guild, games, client, post_event):
    channel = announce_channel(guild)
    original = channel.send
    calls = 0

    async def flaky_send(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("discord down")
        return await original(*args, **kwargs)

    channel.send = flaky_send
    event = game_completed("g-1")

    assert (await post_event(client, event)).status_code == 500
    assert (await post_event(client, event)).json()["status"] == "processed"
    assert len(channel.sent) == 1


async def test_recap_interrupted_by_timeout_is_posted_exactly_once_on_retry(
    guild, games, make_client, shameless_settings, post_event
):
    channel = announce_channel(guild)
    original = channel.send
    hang = {"first": True}

    async def slow_then_ok(*args, **kwargs):
        if hang.pop("first", False):
            await asyncio.sleep(10)
        return await original(*args, **kwargs)

    channel.send = slow_then_ok
    client = await make_client(settings=replace(shameless_settings, handler_timeout_seconds=0.05, claim_lease_seconds=0.2))
    event = game_completed("g-1")

    assert (await post_event(client, event)).status_code == 504
    await asyncio.sleep(0.25)
    retry = await post_event(client, event)
    again = await post_event(client, event)

    assert retry.json()["status"] == "processed"
    assert again.json()["status"] == "duplicate"
    assert len(channel.sent) == 1


# =========================
# PRÉSENCES VOCALES PAR GAME (Spectateurs, US 24)
# =========================

def spectators(settings, game_id):
    """Interface lue par le futur workflow de vote (Phase 2)."""
    return GameAttendanceStore(settings.db_path).spectators(game_id)


async def join(cog, member, channel):
    """Simule l'event gateway on_voice_state_update."""
    before = FakeVoiceState(member.voice_channel) if member.voice_channel else None
    if member.voice_channel is not None:
        member.voice_channel.members.remove(member)
    member.voice_channel = channel
    if channel is not None:
        channel.members.append(member)
    after = FakeVoiceState(channel) if channel else None
    await cog.on_voice_state_update(member, before, after)


async def test_spectators_in_any_voice_of_the_server_at_game_start_are_recorded(
    guild, other_guild, games, client, post_event, shameless_settings
):
    guild.add_member(101, voice=guild.get_channel(TEAM1))  # Joueur
    guild.add_member(500, voice=guild.get_channel(SHARED))  # Spectateur
    guild.add_member(501, voice=guild.get_channel(TEAM2))  # Spectateur dans un salon Team
    guild.add_member(502, voice=guild.get_channel(OTHER_VOICE))  # vocal quelconque du serveur
    guild.add_member(900, bot=True, voice=guild.get_channel(SHARED))  # bot
    other_guild.add_member(503, voice=other_guild.get_channel(FOREIGN_VOICE))  # autre serveur

    await post_event(client, game_started("g-1"))

    assert spectators(shameless_settings, "g-1") == ["500", "501", "502"]


async def test_voice_joins_are_recorded_only_between_start_and_completion(
    guild, games, client, post_event, shameless_settings
):
    early = guild.add_member(600)
    during = guild.add_member(601)
    late = guild.add_member(602)
    player_member = guild.add_member(201)
    bot_member = guild.add_member(901, bot=True)

    await join(games, early, guild.get_channel(SHARED))
    await join(games, early, None)  # parti avant le début
    await post_event(client, game_started("g-1"))
    await join(games, during, guild.get_channel(SHARED))
    await join(games, during, guild.get_channel(TEAM1))  # change de salon : dédupliqué
    await join(games, player_member, guild.get_channel(TEAM2))
    await join(games, bot_member, guild.get_channel(SHARED))
    await post_event(client, game_completed("g-1"))
    await join(games, late, guild.get_channel(SHARED))

    assert spectators(shameless_settings, "g-1") == ["601"]


async def test_joining_any_voice_of_the_server_counts_but_other_servers_do_not(
    guild, other_guild, games, client, post_event, shameless_settings
):
    anywhere = guild.add_member(610)
    elsewhere = other_guild.add_member(611)

    await post_event(client, game_started("g-1"))
    await join(games, anywhere, guild.get_channel(OTHER_VOICE))
    await join(games, elsewhere, other_guild.get_channel(FOREIGN_VOICE))

    assert spectators(shameless_settings, "g-1") == ["610"]


async def test_each_game_of_a_series_has_its_own_attendance(guild, games, client, post_event, shameless_settings):
    first = guild.add_member(700)
    second = guild.add_member(701)

    await post_event(client, game_started("g-1", 1))
    await join(games, first, guild.get_channel(SHARED))
    await join(games, first, None)
    await post_event(client, game_completed("g-1", 1))
    await post_event(client, game_started("g-2", 2))
    await join(games, second, guild.get_channel(SHARED))
    await post_event(client, game_completed("g-2", 2))

    assert spectators(shameless_settings, "g-1") == ["700"]
    assert spectators(shameless_settings, "g-2") == ["701"]


async def test_attendance_survives_a_restart_during_the_game(guild, games, make_client, post_event, shameless_settings):
    before_restart = guild.add_member(800)
    after_restart = guild.add_member(801)
    player_member = guild.add_member(105)

    await post_event(await make_client(), game_started("g-1"))
    await join(games, before_restart, guild.get_channel(SHARED))

    rebooted = FakeBot(guilds=[guild])
    rebooted_games = await load_games(rebooted, shameless_settings)
    rebooted_client = await make_client(rebooted)
    await join(rebooted_games, after_restart, guild.get_channel(TEAM2))
    await join(rebooted_games, player_member, guild.get_channel(SHARED))  # exclusion persistée
    await post_event(rebooted_client, game_completed("g-1"))
    await join(rebooted_games, guild.add_member(802), guild.get_channel(SHARED))

    assert spectators(shameless_settings, "g-1") == ["800", "801"]


async def test_people_in_voice_when_bot_comes_back_are_recorded_for_the_open_game(
    guild, games, client, post_event, shameless_settings
):
    await post_event(client, game_started("g-1"))
    # arrivé pendant que le bot était déconnecté
    guild.add_member(810, voice=guild.get_channel(OTHER_VOICE))

    rebooted_games = await load_games(FakeBot(guilds=[guild]), shameless_settings)
    await rebooted_games.on_ready()

    assert spectators(shameless_settings, "g-1") == ["810"]

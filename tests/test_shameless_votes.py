"""#15 votes MVP/DOFD depuis Discord.

Piloté depuis la frontière FastAPI du bot (webhook signé) avec de faux salons Discord et la
fausse API Shameless : aucun appel Discord ni réseau réel.
"""
import asyncio
import time
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from cogs.shameless_votes import deadline_of
from services.shameless_client import ShamelessApiClient, ShamelessApiError
from services.shameless_vote_view import (
    BulletinDeVote,
    dofd_custom_id,
    mvp_custom_id,
    submit_custom_id,
)
from shameless_config import ShamelessSettings
from tests.fakes import (
    ANNOUNCE,
    VOTE,
    VOTE_PLAYERS,
    FakeBot,
    FakeInteraction,
    FakeUser,
    choose,
    component,
    game_completed,
    game_du_bot,
    iso,
    load_games,
    load_votes,
    press,
    view_of,
)


def api_client(fake_api):
    return ShamelessApiClient(fake_api.base_url, fake_api.api_key, transport=fake_api.transport)


class Horloge:
    """Horloge injectée : avance le temps sans attendre dix minutes."""

    def __init__(self, now: float):
        self.now = now

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock():
    return Horloge(1_000_000.0)


@pytest.fixture
def game(fake_api, clock):
    """Game terminée, contexte servi par GET /bot/games/{id}."""
    fake_api.games[1] = game_du_bot(1, completed_at=iso(clock.now))
    return fake_api.games[1]


def interaction(voter_id: int) -> FakeInteraction:
    return FakeInteraction(user=FakeUser(voter_id))


def embed_text(embed):
    parts = [embed.title or "", embed.description or ""]
    parts += [f"{f.name}\n{f.value}" for f in embed.fields]
    return "\n".join(parts)


# =========================
# CLIENT HTTP (routes /bot)
# =========================

async def test_the_game_context_is_read_from_the_bot_route(fake_api, game):
    client = api_client(fake_api)

    context = await client.get_game(1)
    await client.aclose()

    call = fake_api.calls[0]
    assert (call.method, call.path) == ("GET", "/bot/games/1")
    assert call.authorization == f"Bearer {fake_api.api_key}"
    assert context["teamA"][0]["playerId"] == game["teamA"][0]["playerId"]


async def test_a_bulletin_is_sent_with_an_explicit_null_for_an_omitted_title(fake_api, game):
    client = api_client(fake_api)

    await client.put_votes(1, "101", mvp_player_id=13, dofd_player_id=None)
    await client.aclose()

    call = fake_api.calls[0]
    assert (call.method, call.path) == ("PUT", "/bot/games/1/votes")
    assert call.payload == {"votantDiscordId": "101", "mvpPlayerId": 13, "dofdPlayerId": None}
    assert call.authorization == f"Bearer {fake_api.api_key}"


async def test_the_closed_results_are_read_from_the_bot_route(fake_api, game):
    fake_api.vote_status[1] = "clos"
    client = api_client(fake_api)

    results = await client.get_votes(1)
    await client.aclose()

    assert fake_api.calls[0].path == "/bot/games/1/votes"
    assert results["statut"] == "clos"


@pytest.mark.parametrize("status", [400, 409])
async def test_a_refused_bulletin_exposes_the_api_reason_and_stays_permanent(fake_api, game, status):
    fake_api.status = status
    fake_api.detail = "Les votes de cette game sont clos."
    client = api_client(fake_api)

    with pytest.raises(ShamelessApiError) as error:
        await client.put_votes(1, "101", mvp_player_id=13, dofd_player_id=None)
    await client.aclose()

    assert error.value.is_permanent
    assert error.value.status == status
    assert error.value.detail == "Les votes de cette game sont clos."  # affichable tel quel au votant
    assert fake_api.api_key not in str(error.value)


# =========================
# DÉLAI (10 minutes après CompletedAt)
# =========================

def test_the_default_window_closes_ten_minutes_after_completed_at():
    start = datetime(2026, 10, 17, 20, 0, tzinfo=timezone.utc).timestamp()

    assert deadline_of("2026-10-17T20:00:00Z", ShamelessSettings.vote_duration_seconds) == start + 600
    assert ShamelessSettings.vote_duration_seconds == 600.0


# =========================
# OUVERTURE DU BULLETIN (game_completed)
# =========================

async def opened_vote(fake_bot, guild, shameless_settings, fake_api, make_client, post_event, clock):
    """Bulletin publié pour la Game 1 et sa vue, tels que produits par le webhook."""
    cog = await load_votes(fake_bot, shameless_settings, api=api_client(fake_api), clock=clock)
    await post_event(await make_client(), game_completed(game_id=1))
    return cog, view_of(guild.get_channel(VOTE))


async def test_a_completed_game_proposes_the_bulletin_without_reading_any_result(
    fake_bot, guild, shameless_settings, fake_api, make_client, post_event, game, clock
):
    _, view = await opened_vote(fake_bot, guild, shameless_settings, fake_api, make_client, post_event, clock)

    sent = guild.get_channel(VOTE).sent
    assert len(sent) == 1  # ni annonce ni second bulletin
    text = embed_text(sent[0]["embed"])
    assert "MVP" in text and "DOFD" in text
    for player in VOTE_PLAYERS:
        assert player["prenom"] in text  # les dix Joueurs proposés, aucun décompte
    assert isinstance(view, BulletinDeVote)
    assert view.game_id == "1"
    assert [option.value for option in component(view, mvp_custom_id(1)).options] == [
        str(p["playerId"]) for p in VOTE_PLAYERS
    ]
    # l'API n'a livré que le contexte : aucun résultat lu avant la clôture
    paths = [(c.method, c.path) for c in fake_api.calls]
    assert ("GET", "/bot/games/1") in paths
    assert ("GET", "/bot/games/1/votes") not in paths


async def test_each_cog_listening_to_game_completed_runs_on_the_same_event(
    fake_bot, guild, shameless_settings, fake_api, make_client, post_event, game, clock
):
    # #5 (récap) et #15 (bulletin) écoutent tous deux game_completed : les deux doivent tourner
    await load_games(fake_bot, shameless_settings, api=api_client(fake_api))
    await load_votes(fake_bot, shameless_settings, api=api_client(fake_api), clock=clock)

    await post_event(await make_client(), game_completed(game_id=1))

    assert len(guild.get_channel(ANNOUNCE).sent) == 1  # récap de #5
    assert len(guild.get_channel(VOTE).sent) == 1  # bulletin de #15


async def test_a_missing_vote_channel_fails_the_event_so_shameless_retries(
    fake_bot, guild, shameless_settings, fake_api, make_client, post_event, game, clock
):
    unconfigured = replace(shameless_settings, vote_channel_id=None)
    await load_votes(fake_bot, unconfigured, api=api_client(fake_api), clock=clock)

    response = await post_event(await make_client(settings=unconfigured), game_completed(game_id=1))

    assert response.status_code == 500
    assert guild.get_channel(VOTE).sent == []


async def test_a_transiently_unavailable_context_lets_shameless_retry(
    fake_bot, guild, shameless_settings, fake_api, make_client, post_event, clock
):
    fake_api.games[1] = game_du_bot(1, completed_at=iso(clock.now))
    await load_votes(fake_bot, shameless_settings, api=api_client(fake_api), clock=clock)
    fake_api.status = 503

    response = await post_event(await make_client(), game_completed(game_id=1))

    assert response.status_code == 500


async def test_a_game_without_a_numeric_id_is_processed_without_any_call(
    fake_bot, guild, shameless_settings, fake_api, make_client, post_event, clock
):
    await load_votes(fake_bot, shameless_settings, api=api_client(fake_api), clock=clock)

    response = await post_event(await make_client(), game_completed(game_id="g-1"))

    assert response.json()["status"] == "processed"
    assert fake_api.calls == []


# =========================
# ÉLIGIBILITÉ, CHOIX ET ERREURS API
# =========================

async def test_a_linked_player_votes_for_one_title_and_may_omit_the_other(
    fake_bot, guild, shameless_settings, fake_api, make_client, post_event, game, clock
):
    _, view = await opened_vote(fake_bot, guild, shameless_settings, fake_api, make_client, post_event, clock)
    voter = interaction(101)  # Joueur A1 (playerId 11)

    await choose(view, mvp_custom_id(1), voter, ["13"])  # A3
    await press(view, submit_custom_id(1), voter)

    assert fake_api.votes[1]["101"] == {"mvpPlayerId": 13, "dofdPlayerId": None}
    assert "enregistré" in voter.response.messages[-1]["content"]
    put = next(c for c in fake_api.calls if c.path == "/bot/games/1/votes")
    assert put.method == "PUT"
    assert put.payload == {"votantDiscordId": "101", "mvpPlayerId": 13, "dofdPlayerId": None}


async def test_a_spectator_reported_by_ticket_14_can_vote_for_both_titles(
    fake_bot, guild, shameless_settings, fake_api, make_client, post_event, game, clock
):
    fake_api.spectateurs[1] = ["501"]  # transmis à la clôture par #14
    _, view = await opened_vote(fake_bot, guild, shameless_settings, fake_api, make_client, post_event, clock)
    voter = interaction(501)

    await choose(view, mvp_custom_id(1), voter, ["12"])
    await choose(view, dofd_custom_id(1), voter, ["22"])
    await press(view, submit_custom_id(1), voter)

    assert fake_api.votes[1]["501"] == {"mvpPlayerId": 12, "dofdPlayerId": 22}


async def test_a_second_choice_on_a_title_replaces_the_first(
    fake_bot, guild, shameless_settings, fake_api, make_client, post_event, game, clock
):
    # un Select par titre, max une valeur : le votant ne peut pas désigner deux Joueurs
    _, view = await opened_vote(fake_bot, guild, shameless_settings, fake_api, make_client, post_event, clock)
    voter = interaction(101)

    await choose(view, mvp_custom_id(1), voter, ["13"])
    await choose(view, mvp_custom_id(1), voter, ["14"])
    await press(view, submit_custom_id(1), voter)

    assert fake_api.votes[1]["101"] == {"mvpPlayerId": 14, "dofdPlayerId": None}


async def test_voting_for_oneself_is_refused_before_calling_the_api(
    fake_bot, guild, shameless_settings, fake_api, make_client, post_event, game, clock
):
    _, view = await opened_vote(fake_bot, guild, shameless_settings, fake_api, make_client, post_event, clock)
    voter = interaction(101)  # A1 = playerId 11

    await choose(view, mvp_custom_id(1), voter, ["11"])
    await press(view, submit_custom_id(1), voter)

    assert "toi-même" in voter.response.messages[-1]["content"]
    assert fake_api.votes == {}
    assert all(c.path != "/bot/games/1/votes" for c in fake_api.calls)


async def test_a_non_eligible_voter_is_shown_the_api_refusal(
    fake_bot, guild, shameless_settings, fake_api, make_client, post_event, game, clock
):
    _, view = await opened_vote(fake_bot, guild, shameless_settings, fake_api, make_client, post_event, clock)
    voter = interaction(999)  # ni Joueur lié ni Spectateur

    await choose(view, mvp_custom_id(1), voter, ["12"])
    await press(view, submit_custom_id(1), voter)

    assert "Seuls les dix Joueurs" in voter.response.messages[-1]["content"]
    assert fake_api.votes == {}


async def test_a_closed_window_is_shown_to_the_voter(
    fake_bot, guild, shameless_settings, fake_api, make_client, post_event, game, clock
):
    fake_api.vote_status[1] = "clos"
    _, view = await opened_vote(fake_bot, guild, shameless_settings, fake_api, make_client, post_event, clock)
    voter = interaction(101)

    await choose(view, mvp_custom_id(1), voter, ["13"])
    await press(view, submit_custom_id(1), voter)

    assert "clos" in voter.response.messages[-1]["content"]
    assert fake_api.votes == {}


async def test_a_transient_api_failure_invites_the_voter_to_retry_instead_of_a_refusal(
    fake_bot, guild, shameless_settings, fake_api, make_client, post_event, game, clock
):
    _, view = await opened_vote(fake_bot, guild, shameless_settings, fake_api, make_client, post_event, clock)
    fake_api.status = 503  # panne réseau/5xx : un retry peut réparer
    voter = interaction(101)

    await choose(view, mvp_custom_id(1), voter, ["13"])
    await press(view, submit_custom_id(1), voter)

    message = voter.response.messages[-1]["content"]
    assert "réessaie" in message
    assert "refusé" not in message  # jamais « refusé » pour une panne
    assert fake_api.votes == {}


# =========================
# CLÔTURE ET ANNONCE
# =========================

async def cast(view, discord_id: int, *, mvp: int | None = None, dofd: int | None = None):
    voter = interaction(discord_id)
    if mvp is not None:
        await choose(view, mvp_custom_id(1), voter, [str(mvp)])
    if dofd is not None:
        await choose(view, dofd_custom_id(1), voter, [str(dofd)])
    await press(view, submit_custom_id(1), voter)
    return voter


async def test_all_tied_winners_are_announced_after_the_window(
    fake_bot, guild, shameless_settings, fake_api, make_client, post_event, game, clock
):
    cog, view = await opened_vote(fake_bot, guild, shameless_settings, fake_api, make_client, post_event, clock)
    await cast(view, 101, mvp=13)  # A3
    await cast(view, 102, mvp=14)  # A4 : égalité
    fake_api.vote_status[1] = "clos"

    clock.now += 601  # dix minutes plus tard
    await cog.on_ready()

    sent = guild.get_channel(VOTE).sent
    assert len(sent) == 2  # bulletin + annonce
    text = embed_text(sent[-1]["embed"])
    assert "A3" in text and "A4" in text  # tous les ex æquo reconnus
    assert ("GET", "/bot/games/1/votes") in [(c.method, c.path) for c in fake_api.calls]


async def test_nothing_is_revealed_while_the_api_does_not_say_closed(
    fake_bot, guild, shameless_settings, fake_api, make_client, post_event, game, clock
):
    fake_api.vote_status[1] = "ouverts"
    cog, view = await opened_vote(fake_bot, guild, shameless_settings, fake_api, make_client, post_event, clock)
    await cast(view, 101, mvp=13)

    clock.now += 601
    await cog.on_ready()

    # l'API ne dit pas clos : aucune annonce, aucun décompte divulgué
    assert len(guild.get_channel(VOTE).sent) == 1


async def test_the_window_is_closed_by_the_timer_without_any_restart(
    fake_bot, guild, shameless_settings, fake_api, make_client, post_event
):
    settings = replace(shameless_settings, vote_duration_seconds=0.05)
    fake_api.games[1] = game_du_bot(1, completed_at=iso(time.time()))
    fake_api.vote_status[1] = "clos"
    await load_votes(fake_bot, settings, api=api_client(fake_api))  # horloge réelle

    await post_event(await make_client(settings=settings), game_completed(game_id=1))
    await asyncio.sleep(0.3)

    assert ("GET", "/bot/games/1/votes") in [(c.method, c.path) for c in fake_api.calls]
    assert len(guild.get_channel(VOTE).sent) == 2


async def test_a_restart_after_the_deadline_closes_the_window_at_boot(
    fake_bot, guild, shameless_settings, fake_api, make_client, post_event, game, clock
):
    await opened_vote(fake_bot, guild, shameless_settings, fake_api, make_client, post_event, clock)
    assert len(guild.get_channel(VOTE).sent) == 1  # bulletin
    fake_api.vote_status[1] = "clos"

    # le bot était arrêté au moment de l'échéance : la réconciliation de cog_load clôt
    rebooted = FakeBot(guilds=[guild])
    await load_votes(
        rebooted, shameless_settings, api=api_client(fake_api), clock=Horloge(clock.now + 601)
    )

    sent = guild.get_channel(VOTE).sent
    assert len(sent) == 2  # bulletin (non republié) + annonce
    assert "Aucun vote" in embed_text(sent[-1]["embed"])


async def test_a_reconnected_bot_closes_a_due_window_without_reposting_the_bulletin(
    fake_bot, guild, shameless_settings, fake_api, make_client, post_event, game, clock
):
    await opened_vote(fake_bot, guild, shameless_settings, fake_api, make_client, post_event, clock)
    fake_api.vote_status[1] = "clos"
    reboot_clock = Horloge(clock.now)
    rebooted = FakeBot(guilds=[guild])
    cog = await load_votes(rebooted, shameless_settings, api=api_client(fake_api), clock=reboot_clock)
    assert rebooted.views  # vue persistante réenregistrée pour survivre au redémarrage

    reboot_clock.now += 601
    await cog.on_ready()

    assert len(guild.get_channel(VOTE).sent) == 2  # pas de bulletin republié

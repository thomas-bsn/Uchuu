"""#14 transmission des Spectateurs d'une Game à l'API Shameless.

Piloté depuis la frontière FastAPI du bot (webhook signé) avec de faux salons vocaux ;
le bot écrit dans une fausse API Shameless. Aucun appel Discord ni réseau réel.
"""
from dataclasses import replace

from services.shameless_client import ShamelessApiClient
from tests.fakes import OTHER_VOICE, SHARED, TEAM1, game_completed, game_started, join, load_games


def api_client(fake_api):
    return ShamelessApiClient(fake_api.base_url, fake_api.api_key, transport=fake_api.transport)


async def test_spectators_present_during_the_game_are_transmitted_when_it_completes(
    fake_bot, guild, shameless_settings, fake_api, make_client, post_event
):
    cog = await load_games(fake_bot, shameless_settings, api=api_client(fake_api))
    client = await make_client()
    guild.add_member(101, voice=guild.get_channel(TEAM1))  # Joueur : jamais transmis
    guild.add_member(500, voice=guild.get_channel(SHARED))  # Spectateur présent au début

    await post_event(client, game_started(game_id=1))
    late = guild.add_member(501)
    await join(cog, late, guild.get_channel(OTHER_VOICE))  # arrivé pendant la Game
    await post_event(client, game_completed(game_id=1))

    assert fake_api.calls[0].path == "/bot/games/1/spectateurs"
    assert fake_api.spectateurs[1] == ["500", "501"]  # transmis à la clôture, avant les votes


async def test_starting_a_game_transmits_nothing(fake_bot, guild, shameless_settings, fake_api, make_client, post_event):
    await load_games(fake_bot, shameless_settings, api=api_client(fake_api))

    await post_event(await make_client(), game_started(game_id=1))

    assert fake_api.calls == []


async def test_a_game_without_spectators_transmits_an_empty_set(
    fake_bot, guild, shameless_settings, fake_api, make_client, post_event
):
    await load_games(fake_bot, shameless_settings, api=api_client(fake_api))
    client = await make_client()

    await post_event(client, game_started(game_id=1))
    await post_event(client, game_completed(game_id=1))

    assert fake_api.spectateurs[1] == []


async def test_a_transient_api_failure_lets_shameless_retry_without_duplicating_anything(
    fake_bot, guild, shameless_settings, fake_api, make_client, post_event
):
    await load_games(fake_bot, shameless_settings, api=api_client(fake_api))
    client = await make_client()
    announce = guild.get_channel(3000)
    guild.add_member(500, voice=guild.get_channel(SHARED))
    await post_event(client, game_started(game_id=1))
    posted = len(announce.sent)  # annonce de Série

    fake_api.status = 503  # l'API tombe au moment de la transmission
    failed = await post_event(client, game_completed(game_id=1))

    assert failed.status_code == 500
    assert len(announce.sent) == posted + 1  # le récap part avant la transmission
    fake_api.status = None
    retry = await post_event(client, game_completed(game_id=1))  # même event rejoué

    assert retry.json()["status"] == "processed"
    assert fake_api.spectateurs[1] == ["500"]
    assert len(fake_api.calls) == 2  # le rejeu remplace, sans doublon
    assert len(announce.sent) == posted + 1  # le récap n'est pas republié


async def test_a_permanent_refusal_is_accepted_so_shameless_stops_retrying(
    fake_bot, guild, shameless_settings, fake_api, make_client, post_event
):
    await load_games(fake_bot, shameless_settings, api=api_client(fake_api))
    client = await make_client()
    guild.add_member(500, voice=guild.get_channel(SHARED))
    await post_event(client, game_started(game_id=1))

    fake_api.status = 409  # votes déjà clos : retenter n'y changerait rien
    response = await post_event(client, game_completed(game_id=1))

    assert response.json()["status"] == "processed"
    assert fake_api.spectateurs == {}


async def test_a_missing_api_config_fails_the_event_so_it_is_retried_once_configured(
    fake_bot, guild, make_client, shameless_settings, post_event
):
    unconfigured = replace(shameless_settings, api_url=None, bot_to_api_key=None)
    await load_games(fake_bot, unconfigured)  # pas de client injecté : construit depuis la config
    guild.add_member(500, voice=guild.get_channel(SHARED))
    await post_event(await make_client(settings=unconfigured), game_started(game_id=1))

    response = await post_event(await make_client(settings=unconfigured), game_completed(game_id=1))

    assert response.status_code == 500


async def test_a_game_without_a_numeric_id_is_not_transmitted_but_is_processed(
    fake_bot, guild, shameless_settings, fake_api, make_client, post_event
):
    await load_games(fake_bot, shameless_settings, api=api_client(fake_api))
    client = await make_client()

    await post_event(client, game_started(game_id="g-1"))
    response = await post_event(client, game_completed(game_id="g-1"))

    assert response.json()["status"] == "processed"
    assert fake_api.calls == []


async def test_a_game_id_that_only_looks_numeric_is_still_ignored(
    fake_bot, guild, shameless_settings, fake_api, make_client, post_event
):
    # "²".isdigit() est vrai mais int("²") lève : l'event doit rester acquitté, pas boucler
    await load_games(fake_bot, shameless_settings, api=api_client(fake_api))
    client = await make_client()

    await post_event(client, game_started(game_id="²"))
    response = await post_event(client, game_completed(game_id="²"))

    assert response.json()["status"] == "processed"
    assert fake_api.calls == []

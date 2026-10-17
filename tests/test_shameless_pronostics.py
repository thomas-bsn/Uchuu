"""#16 Pronostics : bulletin Discord avant chaque Game, résultats annoncés après.

Tout est piloté depuis la frontière FastAPI du bot (webhook signé) avec un faux serveur
API Shameless et de fausses interactions Discord ; aucun appel Discord ni réseau réel.
"""
from dataclasses import replace

import pytest

from services.shameless_client import ShamelessApiClient, ShamelessApiError
from tests.fakes import (
    ANNOUNCE,
    COMPOSITION_A,
    COMPOSITION_B,
    PRONOSTICS,
    FakeBot,
    FakeInteraction,
    FakeMember,
    game_completed,
    game_pronostics,
    game_started,
    joueur_pronostique,
    load_pronostics,
    pronostic_evalue,
    series_pronostics,
    teams_formed,
)


def api_client(fake_api):
    return ShamelessApiClient(fake_api.base_url, fake_api.api_key, transport=fake_api.transport)


def pronostics_settings(settings, channel=PRONOSTICS):
    """Config #16 activée, sans boucle de réconciliation (les tests pilotent les events)."""
    return replace(settings, pronostics_channel_id=channel, pronostics_reconcile_seconds=0)


def embed_text(embed):
    parts = [embed.title or "", embed.description or "", embed.footer.text or ""]
    parts += [f.name + "\n" + f.value for f in embed.fields]
    return "\n".join(parts)


def result_embeds(channel, label):
    """Les annonces de résultat d'un titre (elles arrivent séparément)."""
    title = f"🎯 Pronostics — {label}"
    return [m for m in channel.sent if m.get("embed") and m["embed"].title == title]


@pytest.fixture
def pronostics_guild(guild):
    guild.add_text_channel(PRONOSTICS)
    return guild



# =========================
# CLIENT (routes /bot)
# =========================

async def test_the_open_game_preview_is_read_from_the_series_bot_route(fake_api):
    fake_api.series_pronostics[5] = series_pronostics(series_id=5, game_number=2)
    client = api_client(fake_api)

    preview = await client.get_series_pronostics(5)
    await client.aclose()

    call = fake_api.calls[0]
    assert (call.method, call.path) == ("GET", "/bot/series/5/pronostics")
    assert call.authorization == f"Bearer {fake_api.api_key}"
    assert preview["gameNumber"] == 2


async def test_a_pronostic_is_sent_with_every_contract_field(fake_api):
    client = api_client(fake_api)

    await client.put_pronostic(
        5,
        discord_id="500",
        nom="Alice",
        game_number=1,
        equipe_gagnante="A",
        mvp_player_id=11,
        dofd_player_id=21,
    )
    await client.aclose()

    call = fake_api.calls[0]
    assert (call.method, call.path) == ("PUT", "/bot/series/5/pronostics")
    assert call.payload == {
        "pronostiqueurDiscordId": "500",
        "pronostiqueurNom": "Alice",
        "gameNumber": 1,
        "equipeGagnante": "A",
        "mvpPlayerId": 11,
        "dofdPlayerId": 21,
    }


async def test_a_partial_pronostic_sends_explicit_nulls(fake_api):
    client = api_client(fake_api)

    await client.put_pronostic(5, discord_id="500", nom=None, game_number=1, equipe_gagnante="B")
    await client.aclose()

    assert fake_api.calls[0].payload == {
        "pronostiqueurDiscordId": "500",
        "pronostiqueurNom": None,
        "gameNumber": 1,
        "equipeGagnante": "B",
        "mvpPlayerId": None,
        "dofdPlayerId": None,
    }


async def test_evaluated_pronostics_are_read_from_the_game_bot_route(fake_api):
    fake_api.game_pronostics[7] = game_pronostics(game_id=7, vainqueur_connu=True, votes_clos=False)
    client = api_client(fake_api)

    result = await client.get_game_pronostics(7)
    await client.aclose()

    call = fake_api.calls[0]
    assert (call.method, call.path) == ("GET", "/bot/games/7/pronostics")
    assert result["vainqueurConnu"] is True
    assert result["votesClos"] is False


@pytest.mark.parametrize("status", [400, 409])
async def test_a_refused_pronostic_is_a_permanent_error_with_a_readable_reason(fake_api, status):
    fake_api.status = status
    fake_api.detail = "Cette game est lancée : ses pronostics sont verrouillés."
    client = api_client(fake_api)

    with pytest.raises(ShamelessApiError) as error:
        await client.put_pronostic(5, discord_id="500", nom="Alice", game_number=1, equipe_gagnante="A")
    await client.aclose()

    assert error.value.is_permanent
    assert error.value.status == status
    assert "Cette game est lancée" in str(error.value)  # le handler peut l'afficher tel quel
    assert fake_api.api_key not in str(error.value)  # la clé ne fuit jamais


# =========================
# PROPOSITION DU BULLETIN (avant game_started)
# =========================

async def test_the_open_game_is_proposed_to_spectators_when_the_series_forms(
    pronostics_guild, fake_bot, shameless_settings, fake_api, make_client, post_event
):
    settings = pronostics_settings(shameless_settings)
    fake_api.series_pronostics[5] = series_pronostics(series_id=5, game_number=1)
    await load_pronostics(fake_bot, settings, api=api_client(fake_api))
    client = await make_client(settings=settings)

    await post_event(client, teams_formed(series_id=5))

    sent = pronostics_guild.get_channel(PRONOSTICS).sent
    assert len(sent) == 1
    text = embed_text(sent[0]["embed"])
    assert "Game 1" in text
    assert "A1" in text and "B5" in text  # la composition courante est proposée
    assert sent[0]["view"] is not None  # un bulletin cliquable
    assert fake_api.calls[0].path == "/bot/series/5/pronostics"  # aperçu récupéré côté API


async def test_a_replayed_series_forming_does_not_post_a_second_bulletin(
    pronostics_guild, fake_bot, shameless_settings, fake_api, make_client, post_event
):
    settings = pronostics_settings(shameless_settings)
    fake_api.series_pronostics[5] = series_pronostics(series_id=5, game_number=1)
    await load_pronostics(fake_bot, settings, api=api_client(fake_api))
    client = await make_client(settings=settings)

    await post_event(client, teams_formed(series_id=5))
    await post_event(client, teams_formed(series_id=5))

    assert len(pronostics_guild.get_channel(PRONOSTICS).sent) == 1


async def test_a_locked_series_proposes_nothing(
    pronostics_guild, fake_bot, shameless_settings, fake_api, make_client, post_event
):
    settings = pronostics_settings(shameless_settings)
    fake_api.series_pronostics[5] = series_pronostics(series_id=5, game_number=None)  # Game lancée
    await load_pronostics(fake_bot, settings, api=api_client(fake_api))
    client = await make_client(settings=settings)

    response = await post_event(client, teams_formed(series_id=5))

    assert response.json()["status"] == "processed"
    assert pronostics_guild.get_channel(PRONOSTICS).sent == []


async def test_the_feature_is_off_when_no_pronostics_channel_is_configured(
    guild, fake_bot, shameless_settings, fake_api, make_client, post_event
):
    # pas de pronostics_channel_id : le cog ne publie rien et n'appelle pas l'API
    await load_pronostics(fake_bot, shameless_settings, api=api_client(fake_api))
    client = await make_client()

    response = await post_event(client, teams_formed(series_id=5))

    assert response.status_code == 200  # acquitté (aucun handler quand la fonctionnalité est éteinte)
    assert fake_api.calls == []


async def test_an_unreachable_api_lets_shameless_retry_the_proposal(
    pronostics_guild, fake_bot, shameless_settings, make_client, post_event
):
    settings = pronostics_settings(shameless_settings)
    await load_pronostics(fake_bot, settings)  # client construit depuis la config (jamais appelé)
    client = await make_client(settings=settings)

    response = await post_event(client, teams_formed(series_id=5))

    # API non configurée -> ShamelessApiError sans statut -> event non acquitté
    assert response.status_code == 500
    assert pronostics_guild.get_channel(PRONOSTICS).sent == []


# =========================
# SOUMISSION D'UN PRONOSTIC (interactions)
# =========================

async def open_bulletin(pronostics_guild, fake_bot, shameless_settings, fake_api, make_client, post_event):
    """Poste teams_formed et renvoie (cog, client, vue du bulletin) prêts pour les interactions."""
    settings = pronostics_settings(shameless_settings)
    fake_api.series_pronostics[5] = series_pronostics(series_id=5, game_number=1)
    cog = await load_pronostics(fake_bot, settings, api=api_client(fake_api))
    client = await make_client(settings=settings)
    await post_event(client, teams_formed(series_id=5))
    view = pronostics_guild.get_channel(PRONOSTICS).sent[0]["view"]
    return cog, client, view


def put_payloads(fake_api):
    return [call.payload for call in fake_api.calls if call.method == "PUT"]


async def test_a_spectator_builds_a_pronostic_that_is_transmitted_to_the_api(
    pronostics_guild, fake_bot, shameless_settings, fake_api, make_client, post_event
):
    _cog, _client, view = await open_bulletin(pronostics_guild, fake_bot, shameless_settings, fake_api, make_client, post_event)
    interaction = FakeInteraction(user=FakeMember(500, name="Alice"))

    await view.select_winner(interaction, "A")
    await view.select_mvp(interaction, 11)
    await view.select_dofd(interaction, 21)

    # l'API remplace le pronostic entier : le dernier envoi porte les trois choix
    assert put_payloads(fake_api)[-1] == {
        "pronostiqueurDiscordId": "500",
        "pronostiqueurNom": "Alice",
        "gameNumber": 1,
        "equipeGagnante": "A",
        "mvpPlayerId": 11,
        "dofdPlayerId": 21,
    }
    assert interaction.replies[-1]["ephemeral"] is True
    assert "enregistré" in interaction.content


async def test_a_joueur_of_the_composition_cannot_pronosticate(
    pronostics_guild, fake_bot, shameless_settings, fake_api, make_client, post_event
):
    _cog, _client, view = await open_bulletin(pronostics_guild, fake_bot, shameless_settings, fake_api, make_client, post_event)
    interaction = FakeInteraction(user=FakeMember(101, name="A1"))  # discordId lié d'un Joueur

    await view.select_winner(interaction, "A")

    assert put_payloads(fake_api) == []
    assert "Joueurs" in interaction.content


async def test_a_choice_outside_the_composition_is_refused_without_calling_the_api(
    pronostics_guild, fake_bot, shameless_settings, fake_api, make_client, post_event
):
    _cog, _client, view = await open_bulletin(pronostics_guild, fake_bot, shameless_settings, fake_api, make_client, post_event)
    interaction = FakeInteraction(user=FakeMember(500, name="Alice"))

    await view.select_mvp(interaction, 999)  # aucun Joueur de la Série

    assert put_payloads(fake_api) == []
    assert "invalide" in interaction.content


async def test_a_pronostic_submitted_after_the_game_started_is_refused(
    pronostics_guild, fake_bot, shameless_settings, fake_api, make_client, post_event
):
    _cog, client, view = await open_bulletin(pronostics_guild, fake_bot, shameless_settings, fake_api, make_client, post_event)
    await post_event(client, game_started(game_id=1, game_number=1, series_id=5))
    interaction = FakeInteraction(user=FakeMember(500, name="Alice"))

    await view.select_winner(interaction, "A")

    assert put_payloads(fake_api) == []
    assert "verrouill" in interaction.content


@pytest.mark.parametrize(
    ("status", "detail"),
    [
        (400, "On ne pronostique que la prochaine game de la Série (game 2)."),
        (409, "Cette game est lancée : ses pronostics sont verrouillés."),
    ],
)
async def test_an_api_refusal_is_explained_to_the_spectator(
    pronostics_guild, fake_bot, shameless_settings, fake_api, make_client, post_event, status, detail
):
    _cog, client, view = await open_bulletin(pronostics_guild, fake_bot, shameless_settings, fake_api, make_client, post_event)
    fake_api.status = status
    fake_api.detail = detail
    interaction = FakeInteraction(user=FakeMember(500, name="Alice"))

    await view.select_winner(interaction, "A")

    assert detail in interaction.content
    assert interaction.replies[-1]["ephemeral"] is True


async def test_a_stale_bulletin_submitted_after_the_api_locked_the_game_is_explained(
    pronostics_guild, fake_bot, shameless_settings, fake_api, make_client, post_event
):
    # le bot n'a pas vu le game_started (verrou local absent) : c'est l'API qui refuse
    _cog, client, view = await open_bulletin(pronostics_guild, fake_bot, shameless_settings, fake_api, make_client, post_event)
    fake_api.status = 409
    fake_api.detail = "Cette game est lancée : ses pronostics sont verrouillés."
    interaction = FakeInteraction(user=FakeMember(500, name="Alice"))

    await view.select_winner(interaction, "A")

    assert "verrouillés" in interaction.content




# =========================
# ANNONCE DES RÉSULTATS (après game_completed)
# =========================

WINNER_KNOWN_ONLY = game_pronostics(
    game_id=1,
    game_number=1,
    vainqueur_connu=True,
    votes_clos=False,
    pronostics=[
        pronostic_evalue("500", "Alice", equipe="A", equipe_correct=True,
                         mvp=joueur_pronostique("A1", 11, None), dofd=joueur_pronostique("B1", 21, None)),
        pronostic_evalue("501", "Bob", equipe="B", equipe_correct=False, mvp=None, dofd=None),
    ],
)

EVERYTHING_KNOWN = game_pronostics(
    game_id=1,
    game_number=1,
    vainqueur_connu=True,
    votes_clos=True,
    pronostics=[
        pronostic_evalue("500", "Alice", equipe="A", equipe_correct=True,
                         mvp=joueur_pronostique("A1", 11, True), dofd=joueur_pronostique("B1", 21, True)),
        pronostic_evalue("501", "Bob", equipe="B", equipe_correct=False,
                         mvp=joueur_pronostique("A1", 11, True), dofd=joueur_pronostique("B1", 21, False)),
    ],
)


async def started_series(pronostics_guild, fake_bot, shameless_settings, fake_api, make_client, post_event):
    """Cog prêt, bulletin de la Game 1 posté, la Game 2 ouverte à la clôture."""
    cog, client, _view = await open_bulletin(pronostics_guild, fake_bot, shameless_settings, fake_api, make_client, post_event)
    fake_api.series_pronostics[5] = series_pronostics(series_id=5, game_number=2)
    return cog, client


async def test_the_winner_answer_is_announced_as_soon_as_the_game_completes(
    pronostics_guild, fake_bot, shameless_settings, fake_api, make_client, post_event
):
    fake_api.game_pronostics[1] = WINNER_KNOWN_ONLY
    _cog, client = await started_series(pronostics_guild, fake_bot, shameless_settings, fake_api, make_client, post_event)

    await post_event(client, game_completed(game_id=1, series_id=5, winner="A"))

    channel = pronostics_guild.get_channel(PRONOSTICS)
    winner = result_embeds(channel, "Vainqueur")
    assert len(winner) == 1
    text = embed_text(winner[0]["embed"])
    assert "Team A" in text and "Alice" in text and "Bob" not in text  # seul Alice a vu juste
    assert result_embeds(channel, "MVP") == []  # pas encore connu
    assert result_embeds(channel, "DOFD") == []
    assert any("Game 2" in (m["embed"].title or "") for m in channel.sent)  # Game suivante proposée


async def test_mvp_and_dofd_are_announced_separately_once_the_votes_close(
    pronostics_guild, fake_bot, shameless_settings, fake_api, make_client, post_event
):
    fake_api.game_pronostics[1] = WINNER_KNOWN_ONLY
    cog, client = await started_series(pronostics_guild, fake_bot, shameless_settings, fake_api, make_client, post_event)
    await post_event(client, game_completed(game_id=1, series_id=5, winner="A"))
    channel = pronostics_guild.get_channel(PRONOSTICS)

    fake_api.game_pronostics[1] = EVERYTHING_KNOWN  # les votes sont clos
    await cog.reconcile_pronostics()

    mvp = result_embeds(channel, "MVP")
    dofd = result_embeds(channel, "DOFD")
    assert len(mvp) == 1 and len(dofd) == 1  # deux annonces distinctes
    mvp_text = embed_text(mvp[0]["embed"])
    dofd_text = embed_text(dofd[0]["embed"])
    assert "A1" in mvp_text and "Alice" in mvp_text and "Bob" in mvp_text
    assert "B1" in dofd_text and "Alice" in dofd_text and "Bob" not in dofd_text
    # aucun point, aucun classement, aucun titre Doyen
    assert "point" in mvp_text and "classement" in mvp_text and "Doyen" not in mvp_text

    await cog.reconcile_pronostics()  # re-vérification : rien n'est ré-annoncé
    assert len(result_embeds(channel, "MVP")) == 1


async def test_a_game_without_pronostics_result_is_acknowledged(
    pronostics_guild, fake_bot, shameless_settings, fake_api, make_client, post_event
):
    _cog, client = await started_series(pronostics_guild, fake_bot, shameless_settings, fake_api, make_client, post_event)
    # aucun game_pronostics[1] côté API -> 404 (payload non réparable) -> acquitté
    response = await post_event(client, game_completed(game_id=1, series_id=5, winner="A"))

    assert response.json()["status"] == "processed"
    assert result_embeds(pronostics_guild.get_channel(PRONOSTICS), "Vainqueur") == []


async def test_a_transient_api_failure_lets_shameless_retry_the_results_once(
    pronostics_guild, fake_bot, shameless_settings, fake_api, make_client, post_event
):
    fake_api.game_pronostics[1] = WINNER_KNOWN_ONLY
    _cog, client = await started_series(pronostics_guild, fake_bot, shameless_settings, fake_api, make_client, post_event)

    fake_api.status = 503  # l'API tombe au moment d'annoncer
    failed = await post_event(client, game_completed(game_id=1, series_id=5, winner="A"))
    assert failed.status_code == 500

    fake_api.status = None
    retry = await post_event(client, game_completed(game_id=1, series_id=5, winner="A"))
    assert retry.json()["status"] == "processed"
    assert len(result_embeds(pronostics_guild.get_channel(PRONOSTICS), "Vainqueur")) == 1


async def test_the_proposal_survives_a_restart_without_republishing(
    pronostics_guild, fake_bot, shameless_settings, fake_api, make_client, post_event
):
    settings = pronostics_settings(shameless_settings)
    fake_api.series_pronostics[5] = series_pronostics(series_id=5, game_number=1)
    await load_pronostics(fake_bot, settings, api=api_client(fake_api))
    await post_event(await make_client(settings=settings), teams_formed(series_id=5))

    # redémarrage : même SQLite, nouveau bot -> pas de second bulletin
    rebooted = FakeBot(guilds=[pronostics_guild])
    await load_pronostics(rebooted, settings, api=api_client(fake_api))
    await post_event(await make_client(rebooted, settings=settings), teams_formed(series_id=5))

    assert len(pronostics_guild.get_channel(PRONOSTICS).sent) == 1

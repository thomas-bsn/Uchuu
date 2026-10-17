"""#14 client HTTP bot -> API Shameless (routes /bot, ADR 0013).

Le client est testé contre une fausse API (vraie app FastAPI + transport httpx) :
rien ne sort de la machine, mais la requête est réelle (méthode, chemin, en-têtes, corps).
"""
import pytest

from services.shameless_client import ShamelessApiClient, ShamelessApiError


def make_client(fake_api, **kwargs):
    return ShamelessApiClient(fake_api.base_url, fake_api.api_key, transport=fake_api.transport, **kwargs)


async def test_spectateurs_are_pushed_to_the_bot_route_as_sorted_discord_ids(fake_api):
    client = make_client(fake_api)

    await client.put_spectateurs(42, {"2", "1"})
    await client.aclose()

    call = fake_api.calls[0]
    assert (call.method, call.path) == ("PUT", "/bot/games/42/spectateurs")
    assert call.payload == {"discordIds": ["1", "2"]}
    assert call.authorization == f"Bearer {fake_api.api_key}"


@pytest.mark.parametrize("status", [400, 409])
async def test_refused_spectateurs_are_permanent_errors_with_a_readable_reason(fake_api, status):
    fake_api.status = status
    fake_api.detail = "les votes sont clos"
    client = make_client(fake_api)

    with pytest.raises(ShamelessApiError) as error:
        await client.put_spectateurs(42, {"1"})
    await client.aclose()

    assert error.value.is_permanent  # inutile de retenter : relancer ne réparera rien
    assert error.value.status == status
    message = str(error.value)
    assert "PUT /bot/games/42/spectateurs" in message
    assert str(status) in message
    assert "les votes sont clos" in message  # le handler peut l'afficher tel quel
    assert fake_api.api_key not in message  # la clé ne fuit jamais


@pytest.mark.parametrize("status", [401, 408, 429, 500, 503])
async def test_failures_a_retry_can_fix_stay_retryable(fake_api, status):
    fake_api.status = status
    client = make_client(fake_api)

    with pytest.raises(ShamelessApiError) as error:
        await client.put_spectateurs(42, {"1"})
    await client.aclose()

    assert not error.value.is_permanent
    assert error.value.status == status
    assert fake_api.api_key not in str(error.value)


async def test_an_unreachable_api_is_a_retryable_error(fake_api):
    client = ShamelessApiClient(fake_api.base_url, fake_api.api_key, transport=fake_api.unreachable_transport())

    with pytest.raises(ShamelessApiError) as error:
        await client.put_spectateurs(42, {"1"})
    await client.aclose()

    assert not error.value.is_permanent
    assert error.value.status is None
    assert fake_api.api_key not in str(error.value)


async def test_a_new_transmission_replaces_the_set_and_a_replay_creates_no_duplicate(fake_api):
    client = make_client(fake_api)

    await client.put_spectateurs(42, {"1", "2"})
    await client.put_spectateurs(42, {"1", "2", "3"})
    await client.put_spectateurs(42, {"1", "2", "3"})  # rejeu du même event
    await client.aclose()

    assert fake_api.spectateurs[42] == ["1", "2", "3"]
    assert len(fake_api.calls) == 3

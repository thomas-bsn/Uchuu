"""Cog Votes : erreurs des boucles et du bouton remontées au salon de logs, tick périodique."""
import pytest

from cogs.votes import VotesCog
from services.vote import RETRY_SECONDS, Votes
from services.vote_policies import ConfiancePolicy, InvitePolicy
from services.vote_store import VoteStore
from services.vote_types import VoteKind
from tests.fakes import FakeBot
from tests.vote_fakes import FakeClock, FakeVoteGateway

INVITE, MEMBRE, CONFIANCE = 11, 12, 13
NEWCOMER, ALICE = 100, 201
DAY = 24 * 3600


@pytest.fixture
def gateway():
    gw = FakeVoteGateway()
    gw.add_member(NEWCOMER)
    gw.add_member(ALICE, MEMBRE, CONFIANCE)
    return gw


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def cog(bot_settings, gateway, clock):
    cog = VotesCog(FakeBot(), bot_settings)
    cog.votes = Votes(
        VoteStore(bot_settings.votes.db_path),
        gateway,
        [InvitePolicy(bot_settings.ids, bot_settings.votes), ConfiancePolicy(bot_settings.ids, bot_settings.votes)],
        approvals_required=1,
        voter_role_id=CONFIANCE,
        clock=clock,
    )
    return cog


def boom(*args, **kwargs):
    raise RuntimeError("disque plein")


async def test_a_click_that_crashes_gets_an_error_reply_and_is_posted_to_the_logs(cog, gateway, monkeypatch):
    vote = await cog.votes.open(VoteKind.INVITE, NEWCOMER)
    monkeypatch.setattr(cog.votes.store, "add_ballot", boom)

    reply = await cog.vote_clicked(vote.id, ALICE)

    assert "Erreur" in reply
    assert any("disque plein" in log for log in gateway.logs)


async def test_a_tick_failure_is_posted_to_the_logs_and_the_other_steps_still_run(cog, gateway, clock, monkeypatch):
    gateway.validation_channel_available = False
    await cog.votes.open(VoteKind.INVITE, NEWCOMER)
    gateway.validation_channel_available = True
    monkeypatch.setattr(cog.votes, "expire_due", boom)

    clock.advance(RETRY_SECONDS)
    await cog.tick()

    assert any("expiration" in log and "disque plein" in log for log in gateway.logs)
    assert len(gateway.live_messages()) == 1  # le rattrapage a tourné malgré l'échec


async def test_a_scan_failure_is_posted_to_the_logs(cog, gateway, monkeypatch):
    monkeypatch.setattr(cog.votes, "scan", boom)

    await cog.scan()

    assert any("Confiance" in log and "disque plein" in log for log in gateway.logs)


async def test_the_tick_expires_due_votes(cog, gateway, clock):
    await cog.votes.open(VoteKind.INVITE, NEWCOMER)

    clock.advance(DAY)
    await cog.tick()

    assert gateway.kicked == [NEWCOMER]

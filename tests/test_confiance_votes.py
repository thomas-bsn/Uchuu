"""Promotion Membre → Confiance, testée à l'interface du module Vote :
fake gateway, horloge contrôlée, SQLite temporaire."""
import pytest

from services.vote import Votes
from services.vote_policies import ConfiancePolicy, InvitePolicy
from services.vote_store import VoteStore
from services.vote_types import VoteKind
from tests.vote_fakes import FakeClock, FakeVoteGateway

INVITE, MEMBRE, CONFIANCE = 11, 12, 13  # ids de rôles de TEST_ENV
ALICE, BOB, VETERAN, ROOKIE = 201, 202, 301, 302
DAY = 24 * 3600


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def gateway(clock):
    gw = FakeVoteGateway()
    gw.add_member(ALICE, MEMBRE, CONFIANCE, joined_at=clock.now - 400 * DAY)
    gw.add_member(BOB, MEMBRE, CONFIANCE, joined_at=clock.now - 400 * DAY)
    gw.add_member(VETERAN, MEMBRE, joined_at=clock.now - 30 * DAY)
    gw.add_member(ROOKIE, MEMBRE, joined_at=clock.now - 29 * DAY)
    return gw


@pytest.fixture
def make_votes(bot_settings, gateway, clock):
    """Le rappeler = redémarrage (store rouvert)."""

    def _make():
        settings = bot_settings.votes
        return Votes(
            VoteStore(settings.db_path),
            gateway,
            [InvitePolicy(bot_settings.ids, settings), ConfiancePolicy(bot_settings.ids, settings)],
            approvals_required=settings.approvals_required,
            voter_role_id=bot_settings.ids.role_confiance_id,
            clock=clock,
        )

    return _make


@pytest.fixture
def votes(make_votes):
    return make_votes()


def targets(gateway):
    return sorted(int(m.content.split("<@")[1].split(">")[0]) for m in gateway.live_messages())


async def test_the_scan_proposes_membres_present_for_the_eligibility_period(votes, gateway, clock):
    opened = await votes.scan(VoteKind.CONFIANCE)

    assert [vote.target_id for vote in opened] == [VETERAN]
    [message] = gateway.live_messages()
    assert f"<@{VETERAN}>" in message.content
    assert "0/1" in message.content
    assert f"<t:{int(clock.now + DAY)}:R>" in message.content


async def test_the_scan_ignores_bots_and_non_membres(votes, gateway, clock):
    long_ago = clock.now - 400 * DAY
    gateway.add_member(401, MEMBRE, bot=True, joined_at=long_ago)
    gateway.add_member(402, INVITE, joined_at=long_ago)
    gateway.add_member(403, joined_at=long_ago)

    opened = await votes.scan(VoteKind.CONFIANCE)

    assert [vote.target_id for vote in opened] == [VETERAN]


async def test_a_daily_scan_never_reposts_a_membre_whose_vote_is_open(votes, gateway, clock):
    await votes.scan(VoteKind.CONFIANCE)

    clock.advance(DAY / 2)
    again = await votes.scan(VoteKind.CONFIANCE)

    assert again == []
    assert targets(gateway) == [VETERAN]


async def test_reaching_the_quorum_gives_the_confiance_role(votes, gateway):
    [vote] = await votes.scan(VoteKind.CONFIANCE)

    reply = await votes.approve(vote.id, ALICE)

    assert "quorum" in reply.lower()
    assert CONFIANCE in gateway.roles_of(VETERAN)
    assert MEMBRE in gateway.roles_of(VETERAN)
    assert gateway.live_messages() == []
    [log] = gateway.logs
    assert f"<@{VETERAN}>" in log and f"<@{ALICE}>" in log


async def test_confiance_votes_follow_the_invite_voting_rules(votes, gateway):
    gateway.add_member(VETERAN, MEMBRE, joined_at=gateway.roster[VETERAN].joined_at)
    gateway.add_member(ROOKIE, MEMBRE, joined_at=gateway.roster[VETERAN].joined_at)
    [vote, _] = await votes.scan(VoteKind.CONFIANCE)

    assert "toi-même" in await votes.approve(vote.id, VETERAN)
    assert "Confiance" in await votes.approve(vote.id, ROOKIE)  # Membre sans rôle Confiance

    assert CONFIANCE not in gateway.roles_of(VETERAN)
    assert len(gateway.live_messages()) == 2


async def test_an_expired_confiance_vote_changes_no_role_and_kicks_nobody(votes, gateway, clock):
    await votes.scan(VoteKind.CONFIANCE)

    clock.advance(DAY)
    await votes.expire_due()

    assert gateway.roles_of(VETERAN) == {MEMBRE}
    assert gateway.kicked == [] and gateway.dms == []
    assert gateway.live_messages() == []
    [log] = gateway.logs
    assert f"<@{VETERAN}>" in log


async def test_after_an_expired_vote_the_membre_waits_for_the_cooldown_even_across_restarts(
    make_votes, gateway, clock
):
    del gateway.roster[ROOKIE]
    await make_votes().scan(VoteKind.CONFIANCE)
    clock.advance(DAY)
    await make_votes().expire_due()
    expired_at = clock.now

    clock.advance(DAY)
    assert await make_votes().scan(VoteKind.CONFIANCE) == []

    clock.now = expired_at + 30 * DAY - 1
    assert await make_votes().scan(VoteKind.CONFIANCE) == []
    assert gateway.live_messages() == []

    clock.now = expired_at + 30 * DAY
    reopened = await make_votes().scan(VoteKind.CONFIANCE)
    assert [vote.target_id for vote in reopened] == [VETERAN]

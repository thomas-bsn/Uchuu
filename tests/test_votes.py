"""Module Vote, testé à son interface : fake gateway, horloge contrôlée, SQLite temporaire."""
import pytest

from services.vote import Votes
from services.vote_policies import InvitePolicy
from services.vote_store import VoteStore
from tests.vote_fakes import FakeClock, FakeVoteGateway

INVITE, MEMBRE, CONFIANCE = 11, 12, 13  # ids de rôles de TEST_ENV
NEWCOMER, ALICE, BOB, CAROL = 100, 201, 202, 203
DAY = 24 * 3600


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def gateway():
    gw = FakeVoteGateway()
    gw.add_member(NEWCOMER)
    gw.add_member(ALICE, MEMBRE, CONFIANCE)
    gw.add_member(BOB, MEMBRE, CONFIANCE)
    gw.add_member(CAROL, MEMBRE)
    return gw


@pytest.fixture
def make_votes(bot_settings, gateway, clock):
    """make_votes(approvals=None) -> Votes ; le rappeler = redémarrage (store rouvert)."""

    def _make(approvals=None):
        votes_settings = bot_settings.votes
        if approvals is not None:
            from dataclasses import replace
            votes_settings = replace(votes_settings, approvals_required=approvals)
        return Votes(
            VoteStore(votes_settings.db_path),
            gateway,
            [InvitePolicy(bot_settings.ids, votes_settings)],
            approvals_required=votes_settings.approvals_required,
            voter_role_id=bot_settings.ids.role_confiance_id,
            clock=clock,
        )

    return _make


@pytest.fixture
def votes(make_votes):
    return make_votes()


async def test_opening_an_invite_vote_gives_the_invite_role_and_posts_the_vote(votes, gateway, clock):
    await votes.open("invite", NEWCOMER)

    assert INVITE in gateway.roles_of(NEWCOMER)
    [message] = gateway.live_messages()
    assert f"<@{NEWCOMER}>" in message.content
    assert "0/1" in message.content
    assert f"<t:{int(clock.now + DAY)}:R>" in message.content


async def test_reaching_the_quorum_turns_the_invite_into_a_membre(make_votes, gateway):
    votes = make_votes(approvals=2)
    vote = await votes.open("invite", NEWCOMER)

    await votes.approve(vote.id, ALICE)
    assert INVITE in gateway.roles_of(NEWCOMER)
    reply = await votes.approve(vote.id, BOB)

    assert MEMBRE in gateway.roles_of(NEWCOMER)
    assert INVITE not in gateway.roles_of(NEWCOMER)
    assert gateway.live_messages() == []
    [log] = gateway.logs
    assert f"<@{NEWCOMER}>" in log and f"<@{ALICE}>, <@{BOB}>" in log
    assert "quorum" in reply.lower()


async def test_each_approval_updates_the_counter_on_the_vote_message(make_votes, gateway):
    votes = make_votes(approvals=2)
    vote = await votes.open("invite", NEWCOMER)

    reply = await votes.approve(vote.id, ALICE)

    [message] = gateway.live_messages()
    assert "1/2" in message.content
    assert "1/2" in reply


async def test_a_double_click_is_counted_once(make_votes, gateway):
    votes = make_votes(approvals=2)
    vote = await votes.open("invite", NEWCOMER)

    await votes.approve(vote.id, ALICE)
    reply = await votes.approve(vote.id, ALICE)

    assert "déjà" in reply
    assert INVITE in gateway.roles_of(NEWCOMER)
    [message] = gateway.live_messages()
    assert "1/2" in message.content


async def test_a_voter_without_the_confiance_role_is_refused(votes, gateway):
    vote = await votes.open("invite", NEWCOMER)

    reply = await votes.approve(vote.id, CAROL)

    assert "Confiance" in reply
    assert INVITE in gateway.roles_of(NEWCOMER)
    [message] = gateway.live_messages()
    assert "0/1" in message.content


async def test_nobody_can_vote_for_themselves(bot_settings, make_votes, gateway):
    gateway.add_member(NEWCOMER, CONFIANCE)  # cas limite : la cible a le rôle Confiance
    votes = make_votes()
    vote = await votes.open("invite", NEWCOMER)

    reply = await votes.approve(vote.id, NEWCOMER)

    assert "toi-même" in reply
    assert MEMBRE not in gateway.roles_of(NEWCOMER)


async def test_clicking_a_closed_vote_says_it_is_over(votes, gateway):
    vote = await votes.open("invite", NEWCOMER)
    await votes.approve(vote.id, ALICE)

    reply = await votes.approve(vote.id, BOB)

    assert "terminé" in reply
    assert len(gateway.logs) == 1


async def test_an_invite_vote_without_quorum_expires_with_a_dm_then_a_kick(make_votes, gateway, clock):
    votes = make_votes(approvals=2)
    vote = await votes.open("invite", NEWCOMER)
    await votes.approve(vote.id, ALICE)

    clock.advance(DAY - 1)
    await votes.expire_due()
    assert gateway.kicked == []

    clock.advance(1)
    await votes.expire_due()

    [(dm_target, _)] = gateway.dms
    assert dm_target == NEWCOMER
    assert gateway.kicked == [NEWCOMER]
    assert gateway.live_messages() == []
    [log] = gateway.logs
    assert f"<@{NEWCOMER}>" in log and f"<@{ALICE}>" in log
    assert "terminé" in await votes.approve(vote.id, BOB)


async def test_expiry_does_not_kick_an_invite_whose_role_was_removed_manually(votes, gateway, clock):
    await votes.open("invite", NEWCOMER)
    await gateway.remove_role(NEWCOMER, INVITE, "admission manuelle")

    clock.advance(DAY)
    await votes.expire_due()

    assert gateway.kicked == [] and gateway.dms == []
    assert gateway.live_messages() == []
    [log] = gateway.logs
    assert f"<@{NEWCOMER}>" in log


async def test_expiry_of_an_invite_who_already_left_only_closes_the_vote(votes, gateway, clock):
    vote = await votes.open("invite", NEWCOMER)
    del gateway.members[NEWCOMER]

    clock.advance(DAY)
    await votes.expire_due()

    assert gateway.kicked == [] and gateway.dms == []
    assert gateway.live_messages() == []
    assert len(gateway.logs) == 1
    assert "terminé" in await votes.approve(vote.id, ALICE)


async def test_an_open_vote_can_be_completed_after_a_restart(make_votes, gateway):
    vote = await make_votes(approvals=2).open("invite", NEWCOMER)
    await make_votes(approvals=2).approve(vote.id, ALICE)

    restarted = make_votes(approvals=2)
    assert "déjà" in await restarted.approve(vote.id, ALICE)
    await restarted.approve(vote.id, BOB)

    assert MEMBRE in gateway.roles_of(NEWCOMER)
    assert gateway.live_messages() == []


async def test_an_open_vote_expires_on_schedule_after_a_restart(make_votes, gateway, clock):
    await make_votes().open("invite", NEWCOMER)

    restarted = make_votes()
    clock.advance(DAY - 1)
    await restarted.expire_due()
    assert gateway.kicked == []
    clock.advance(1)
    await restarted.expire_due()

    assert gateway.kicked == [NEWCOMER]


async def test_without_a_validation_channel_the_problem_is_logged_and_nobody_is_kicked_later(votes, gateway, clock):
    gateway.validation_channel_available = False

    assert await votes.open("invite", NEWCOMER) is None

    assert gateway.logs  # le problème est loggé
    clock.advance(DAY)
    assert await votes.expire_due() == []
    assert gateway.kicked == []


async def test_no_vote_opens_when_the_invite_role_cannot_be_given(votes, gateway):
    assert await votes.open("invite", 999) is None  # membre introuvable

    assert gateway.live_messages() == []


async def test_a_target_has_at_most_one_open_vote_per_policy(votes, gateway):
    first = await votes.open("invite", NEWCOMER)
    again = await votes.open("invite", NEWCOMER)

    assert again.id == first.id
    assert len(gateway.live_messages()) == 1

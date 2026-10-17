"""Module Vote, testé à son interface : fake gateway, horloge contrôlée, SQLite temporaire."""
import pytest

from services.vote import RETRY_SECONDS, Votes
from services.vote_policies import InvitePolicy
from services.vote_store import VoteStore
from services.vote_types import VoteKind, VoteStatus
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
    await votes.open(VoteKind.INVITE, NEWCOMER)

    assert INVITE in gateway.roles_of(NEWCOMER)
    [message] = gateway.live_messages()
    assert f"<@{NEWCOMER}>" in message.content
    assert "0/1" in message.content
    assert f"<t:{int(clock.now + DAY)}:R>" in message.content


async def test_reaching_the_quorum_turns_the_invite_into_a_membre(make_votes, gateway):
    votes = make_votes(approvals=2)
    vote = await votes.open(VoteKind.INVITE, NEWCOMER)

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
    vote = await votes.open(VoteKind.INVITE, NEWCOMER)

    reply = await votes.approve(vote.id, ALICE)

    [message] = gateway.live_messages()
    assert "1/2" in message.content
    assert "1/2" in reply


async def test_a_double_click_is_counted_once(make_votes, gateway):
    votes = make_votes(approvals=2)
    vote = await votes.open(VoteKind.INVITE, NEWCOMER)

    await votes.approve(vote.id, ALICE)
    reply = await votes.approve(vote.id, ALICE)

    assert "déjà" in reply
    assert INVITE in gateway.roles_of(NEWCOMER)
    [message] = gateway.live_messages()
    assert "1/2" in message.content


async def test_a_voter_without_the_confiance_role_is_refused(votes, gateway):
    vote = await votes.open(VoteKind.INVITE, NEWCOMER)

    reply = await votes.approve(vote.id, CAROL)

    assert "Confiance" in reply
    assert INVITE in gateway.roles_of(NEWCOMER)
    [message] = gateway.live_messages()
    assert "0/1" in message.content


async def test_nobody_can_vote_for_themselves(bot_settings, make_votes, gateway):
    gateway.add_member(NEWCOMER, CONFIANCE)  # cas limite : la cible a le rôle Confiance
    votes = make_votes()
    vote = await votes.open(VoteKind.INVITE, NEWCOMER)

    reply = await votes.approve(vote.id, NEWCOMER)

    assert "toi-même" in reply
    assert MEMBRE not in gateway.roles_of(NEWCOMER)


async def test_clicking_a_closed_vote_says_it_is_over(votes, gateway):
    vote = await votes.open(VoteKind.INVITE, NEWCOMER)
    await votes.approve(vote.id, ALICE)

    reply = await votes.approve(vote.id, BOB)

    assert "terminé" in reply
    assert len(gateway.logs) == 1


async def test_an_invite_vote_without_quorum_expires_with_a_dm_then_a_kick(make_votes, gateway, clock):
    votes = make_votes(approvals=2)
    vote = await votes.open(VoteKind.INVITE, NEWCOMER)
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
    await votes.open(VoteKind.INVITE, NEWCOMER)
    await gateway.remove_role(NEWCOMER, INVITE, "admission manuelle")

    clock.advance(DAY)
    await votes.expire_due()

    assert gateway.kicked == [] and gateway.dms == []
    assert gateway.live_messages() == []
    [log] = gateway.logs
    assert f"<@{NEWCOMER}>" in log


async def test_expiry_of_an_invite_who_already_left_only_closes_the_vote(votes, gateway, clock):
    vote = await votes.open(VoteKind.INVITE, NEWCOMER)
    del gateway.roster[NEWCOMER]

    clock.advance(DAY)
    await votes.expire_due()

    assert gateway.kicked == [] and gateway.dms == []
    assert gateway.live_messages() == []
    assert len(gateway.logs) == 1
    assert "terminé" in await votes.approve(vote.id, ALICE)


async def test_an_open_vote_can_be_completed_after_a_restart(make_votes, gateway):
    vote = await make_votes(approvals=2).open(VoteKind.INVITE, NEWCOMER)
    await make_votes(approvals=2).approve(vote.id, ALICE)

    restarted = make_votes(approvals=2)
    assert "déjà" in await restarted.approve(vote.id, ALICE)
    await restarted.approve(vote.id, BOB)

    assert MEMBRE in gateway.roles_of(NEWCOMER)
    assert gateway.live_messages() == []


async def test_an_open_vote_expires_on_schedule_after_a_restart(make_votes, gateway, clock):
    await make_votes().open(VoteKind.INVITE, NEWCOMER)

    restarted = make_votes()
    clock.advance(DAY - 1)
    await restarted.expire_due()
    assert gateway.kicked == []
    clock.advance(1)
    await restarted.expire_due()

    assert gateway.kicked == [NEWCOMER]


async def test_a_vote_message_that_could_not_be_posted_is_posted_by_the_next_tick(votes, gateway, clock):
    gateway.validation_channel_available = False

    vote = await votes.open(VoteKind.INVITE, NEWCOMER)

    assert vote.status == VoteStatus.OPEN
    assert INVITE in gateway.roles_of(NEWCOMER)
    assert gateway.logs  # le problème est loggé
    assert gateway.live_messages() == []

    gateway.validation_channel_available = True
    clock.advance(RETRY_SECONDS)
    await votes.reconcile()

    [message] = gateway.live_messages()
    assert f"<@{NEWCOMER}>" in message.content
    await votes.approve(vote.id, ALICE)
    assert MEMBRE in gateway.roles_of(NEWCOMER)
    assert gateway.live_messages() == []


async def test_an_invite_whose_vote_was_never_posted_is_still_kicked_at_expiry(votes, gateway, clock):
    gateway.validation_channel_available = False
    await votes.open(VoteKind.INVITE, NEWCOMER)

    clock.advance(DAY)
    await votes.expire_due()

    assert gateway.kicked == [NEWCOMER]


async def test_an_invite_role_that_could_not_be_given_is_given_by_the_next_tick(votes, gateway, clock):
    gateway.role_changes_fail = True

    vote = await votes.open(VoteKind.INVITE, NEWCOMER)

    assert vote.status == VoteStatus.OPEN
    assert INVITE not in gateway.roles_of(NEWCOMER)
    assert len(gateway.live_messages()) == 1

    gateway.role_changes_fail = False
    clock.advance(RETRY_SECONDS)
    await votes.reconcile()

    assert INVITE in gateway.roles_of(NEWCOMER)
    assert len(gateway.live_messages()) == 1  # rien de reposté


async def test_an_invite_never_given_the_role_is_still_kicked_at_expiry(votes, gateway, clock):
    gateway.role_changes_fail = True
    await votes.open(VoteKind.INVITE, NEWCOMER)

    clock.advance(DAY)
    await votes.expire_due()

    assert gateway.kicked == [NEWCOMER]


async def test_the_tick_does_not_give_back_an_invite_role_removed_by_hand(votes, gateway, clock):
    await votes.open(VoteKind.INVITE, NEWCOMER)
    await gateway.remove_role(NEWCOMER, INVITE, "admission manuelle")

    await votes.reconcile()

    assert INVITE not in gateway.roles_of(NEWCOMER)
    assert len(gateway.live_messages()) == 1


async def test_a_target_has_at_most_one_open_vote_per_policy(votes, gateway):
    first = await votes.open(VoteKind.INVITE, NEWCOMER)
    again = await votes.open(VoteKind.INVITE, NEWCOMER)

    assert again.id == first.id
    assert len(gateway.live_messages()) == 1


async def test_on_the_very_first_start_no_vote_is_opened_for_existing_members(make_votes, gateway, clock):
    gateway.add_member(300, joined_at=clock.now - DAY)  # sans rôle, déjà là avant le bot

    assert await make_votes().catch_up_arrivals(VoteKind.INVITE) == []

    assert gateway.live_messages() == []
    assert gateway.roles_of(300) == set()


async def test_arrivals_during_downtime_get_their_invite_vote_at_startup(make_votes, gateway, clock):
    gateway.add_member(300, joined_at=clock.now - DAY)  # arrivé avant le dernier heartbeat
    await make_votes().heartbeat()
    clock.advance(3600)  # bot arrêté une heure
    gateway.add_member(301, joined_at=clock.now - 1800)
    gateway.add_member(302, MEMBRE, joined_at=clock.now - 1800)  # admis à la main entre-temps
    gateway.add_member(303, INVITE, joined_at=clock.now - 1800)
    gateway.add_member(304, CONFIANCE, joined_at=clock.now - 1800)
    gateway.add_member(305, bot=True, joined_at=clock.now - 1800)

    opened = await make_votes().catch_up_arrivals(VoteKind.INVITE)

    assert [vote.target_id for vote in opened] == [301]
    assert INVITE in gateway.roles_of(301)
    [message] = gateway.live_messages()
    assert "<@301>" in message.content



async def test_an_approval_whose_role_change_fails_is_logged_as_a_failure(votes, gateway):
    vote = await votes.open(VoteKind.INVITE, NEWCOMER)
    gateway.role_changes_fail = True  # ex. Forbidden

    await votes.approve(vote.id, ALICE)

    [log] = gateway.logs
    assert "approuvée" not in log
    assert "Membre" in log and "impossible" in log
    assert f"<@{NEWCOMER}>" in log and f"<@{ALICE}>" in log


async def test_an_approval_for_an_invite_who_left_is_logged_as_a_failure(votes, gateway):
    vote = await votes.open(VoteKind.INVITE, NEWCOMER)
    del gateway.roster[NEWCOMER]

    await votes.approve(vote.id, ALICE)

    [log] = gateway.logs
    assert "approuvée" not in log
    assert "impossible" in log


async def test_a_ballot_that_loses_the_quorum_race_is_told_it_was_recorded(votes, gateway):
    import asyncio

    vote = await votes.open(VoteKind.INVITE, NEWCOMER)
    both_checked = asyncio.Barrier(2)
    lookup = gateway.member

    async def member(member_id):  # ALICE et BOB cliquent au même instant
        info = await lookup(member_id)
        if member_id in (ALICE, BOB):
            await both_checked.wait()
        return info

    gateway.member = member
    replies = await asyncio.gather(votes.approve(vote.id, ALICE), votes.approve(vote.id, BOB))

    assert MEMBRE in gateway.roles_of(NEWCOMER)
    assert len(gateway.logs) == 1
    assert sum("quorum atteint" in reply for reply in replies) == 1
    late = next(reply for reply in replies if "quorum atteint" not in reply)
    assert "terminé" not in late
    assert "enregistré" in late and "déjà" in late


async def test_an_incomplete_vote_is_retried_at_most_every_few_minutes(votes, gateway, clock):
    gateway.validation_channel_available = False
    await votes.open(VoteKind.INVITE, NEWCOMER)
    failures = len(gateway.logs)

    clock.advance(RETRY_SECONDS - 1)
    await votes.reconcile()
    assert len(gateway.logs) == failures

    clock.advance(1)
    await votes.reconcile()
    assert len(gateway.logs) == 2 * failures

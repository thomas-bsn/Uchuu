"""Secret Santa : tirage, exclusions, MP en échec, retry, anti double tirage, confidentialité,
enregistrement des commandes et du /help. Aucun appel Discord réel : tout passe par des fakes."""
import logging
import sqlite3
from dataclasses import dataclass, field
from types import SimpleNamespace

import discord
import pytest
from discord.ext import commands

import services.secret_santa as santa
from services.secret_santa import (
    Participant,
    SecretSantaStore,
    collect_participants,
    deliver_pending,
    derangement,
    parse_message_url,
)

GUILD_ID = 1000
ORGANIZER_ID = 1
YEAR = 2026


@pytest.fixture(autouse=True)
def no_send_delay(monkeypatch):
    monkeypatch.setattr(santa, "SEND_DELAY_SECONDS", 0)


@pytest.fixture(autouse=True)
def fixed_year(monkeypatch):
    class _Now:
        @staticmethod
        def now():
            return SimpleNamespace(year=YEAR)

    import cogs.secret_santa as cog_module
    monkeypatch.setattr(cog_module, "datetime", _Now)


# =========================
# FAKES
# =========================

def http_error(cls):
    return cls(SimpleNamespace(status=403 if cls is discord.Forbidden else 500, reason="x"), "boom")


@dataclass(eq=False)
class FakeUser:
    id: int
    name: str = ""
    bot: bool = False
    dms: list = field(default_factory=list)
    failure: type | None = None

    def __post_init__(self):
        self.name = self.name or f"user{self.id}"

    @property
    def display_name(self):
        return self.name

    @property
    def mention(self):
        return f"<@{self.id}>"

    async def send(self, content):
        if self.failure:
            raise http_error(self.failure)
        self.dms.append(content)


class FakeReaction:
    def __init__(self, emoji, users):
        self.emoji = emoji
        self._users = users

    async def users(self):
        for user in self._users:
            yield user


class FakeGuild:
    def __init__(self, members, left=()):
        self.id = GUILD_ID
        self.me = SimpleNamespace()
        self.members = {m.id: m for m in members}
        self.left = set(left)
        self.channel = None

    def get_member(self, user_id):
        return self.members.get(user_id)

    async def fetch_member(self, user_id):
        if user_id in self.members:
            return self.members[user_id]
        raise discord.NotFound(SimpleNamespace(status=404, reason="x"), "unknown member")

    def get_channel_or_thread(self, channel_id):
        return self.channel if self.channel and self.channel.id == channel_id else None


class FakeChannel:
    id = 2000
    mention = "<#2000>"

    def __init__(self, message, can_read=True):
        self.message = message
        self.can_read = can_read

    def permissions_for(self, _me):
        return SimpleNamespace(view_channel=self.can_read, read_message_history=self.can_read)

    async def fetch_message(self, message_id):
        return self.message


class FakeInteraction:
    """Enregistre tout ce que l'utilisateur verrait, avec le flag éphémère."""

    def __init__(self, guild, user, manage_guild=True):
        self.guild = guild
        self.user = user
        self.permissions = SimpleNamespace(manage_guild=manage_guild)
        self.outputs: list[tuple[str, bool]] = []  # (texte, éphémère)
        self.views: list = []
        outer = self

        class Response:
            async def send_message(self, content=None, *, ephemeral=False, view=None, **kw):
                outer.record(content, ephemeral, view)

            async def defer(self, *, ephemeral=False, thinking=False):
                pass

            async def edit_message(self, *, content=None, view=None):
                outer.record(content, True, None)

        class Followup:
            async def send(self, content=None, *, ephemeral=False, view=None, **kw):
                outer.record(content, ephemeral, view)

        self.response = Response()
        self.followup = Followup()

    def record(self, content, ephemeral, view):
        self.outputs.append((content, ephemeral))
        if view is not None:
            self.views.append(view)

    async def edit_original_response(self, *, content=None, **kw):
        self.outputs.append((content, True))

    @property
    def texts(self):
        return [text for text, _ in self.outputs]


def make_users(n):
    return [FakeUser(ORGANIZER_ID + i, name=f"Pseudo{i}") for i in range(n)]


@pytest.fixture
async def bot(bot_settings):
    instance = commands.Bot(command_prefix="$$", intents=discord.Intents.none())
    instance.settings = bot_settings
    await instance.load_extension("cogs.secret_santa")
    await instance.load_extension("commands.helps")
    instance.users_by_id = {}

    async def fetch_user(user_id):
        return instance.users_by_id[user_id]

    instance.fetch_user = fetch_user
    yield instance
    await instance.close()


@pytest.fixture
def cog(bot):
    return bot.get_cog("SecretSanta")


def setup_server(bot, users, *, emoji="🎅", extra_reactors=(), can_read=True):
    """Serveur avec un message d'inscription ; renvoie (guild, url)."""
    guild = FakeGuild(users)
    reaction = FakeReaction(emoji, list(users) + list(extra_reactors))
    guild.channel = FakeChannel(SimpleNamespace(reactions=[reaction]), can_read=can_read)
    bot.users_by_id.update({u.id: u for u in users})
    return guild, f"https://discord.com/channels/{GUILD_ID}/2000/3000"


async def prepare_draw(cog, bot, users, **kw):
    """Joue /secret-santa draw et renvoie (interaction, vue de confirmation)."""
    guild, url = setup_server(bot, users, **kw)
    interaction = FakeInteraction(guild, users[0])
    await cog.draw.callback(cog, interaction, url, "🎅")
    return interaction, (interaction.views[0] if interaction.views else None)


async def full_draw(cog, bot, users, **kw):
    interaction, view = await prepare_draw(cog, bot, users, **kw)
    await view.confirm.callback(interaction)
    return interaction


def received(users):
    """{donneur: nom du destinataire} d'après les MP reçus (lecture dans le test uniquement)."""
    out = {}
    for user in users:
        for dm in user.dms:
            if "pour offrir un cadeau à" in dm:
                out[user.id] = dm.split("**@")[1].split("**")[0]
    return out


# =========================
# ALGORITHME
# =========================

def test_ten_participants_give_ten_unique_assignments():
    ids = list(range(1, 11))

    result = derangement(ids)

    assert set(result) == set(ids)
    assert sorted(result.values()) == ids  # chacun reçoit exactement un cadeau


def test_nobody_draws_themselves_over_many_draws():
    for _ in range(500):
        for n in (2, 3, 5, 10):
            result = derangement(list(range(n)))
            assert all(giver != receiver for giver, receiver in result.items())


def test_two_participants_swap():
    assert derangement([5, 9]) == {5: 9, 9: 5}


def test_derangement_needs_two_distinct_participants():
    with pytest.raises(ValueError):
        derangement([1])
    with pytest.raises(ValueError):
        derangement([1, 1])


def test_all_derangements_are_reachable():
    # Sattolo ne produirait que les 2 cycles à 3 ; il y a bien 2 dérangements de 3 éléments,
    # mais pour 4 il y en a 9 (6 cycles + 3 doubles échanges) : tous doivent sortir.
    seen = {tuple(sorted(derangement([0, 1, 2, 3]).items())) for _ in range(1000)}
    assert len(seen) == 9


# =========================
# PARTICIPANTS
# =========================

def test_message_url_parsing():
    assert parse_message_url("https://discord.com/channels/1/2/3") == (1, 2, 3)
    assert parse_message_url(" https://ptb.discord.com/channels/1/2/3 ") == (1, 2, 3)
    assert parse_message_url("https://evil.example/channels/1/2/3") is None
    assert parse_message_url("n'importe quoi") is None


async def test_bots_and_duplicates_are_excluded():
    humans = make_users(3)
    bot_user = FakeUser(99, bot=True)
    guild = FakeGuild(humans + [bot_user])
    reaction = FakeReaction("🎅", [humans[0], bot_user, humans[1], humans[0], humans[2], humans[1]])
    message = SimpleNamespace(reactions=[reaction, FakeReaction("🎄", [FakeUser(50)])])

    participants, skipped, found = await collect_participants(message, guild, "🎅")

    assert found
    assert sorted(p.id for p in participants) == [u.id for u in humans]
    assert skipped == 0


async def test_all_reactors_are_read_beyond_one_page():
    users = [FakeUser(i, name=f"u{i}") for i in range(1, 251)]
    guild = FakeGuild(users)
    message = SimpleNamespace(reactions=[FakeReaction("🎅", users)])

    participants, _, _ = await collect_participants(message, guild, "🎅")

    assert len(participants) == 250


async def test_members_who_left_are_skipped_and_counted():
    present, gone = make_users(2)
    guild = FakeGuild([present])
    message = SimpleNamespace(reactions=[FakeReaction("🎅", [present, gone])])

    participants, skipped, _ = await collect_participants(message, guild, "🎅")

    assert [p.id for p in participants] == [present.id]
    assert skipped == 1


async def test_emoji_variation_selector_and_missing_emoji():
    users = make_users(2)
    guild = FakeGuild(users)
    message = SimpleNamespace(reactions=[FakeReaction("❤️", users)])

    assert (await collect_participants(message, guild, "❤"))[2] is True
    assert (await collect_participants(message, guild, "🎅"))[2] is False


# =========================
# /secret-santa draw : workflow et confirmation
# =========================

async def test_draw_command_lists_participants_ephemerally_and_does_not_draw(cog, bot):
    users = make_users(4)

    interaction, view = await prepare_draw(cog, bot, users, extra_reactors=[FakeUser(99, bot=True)])

    text, ephemeral = interaction.outputs[-1]
    assert ephemeral and "4 participants" in text
    assert all(u.name in text for u in users)
    assert view is not None
    assert all(not u.dms for u in users)  # aucun MP avant confirmation
    assert not cog.store.draw_exists(GUILD_ID, YEAR)


async def test_draw_needs_two_participants(cog, bot):
    interaction, view = await prepare_draw(cog, bot, make_users(1))

    assert view is None and "au moins 2" in interaction.texts[-1]


async def test_cancel_sends_nothing(cog, bot):
    users = make_users(3)
    interaction, view = await prepare_draw(cog, bot, users)

    await view.cancel.callback(interaction)

    assert all(not u.dms for u in users)
    assert not cog.store.draw_exists(GUILD_ID, YEAR)


async def test_confirmation_is_reserved_to_the_organizer(cog, bot):
    users = make_users(3)
    _, view = await prepare_draw(cog, bot, users)
    intruder = FakeInteraction(FakeGuild([]), FakeUser(777))

    assert await view.interaction_check(intruder) is False
    assert await view.interaction_check(FakeInteraction(FakeGuild([]), users[0])) is True


async def test_draw_requires_permission_and_bot_access(cog, bot):
    users = make_users(3)
    guild, url = setup_server(bot, users, can_read=False)

    denied = FakeInteraction(guild, users[0], manage_guild=False)
    await cog.draw.callback(cog, denied, url, "🎅")
    no_access = FakeInteraction(guild, users[0])
    await cog.draw.callback(cog, no_access, url, "🎅")

    assert "Gérer le serveur" in denied.texts[-1]
    assert "Lire l'historique" in no_access.texts[-1]
    assert not no_access.views


async def test_confirmed_draw_sends_every_dm_with_the_right_format(cog, bot):
    users = make_users(10)

    interaction = await full_draw(cog, bot, users)

    gifts = received(users)
    assert len(gifts) == 10
    assert sorted(gifts.values()) == sorted(u.name for u in users)  # un cadeau reçu chacun
    assert all(gifts[u.id] != u.name for u in users)  # personne ne se tire
    assert all(f"SECRET SANTA {YEAR}" in u.dms[0] and f"Salut {u.name} !" in u.dms[0] and "Garde son identité secrète" in u.dms[0] for u in users)
    assert "10/10" in interaction.texts[-1]


async def test_double_execution_is_refused(cog, bot):
    users = make_users(4)
    first = await full_draw(cog, bot, users)
    dms_after_first = [len(u.dms) for u in users]
    assignments_after_first = received(users)

    second_interaction, second_view = await prepare_draw(cog, bot, users)

    assert second_view is None and "existe déjà" in second_interaction.texts[-1]
    # Même en contournant la vérification amont (deux confirmations simultanées) :
    text = await cog.execute_draw(GUILD_ID, ORGANIZER_ID, [Participant(u.id, u.name) for u in users])
    assert "existe déjà" in text
    assert [len(u.dms) for u in users] == dms_after_first
    assert received(users) == assignments_after_first
    assert "4/4" in first.texts[-1]


async def test_double_click_on_confirm_draws_once(cog, bot):
    users = make_users(3)
    interaction, view = await prepare_draw(cog, bot, users)

    await view.confirm.callback(interaction)
    await view.confirm.callback(interaction)

    assert [len(u.dms) for u in users] == [1, 1, 1]


# =========================
# ÉCHEC DE MP ET RETRY
# =========================

async def test_failed_dm_keeps_assignments_and_never_redraws(cog, bot):
    users = make_users(5)
    users[2].failure = discord.Forbidden

    interaction = await full_draw(cog, bot, users)

    result = interaction.texts[-1]
    assert "4/5" in result and users[2].name in result and "MP fermés" in result
    assert len(received(users)) == 4
    sent, waiting = cog.store.progress(GUILD_ID, YEAR)
    assert sent == 4 and [w[0] for w in waiting] == [users[2].id]
    assert cog.store.draw_exists(GUILD_ID, YEAR)


async def test_retry_resends_only_failed_dms_without_new_draw(cog, bot):
    users = make_users(5)
    users[2].failure = discord.Forbidden
    await full_draw(cog, bot, users)
    secret_row = sqlite3.connect(cog.store.db_path).execute(
        "SELECT recipient_id, recipient_name FROM secret_santa_assignments WHERE giver_id = ?", (users[2].id,)
    ).fetchone()
    before = {u.id: list(u.dms) for u in users}
    users[2].failure = None  # l'utilisateur a rouvert ses MP

    retry = FakeInteraction(FakeGuild(users), users[0])
    await cog.retry.callback(cog, retry)

    assert "1/1" in retry.texts[-1]
    assert users[2].dms and f"**@{secret_row[1]}**" in users[2].dms[0]  # l'attribution d'origine
    assert all(u.dms == before[u.id] for u in users if u is not users[2])  # personne d'autre re-contacté
    assert cog.store.progress(GUILD_ID, YEAR) == (5, [])

    again = FakeInteraction(FakeGuild(users), users[0])
    await cog.retry.callback(cog, again)
    assert "déjà été envoyés" in again.texts[-1] and len(users[2].dms) == 1


async def test_retry_is_reserved_to_the_organizer(cog, bot):
    users = make_users(3)
    users[1].failure = discord.HTTPException
    await full_draw(cog, bot, users)
    users[1].failure = None

    other = FakeInteraction(FakeGuild(users), users[2])  # admin, mais pas l'organisateur
    await cog.retry.callback(cog, other)
    no_perm = FakeInteraction(FakeGuild(users), users[0], manage_guild=False)
    await cog.retry.callback(cog, no_perm)

    assert "organisateur" in other.texts[-1]
    assert "Gérer le serveur" in no_perm.texts[-1]
    assert not users[1].dms


async def test_deliver_pending_survives_unknown_user(cog, bot):
    users = make_users(3)
    await full_draw(cog, bot, users)
    # un MP en attente dont le compte n'existe plus ne bloque pas les autres
    store = cog.store
    with store._conn() as conn:
        conn.execute("UPDATE secret_santa_assignments SET sent_at = NULL, recipient_id = 5, recipient_name = 'x'")

    async def resolve(user_id):
        if user_id == users[0].id:
            raise discord.NotFound(SimpleNamespace(status=404, reason="x"), "gone")
        return users[user_id - ORGANIZER_ID]

    report = await deliver_pending(store, resolve, GUILD_ID, YEAR)

    assert report.sent == 2 and [f[0] for f in report.failed] == [users[0].id]


# =========================
# CONFIDENTIALITÉ
# =========================

async def test_assignments_never_leak_in_responses_logs_or_database(cog, bot, caplog):
    users = make_users(10)
    users[4].failure = discord.Forbidden
    caplog.set_level(logging.DEBUG)

    draw = await full_draw(cog, bot, users)
    status = FakeInteraction(FakeGuild(users), users[0])
    await cog.status.callback(cog, status)
    failing_recipient = sqlite3.connect(cog.store.db_path).execute(
        "SELECT recipient_name FROM secret_santa_assignments WHERE giver_id = ?", (users[4].id,)
    ).fetchone()[0]

    for text, ephemeral in draw.outputs + status.outputs:
        assert ephemeral
        assert "pour offrir un cadeau" not in text
    final = draw.texts[-1] + status.texts[-1]
    assert users[4].name in final and failing_recipient not in final.replace(users[4].name, "")
    assert "pour offrir un cadeau" not in caplog.text
    assert failing_recipient not in caplog.text.replace(users[4].name, "")

    # En base : seules les attributions des MP en échec subsistent
    rows = sqlite3.connect(cog.store.db_path).execute(
        "SELECT giver_id, recipient_id FROM secret_santa_assignments WHERE recipient_id IS NOT NULL"
    ).fetchall()
    assert [r[0] for r in rows] == [users[4].id]


async def test_status_without_draw_and_with_progress(cog, bot):
    users = make_users(3)
    before = FakeInteraction(FakeGuild(users), users[0])
    await cog.status.callback(cog, before)
    await full_draw(cog, bot, users)
    after = FakeInteraction(FakeGuild(users), users[0])
    await cog.status.callback(cog, after)

    assert "Aucun tirage" in before.texts[-1]
    assert "3/3" in after.texts[-1]
    assert all(ephemeral for _, ephemeral in after.outputs)


# =========================
# /secret-santa test
# =========================

async def test_test_command_sends_the_test_dm_and_changes_no_state(cog, bot):
    target = FakeUser(42, name="Cible")
    interaction = FakeInteraction(FakeGuild([target]), FakeUser(1))

    await cog.test.callback(cog, interaction, target)

    assert target.dms == [santa.TEST_DM]
    assert "accepté" in interaction.texts[-1] and interaction.outputs[-1][1]
    assert not cog.store.draw_exists(GUILD_ID, YEAR)
    assert cog.store.latest_draw(GUILD_ID) is None


async def test_test_command_defaults_to_the_caller(cog):
    caller = FakeUser(1, name="Moi")
    interaction = FakeInteraction(FakeGuild([caller]), caller)

    await cog.test.callback(cog, interaction, None)

    assert caller.dms == [santa.TEST_DM]


@pytest.mark.parametrize("failure, expected", [(discord.Forbidden, "MP fermés"), (discord.HTTPException, "erreur Discord")])
async def test_test_command_reports_explicit_dm_error(cog, failure, expected):
    target = FakeUser(42, failure=failure)
    interaction = FakeInteraction(FakeGuild([target]), FakeUser(1))

    await cog.test.callback(cog, interaction, target)

    assert "❌" in interaction.texts[-1] and expected in interaction.texts[-1]


async def test_test_command_is_restricted(cog):
    target = FakeUser(42)
    interaction = FakeInteraction(FakeGuild([target]), FakeUser(1), manage_guild=False)

    await cog.test.callback(cog, interaction, target)

    assert not target.dms and "Gérer le serveur" in interaction.texts[-1]


# =========================
# ENREGISTREMENT ET /help
# =========================

def test_commands_registered_as_guild_only_group(bot):
    group = next(c for c in bot.tree.get_commands() if c.name == "secret-santa")

    assert {c.name for c in group.commands} == {"test", "draw", "status", "retry"}
    assert group.guild_only
    assert [p.name for p in group.get_command("draw").parameters] == ["message_url", "emoji"]
    assert [p.name for p in group.get_command("test").parameters] == ["user"]


class FakeCtx:
    def __init__(self):
        self.sent = []

    async def send(self, content):
        self.sent.append(content)


async def test_help_lists_secret_santa_and_details_it(bot):
    helper = bot.get_cog("Help")

    overview = FakeCtx()
    await helper.help_command.callback(helper, overview)
    detail = FakeCtx()
    await helper.help_command.callback(helper, detail, "secret-santa")

    listing = "\n".join(overview.sent)
    assert "/secret-santa draw" in listing and "/secret-santa test" in listing
    text = "\n".join(detail.sent)
    for expected in ("/secret-santa test", "/secret-santa draw <message_url> <emoji>", "/secret-santa status",
                     "/secret-santa retry", "Exemple", "Permission", "requis", "optionnel"):
        assert expected in text
    assert all(len(chunk) <= 2000 for chunk in overview.sent + detail.sent)


async def test_help_unknown_command_names_it(bot):
    helper = bot.get_cog("Help")
    ctx = FakeCtx()

    await helper.help_command.callback(helper, ctx, "nimportequoi")

    assert "`nimportequoi` n'existe pas" in ctx.sent[0]


def test_secret_santa_extension_is_loaded_at_startup():
    from main import EXTENSIONS

    assert "cogs.secret_santa" in EXTENSIONS


# =========================
# PERSISTANCE
# =========================

def test_state_survives_restart_and_draw_stays_unique(shameless_db_path):
    people = [Participant(i, f"p{i}") for i in range(1, 5)]
    first = SecretSantaStore(str(shameless_db_path))
    assert first.create_draw(GUILD_ID, YEAR, 1, people, derangement([p.id for p in people]))

    restarted = SecretSantaStore(str(shameless_db_path))

    assert restarted.draw_exists(GUILD_ID, YEAR)
    assert len(restarted.pending(GUILD_ID, YEAR)) == 4
    assert not restarted.create_draw(GUILD_ID, YEAR, 2, people, derangement([p.id for p in people]))
    assert restarted.latest_draw(GUILD_ID) == (YEAR, 1)  # l'organisateur d'origine est conservé
    assert (shameless_db_path.stat().st_mode & 0o077) == 0

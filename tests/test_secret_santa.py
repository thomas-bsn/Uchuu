"""Secret Santa : tirage, exclusions, MP en échec, retry, anti double tirage, confidentialité,
enregistrement des commandes et du /help. Aucun appel Discord réel : tout passe par des fakes."""
import logging
import sqlite3
import sys
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
    """Clic sur un bouton : enregistre ce que l'utilisateur verrait."""

    def __init__(self, guild, user):
        self.guild = guild
        self.user = user
        self.outputs: list[tuple[str, bool]] = []  # (texte, éphémère)
        outer = self

        class Response:
            async def send_message(self, content=None, *, ephemeral=False, **kw):
                outer.outputs.append((content, ephemeral))

            async def edit_message(self, *, content=None, view=None):
                outer.outputs.append((content, True))

        self.response = Response()

    async def edit_original_response(self, *, content=None, **kw):
        self.outputs.append((content, True))

    @property
    def texts(self):
        return [text for text, _ in self.outputs]


class FakeAuthor:
    """ctx.author : ses MP vont dans ctx.outputs (pas dans user.dms, réservé aux MP de tirage)."""

    def __init__(self, ctx, user, authorized):
        self._ctx = ctx
        self._user = user
        self.id = user.id if authorized else 9999  # 9999 : hors de la liste des organisateurs

    def __getattr__(self, name):
        return getattr(self._user, name)

    async def send(self, content, view=None, **kw):
        if self._ctx.dm_closed:
            raise http_error(discord.Forbidden)
        self._ctx.record("dm", content, view)


class FakeCtx:
    """Contexte d'une commande à préfixe : outputs = [(\"channel\"|\"dm\", texte)]."""

    prefix = "$$"

    def __init__(self, guild, user, authorized=True, dm_closed=False):
        self.guild = guild
        self.dm_closed = dm_closed
        self.outputs: list[tuple[str, str]] = []
        self.views: list = []
        self.author = FakeAuthor(self, user, authorized)

    def record(self, where, content, view=None):
        self.outputs.append((where, content))
        if view is not None:
            self.views.append(view)

    async def send(self, content=None, **kw):
        self.record("channel", content)

    def texts_in(self, where):
        return [text for w, text in self.outputs if w == where]

    @property
    def texts(self):
        return [text for _, text in self.outputs]


def make_users(n):
    return [FakeUser(ORGANIZER_ID + i, name=f"Pseudo{i}") for i in range(n)]


@pytest.fixture
async def bot(bot_settings, monkeypatch):
    instance = commands.Bot(command_prefix="$$", intents=discord.Intents.none())
    instance.settings = bot_settings
    await instance.load_extension("cogs.secret_santa")
    # Le module est rechargé à chaque test (décharger l'extension le retire de sys.modules) :
    # on patche celui que le cog utilise réellement.
    cog_module = sys.modules["cogs.secret_santa"]
    monkeypatch.setattr(cog_module, "ORGANIZER_IDS", frozenset(range(1, 500)))
    monkeypatch.setattr(cog_module, "datetime", SimpleNamespace(now=lambda: SimpleNamespace(year=YEAR)))
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
    """Joue `$$secret-santa draw` et renvoie (ctx, vue de confirmation)."""
    guild, url = setup_server(bot, users, **kw)
    ctx = FakeCtx(guild, users[0])
    await cog.draw.callback(cog, ctx, url, "🎅")
    return ctx, (ctx.views[0] if ctx.views else None)


async def full_draw(cog, bot, users, **kw):
    """Tirage confirmé ; renvoie l'interaction du clic (ce que voit l'organisateur à la fin)."""
    ctx, view = await prepare_draw(cog, bot, users, **kw)
    interaction = FakeInteraction(ctx.guild, users[0])
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
# $$secret-santa draw : workflow et confirmation
# =========================

async def test_draw_command_lists_participants_privately_and_does_not_draw(cog, bot):
    users = make_users(4)

    ctx, view = await prepare_draw(cog, bot, users, extra_reactors=[FakeUser(99, bot=True)])

    (listing,) = ctx.texts_in("dm")  # la liste part en MP à l'organisateur
    assert "4 participants" in listing and all(u.name in listing for u in users)
    assert not any(u.name in text for u in users for text in ctx.texts_in("channel"))  # pas dans le salon
    assert view is not None
    assert all(not u.dms for u in users)  # aucun MP de tirage avant confirmation
    assert not cog.store.draw_exists(GUILD_ID, YEAR)


async def test_draw_needs_two_participants(cog, bot):
    ctx, view = await prepare_draw(cog, bot, make_users(1))

    assert view is None and "au moins 2" in ctx.texts[-1]


async def test_draw_with_closed_dms_explains_and_draws_nothing(cog, bot):
    users = make_users(3)
    guild, url = setup_server(bot, users)
    ctx = FakeCtx(guild, users[0], dm_closed=True)

    await cog.draw.callback(cog, ctx, url, "🎅")

    assert "Ouvre tes MP" in ctx.texts[-1] and not ctx.views
    assert not cog.store.draw_exists(GUILD_ID, YEAR)


async def test_cancel_sends_nothing(cog, bot):
    users = make_users(3)
    ctx, view = await prepare_draw(cog, bot, users)

    await view.cancel.callback(FakeInteraction(ctx.guild, users[0]))

    assert all(not u.dms for u in users)
    assert not cog.store.draw_exists(GUILD_ID, YEAR)


async def test_confirmation_is_reserved_to_the_organizer(cog, bot):
    users = make_users(3)
    _, view = await prepare_draw(cog, bot, users)

    assert await view.interaction_check(FakeInteraction(FakeGuild([]), FakeUser(777))) is False
    assert await view.interaction_check(FakeInteraction(FakeGuild([]), users[0])) is True


async def test_draw_requires_permission_and_bot_access(cog, bot):
    users = make_users(3)
    guild, url = setup_server(bot, users, can_read=False)

    denied = FakeCtx(guild, users[0], authorized=False)
    await cog.draw.callback(cog, denied, url, "🎅")
    no_access = FakeCtx(guild, users[0])
    await cog.draw.callback(cog, no_access, url, "🎅")

    assert "pas autorisé" in denied.texts[-1]
    assert "Lire l'historique" in no_access.texts[-1]
    assert not no_access.views


async def test_draw_rejects_bad_or_foreign_links(cog, bot):
    users = make_users(3)
    guild, _ = setup_server(bot, users)
    bad = FakeCtx(guild, users[0])
    foreign = FakeCtx(guild, users[0])

    await cog.draw.callback(cog, bad, "pas un lien", "🎅")
    await cog.draw.callback(cog, foreign, "https://discord.com/channels/999/2000/3000", "🎅")

    assert "Lien invalide" in bad.texts[-1]
    assert "pas sur ce serveur" in foreign.texts[-1]


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

    second_ctx, second_view = await prepare_draw(cog, bot, users)

    assert second_view is None and "existe déjà" in second_ctx.texts[-1]
    # Même en contournant la vérification amont (deux confirmations simultanées) :
    text = await cog.execute_draw(GUILD_ID, ORGANIZER_ID, [Participant(u.id, u.name) for u in users])
    assert "existe déjà" in text
    assert [len(u.dms) for u in users] == dms_after_first
    assert received(users) == assignments_after_first
    assert "4/4" in first.texts[-1]


async def test_double_click_on_confirm_draws_once(cog, bot):
    users = make_users(3)
    ctx, view = await prepare_draw(cog, bot, users)
    interaction = FakeInteraction(ctx.guild, users[0])

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
    assert "$$secret-santa retry" in result  # le préfixe du bot, pas un slash
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

    retry = FakeCtx(FakeGuild(users), users[0])
    await cog.retry.callback(cog, retry)

    assert "1/1" in retry.texts_in("dm")[-1]
    assert users[2].dms and f"**@{secret_row[1]}**" in users[2].dms[0]  # l'attribution d'origine
    assert all(u.dms == before[u.id] for u in users if u is not users[2])  # personne d'autre re-contacté
    assert cog.store.progress(GUILD_ID, YEAR) == (5, [])

    again = FakeCtx(FakeGuild(users), users[0])
    await cog.retry.callback(cog, again)
    assert "déjà été envoyés" in again.texts[-1] and len(users[2].dms) == 1


async def test_retry_is_reserved_to_the_organizer(cog, bot):
    users = make_users(3)
    users[1].failure = discord.HTTPException
    await full_draw(cog, bot, users)
    users[1].failure = None

    other = FakeCtx(FakeGuild(users), users[2])  # admin, mais pas l'organisateur
    await cog.retry.callback(cog, other)
    no_perm = FakeCtx(FakeGuild(users), users[0], authorized=False)
    await cog.retry.callback(cog, no_perm)

    assert "organisateur" in other.texts[-1]
    assert "pas autorisé" in no_perm.texts[-1]
    assert not users[1].dms


async def test_deliver_pending_survives_unknown_user(cog, bot):
    users = make_users(3)
    await full_draw(cog, bot, users)
    # un MP en attente dont le compte n'existe plus ne bloque pas les autres
    with cog.store._conn() as conn:
        conn.execute("UPDATE secret_santa_assignments SET sent_at = NULL, recipient_id = 5, recipient_name = 'x'")

    async def resolve(user_id):
        if user_id == users[0].id:
            raise discord.NotFound(SimpleNamespace(status=404, reason="x"), "gone")
        return users[user_id - ORGANIZER_ID]

    report = await deliver_pending(cog.store, resolve, GUILD_ID, YEAR)

    assert report.sent == 2 and [f[0] for f in report.failed] == [users[0].id]


# =========================
# CONFIDENTIALITÉ
# =========================

async def test_assignments_never_leak_in_responses_logs_or_database(cog, bot, caplog):
    users = make_users(10)
    users[4].failure = discord.Forbidden
    caplog.set_level(logging.DEBUG)

    draw = await full_draw(cog, bot, users)
    status = FakeCtx(FakeGuild(users), users[0])
    await cog.status.callback(cog, status)
    failing_recipient = sqlite3.connect(cog.store.db_path).execute(
        "SELECT recipient_name FROM secret_santa_assignments WHERE giver_id = ?", (users[4].id,)
    ).fetchone()[0]

    for text in draw.texts + status.texts:
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
    before = FakeCtx(FakeGuild(users), users[0])
    await cog.status.callback(cog, before)
    await full_draw(cog, bot, users)
    after = FakeCtx(FakeGuild(users), users[0])
    await cog.status.callback(cog, after)

    assert "Aucun tirage" in before.texts[-1]
    assert "3/3" in after.texts_in("dm")[-1]
    assert not any("3/3" in text for text in after.texts_in("channel"))  # le salon ne reçoit qu'un accusé


async def test_status_requires_permission(cog):
    ctx = FakeCtx(FakeGuild([]), FakeUser(1), authorized=False)

    await cog.status.callback(cog, ctx)

    assert "pas autorisé" in ctx.texts[-1] and not ctx.texts_in("dm")


# =========================
# $$secret-santa test
# =========================

async def test_test_command_sends_the_test_dm_and_changes_no_state(cog):
    target = FakeUser(42, name="Cible")
    ctx = FakeCtx(FakeGuild([target]), FakeUser(1))

    await cog.test.callback(cog, ctx, target)

    assert target.dms == [santa.TEST_DM]
    assert "accepté" in ctx.texts[-1]
    assert not cog.store.draw_exists(GUILD_ID, YEAR)
    assert cog.store.latest_draw(GUILD_ID) is None


async def test_test_command_defaults_to_the_caller(cog):
    ctx = FakeCtx(FakeGuild([]), FakeUser(1, name="Moi"))

    await cog.test.callback(cog, ctx, None)

    assert ctx.texts_in("dm") == [santa.TEST_DM]  # envoyé à celui qui a lancé la commande


@pytest.mark.parametrize("failure, expected", [(discord.Forbidden, "MP fermés"), (discord.HTTPException, "erreur Discord")])
async def test_test_command_reports_explicit_dm_error(cog, failure, expected):
    target = FakeUser(42, failure=failure)
    ctx = FakeCtx(FakeGuild([target]), FakeUser(1))

    await cog.test.callback(cog, ctx, target)

    assert "❌" in ctx.texts[-1] and expected in ctx.texts[-1]


async def test_test_command_is_restricted(cog):
    target = FakeUser(42)
    ctx = FakeCtx(FakeGuild([target]), FakeUser(1), authorized=False)

    await cog.test.callback(cog, ctx, target)

    assert not target.dms and "pas autorisé" in ctx.texts[-1]


# =========================
# $$secret-santa info (budget, dates) et on / off
# =========================

def infos_received(users):
    return {u.id: [dm for dm in u.dms if "Budget" in dm] for u in users}


async def run_info(cog, users, budget="20€ maximum", user=None, confirm=True):
    ctx = FakeCtx(FakeGuild(users), user or users[0])
    await cog.info.callback(cog, ctx, budget=budget)
    if confirm and ctx.views:
        await ctx.views[0].confirm.callback(FakeInteraction(ctx.guild, users[0]))
    return ctx


async def test_info_previews_then_sends_to_every_participant_once(cog, bot):
    users = make_users(5)
    await full_draw(cog, bot, users)

    preview = await run_info(cog, users, confirm=False)

    (text,) = preview.texts_in("dm")  # l'aperçu part en MP à l'organisateur
    for expected in ("20€ maximum", "nuit du 24 au 25 décembre", "en main propre sur place ou par la poste", "dimanche 20 décembre"):
        assert expected in text
    assert not any(infos_received(users).values())  # rien n'est parti avant confirmation

    await run_info(cog, users)

    assert all(len(v) == 1 for v in infos_received(users).values())
    again = await run_info(cog, users)
    assert "déjà reçu" in again.texts[-1]
    assert all(len(v) == 1 for v in infos_received(users).values())  # jamais deux fois


async def test_info_retry_only_contacts_participants_who_failed(cog, bot):
    users = make_users(4)
    await full_draw(cog, bot, users)
    users[2].failure = discord.Forbidden
    await run_info(cog, users)
    users[2].failure = None
    first = {u.id: len(v) for u, v in zip(users, infos_received(users).values())}

    await run_info(cog, users)

    after = infos_received(users)
    assert [len(after[u.id]) for u in users] == [1, 1, 1, 1]
    assert first[users[2].id] == 0 and first[users[0].id] == 1


async def test_info_never_reveals_or_changes_assignments(cog, bot):
    users = make_users(4)
    await full_draw(cog, bot, users)
    gifts = received(users)

    await run_info(cog, users)

    assert received(users) == gifts
    assert all("pour offrir un cadeau" not in dm for u in users for dm in infos_received(users)[u.id])
    assert cog.store.progress(GUILD_ID, YEAR) == (4, [])


async def test_info_needs_a_draw_and_authorization(cog, bot):
    users = make_users(3)
    no_draw = await run_info(cog, users)
    await full_draw(cog, bot, users)
    stranger = await run_info(cog, users, user=users[1])  # autorisé : ok
    denied = FakeCtx(FakeGuild(users), users[0], authorized=False)
    await cog.info.callback(cog, denied, budget="10€")

    assert "Aucun tirage" in no_draw.texts[-1]
    assert stranger.views
    assert "pas autorisé" in denied.texts[-1]


async def test_off_blocks_every_command_and_on_restores_them(cog, bot):
    users = make_users(3)
    await full_draw(cog, bot, users)
    off = FakeCtx(FakeGuild(users), users[0])
    await cog.off.callback(cog, off)

    blocked = []
    for command, args in ((cog.test, (None,)), (cog.status, ()), (cog.retry, ())):
        ctx = FakeCtx(FakeGuild(users), users[0])
        await command.callback(cog, ctx, *args)
        blocked.append(ctx)
    draw_ctx = FakeCtx(*(setup_server(bot, users)[0], users[0]))
    await cog.draw.callback(cog, draw_ctx, "https://discord.com/channels/1000/2000/3000", "🎅")
    info_ctx = FakeCtx(FakeGuild(users), users[0])
    await cog.info.callback(cog, info_ctx, budget="20€")

    assert "désactivé" in off.texts[-1]
    assert all("désactivé" in ctx.texts[-1] for ctx in [*blocked, draw_ctx, info_ctx])
    assert not any(ctx.views or ctx.texts_in("dm") for ctx in [*blocked, draw_ctx, info_ctx])

    on = FakeCtx(FakeGuild(users), users[0])
    await cog.on.callback(cog, on)
    status = FakeCtx(FakeGuild(users), users[0])
    await cog.status.callback(cog, status)

    assert "réactivé" in on.texts[-1] and "3/3" in status.texts_in("dm")[-1]


async def test_off_and_on_are_restricted(cog):
    for command in (cog.off, cog.on):
        ctx = FakeCtx(FakeGuild([]), FakeUser(1), authorized=False)
        await command.callback(cog, ctx)
        assert "pas autorisé" in ctx.texts[-1]
    assert cog.store.is_enabled()


def test_disabled_state_survives_restart(shameless_db_path):
    store = SecretSantaStore(str(shameless_db_path))
    assert store.is_enabled()  # activé par défaut
    store.set_enabled(False)

    assert not SecretSantaStore(str(shameless_db_path)).is_enabled()


# =========================
# ENREGISTREMENT ET help
# =========================

def test_commands_registered_on_the_bot_prefix_group(bot):
    group = bot.get_command("secret-santa")

    assert {c.name for c in group.commands} == {"test", "draw", "status", "retry", "info", "on", "off"}
    assert not bot.tree.get_commands()  # plus aucune slash command
    assert list(bot.get_command("secret-santa draw").clean_params) == ["message_url", "emoji"]
    assert list(bot.get_command("secret-santa test").clean_params) == ["user"]


class FakeHelpCtx:
    def __init__(self):
        self.sent = []

    async def send(self, content):
        self.sent.append(content)


async def test_help_lists_secret_santa_and_details_it(bot):
    helper = bot.get_cog("Help")

    overview = FakeHelpCtx()
    await helper.help_command.callback(helper, overview)
    detail = FakeHelpCtx()
    await helper.help_command.callback(helper, detail, "secret-santa")

    assert "secret-santa" in "\n".join(overview.sent)
    text = "\n".join(detail.sent)
    for expected in ("secret-santa test", "secret-santa draw <message_url> <emoji>", "secret-santa status",
                     "secret-santa retry", "Exemple : `$$secret-santa draw", "Permission", "Paramètres"):
        assert expected in text
    assert all(len(chunk) <= 2000 for chunk in overview.sent + detail.sent)


async def test_help_detail_of_a_subcommand_and_unknown_command(bot):
    helper = bot.get_cog("Help")
    sub, unknown = FakeHelpCtx(), FakeHelpCtx()

    await helper.help_command.callback(helper, sub, "secret-santa", "retry")
    await helper.help_command.callback(helper, unknown, "nimportequoi")

    assert "Organisateur du tirage uniquement" in sub.sent[0]
    assert "`nimportequoi` n'existe pas" in unknown.sent[0]


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


def test_organizers_file_lists_only_valid_discord_ids():
    from cogs.secret_santa import load_organizer_ids

    ids = load_organizer_ids()

    assert ids and all(isinstance(i, int) and i > 10**16 for i in ids)

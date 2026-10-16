"""Bouton ✅ persistant : identifiant stable par vote, réenregistré au démarrage."""
import re

from views.vote_button import VoteButton


def test_the_approve_button_has_a_stable_custom_id_per_vote():
    button = VoteButton(42)

    assert button.custom_id == "vote:42:approve"
    assert VoteButton(42).custom_id == button.custom_id
    match = re.fullmatch(VoteButton.__discord_ui_compiled_template__, button.custom_id)
    assert int(match["vote_id"]) == 42


class _StartupBot:
    def __init__(self, settings):
        self.settings = settings
        self.cogs = []
        self.dynamic_items = []

    async def add_cog(self, cog):
        self.cogs.append(cog)

    def add_dynamic_items(self, *items):
        self.dynamic_items.extend(items)

    def get_guild(self, guild_id):
        return None


async def test_the_vote_extension_reregisters_the_button_at_startup(bot_settings):
    import cogs.votes

    bot = _StartupBot(bot_settings)
    await cogs.votes.setup(bot)

    assert VoteButton in bot.dynamic_items


async def test_the_discord_gateway_logs_missing_server_and_channels_without_crashing(bot_settings):
    from services.vote_gateway import DiscordVoteGateway, MessageRef
    from tests.fakes import FakeBot

    bot = FakeBot()
    logs = bot.add_guild(999).add_text_channel(bot_settings.ids.channel_logs_id)  # pas le bon serveur
    gateway = DiscordVoteGateway(bot, bot_settings)

    assert await gateway.member(100) is None
    assert await gateway.add_role(100, bot_settings.ids.role_invite_id, "test") is False
    assert await gateway.post_vote(1, "vote") is None
    await gateway.delete_vote(MessageRef(12345, 1))

    contents = [sent["content"] for sent in logs.sent]
    assert any(str(bot_settings.ids.guild_id) in c for c in contents)
    assert any(str(bot_settings.ids.channel_validation_id) in c for c in contents)
    assert any("12345" in c for c in contents)

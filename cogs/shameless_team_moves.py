from discord.ext import commands

from services.shameless_events import EVENT_TEAMS_FORMED, get_dispatcher
from services.shameless_team_moves import make_teams_formed_handler
from shameless_config import ShamelessSettings


class ShamelessTeamMovesCog(commands.Cog):
    """Branche le handler teams_formed (#4) sur le dispatcher webhook Shameless."""

    def __init__(self, bot, settings: ShamelessSettings):
        self.bot = bot
        self.settings = settings
        self._handler = None

    async def cog_load(self):
        self._handler = make_teams_formed_handler(self.bot, self.settings)
        get_dispatcher(self.bot).register(EVENT_TEAMS_FORMED, self._handler)

    async def cog_unload(self):
        get_dispatcher(self.bot).unregister(EVENT_TEAMS_FORMED, self._handler)


async def setup(bot):
    await bot.add_cog(ShamelessTeamMovesCog(bot, bot.settings.shameless))

from discord.ext import commands

from services.shameless_team_moves import register_team_moves, unregister_team_moves
from shameless_config import ShamelessSettings


class ShamelessTeamMovesCog(commands.Cog):
    """Branche le handler teams_formed (#4) sur le dispatcher webhook Shameless."""

    def __init__(self, bot, settings: ShamelessSettings):
        self.bot = bot
        self.settings = settings

    async def cog_load(self):
        register_team_moves(self.bot, self.settings)

    async def cog_unload(self):
        unregister_team_moves(self.bot)


async def setup(bot):
    await bot.add_cog(ShamelessTeamMovesCog(bot, ShamelessSettings.from_env()))

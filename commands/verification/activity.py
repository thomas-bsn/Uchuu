from datetime import datetime, timezone, timedelta
import discord

class ActivityTracker:
    def __init__(self, bot):
        self.bot = bot

    async def get_user_activity(self, member: discord.Member):
        #TODO: Voir exp avec MEE6
        return None

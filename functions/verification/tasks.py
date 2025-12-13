from discord.ext import tasks
from .config import GUILD_ID, ROLE_MEMBRE_ID
from .promotion import PromotionService

class TaskScheduler:
    def __init__(self, bot, store):
        self.bot = bot
        self.store = store
        self.promotion_service = PromotionService(bot, store)

    @tasks.loop(hours=24)  # Vérifie tous les 24h
    async def promote_trusted_members(self):
        guild = self.bot.get_guild(GUILD_ID)
        if guild is None:
            return
        
        for member in guild.members:
            if member.bot:
                continue  # Ignore les bots
            if member.guild.get_role(ROLE_MEMBRE_ID) in member.roles:
                result = await self.promotion_service.check_and_promote(member)
                if result:
                    print(result)  # Log ou envoi de message pour la promotion

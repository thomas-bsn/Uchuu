from discord.ext import tasks
from datetime import datetime, timezone

class ExpiryScheduler:
    def __init__(self, service):
        self.service = service
        self.loop.start()

    @tasks.loop(seconds=5)
    async def loop(self):
        now = int(datetime.now(timezone.utc).timestamp())
        await self.service.process_expirations(now)

    @loop.before_loop
    async def before_loop(self):
        """Attend que le bot soit prêt avant de commencer le processus."""
        await self.service.bot.wait_until_ready()

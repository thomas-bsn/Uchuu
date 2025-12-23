import asyncio
import threading
import discord
from discord.ext import commands
import uvicorn

import runtime_config as rt
import discord_config as dc
from internal_api import create_internal_api

class MyBot(commands.Bot):
    async def setup_hook(self):
        # Ici on est dans le bon contexte async, donc OK
        self.runtime_loop = asyncio.get_running_loop()

        # charge tes extensions ici plutôt que on_ready
        for ext in dc.EXTENSIONS:
            await self.load_extension(ext)

bot = MyBot(command_prefix=rt.BOT_PREFIX, intents=discord.Intents.all())

@bot.event
async def on_ready():
    print(f"{bot.user.name} est prêt.")
    await bot.change_presence(activity=discord.Game(rt.BOT_STATUS))

def run_internal_api():
    app = create_internal_api(bot)
    config = uvicorn.Config(
        app,
        host=rt.INTERNAL_API_HOST,   # 127.0.0.1
        port=rt.INTERNAL_API_PORT,   # 9000
        log_level="info",
    )
    uvicorn.Server(config).run()

if __name__ == "__main__":
    threading.Thread(target=run_internal_api, daemon=True).start()
    bot.run(rt.DISCORD_TOKEN)

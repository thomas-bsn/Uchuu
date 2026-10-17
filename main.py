import asyncio
import os
import sys
import threading

import discord
import uvicorn
from discord.ext import commands
from dotenv import load_dotenv

from bot_settings import BotSettings, SettingsError
from internal_api import create_internal_api

EXTENSIONS = [
    "commands.ping",
    "commands.on_message",
    "commands.helps",
    "commands.clean",
    "commands.profile_pictures",
    "cogs.shameless_team_moves",
    "cogs.shameless_games",
    "cogs.shameless_votes",
]


class MyBot(commands.Bot):
    """Porte la config unique : chaque `setup(bot)` d'extension la passe à son cog."""

    def __init__(self, settings: BotSettings):
        super().__init__(command_prefix=settings.discord.prefix, intents=discord.Intents.all())
        self.settings = settings

    async def setup_hook(self):
        # Ici on est dans le bon contexte async, donc OK
        self.runtime_loop = asyncio.get_running_loop()

        for ext in EXTENSIONS:
            await self.load_extension(ext)

    async def on_ready(self):
        print(f"{self.user.name} est prêt.")
        await self.change_presence(activity=discord.Game(self.settings.discord.status))


def run_internal_api(bot: MyBot, settings: BotSettings):
    app = create_internal_api(bot, settings)
    config = uvicorn.Config(
        app,
        host=settings.internal_api.host,
        port=settings.internal_api.port,
        log_level="info",
    )
    uvicorn.Server(config).run()


def main():
    load_dotenv()
    try:
        settings = BotSettings.from_env(os.environ)
    except SettingsError as error:
        sys.exit(str(error))

    bot = MyBot(settings)
    threading.Thread(target=run_internal_api, args=(bot, settings), daemon=True).start()
    bot.run(settings.discord.token)


if __name__ == "__main__":
    main()

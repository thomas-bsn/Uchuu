import asyncio
import copy
import logging
import os
import sys
import threading

import discord
import uvicorn
from uvicorn.config import LOGGING_CONFIG
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
    "cogs.shameless_clips",
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


def uvicorn_log_config() -> dict:
    """Logs d'uvicorn sur stdout et sans couleur, comme ceux du bot (voir main())."""
    config = copy.deepcopy(LOGGING_CONFIG)
    for formatter in config["formatters"].values():
        formatter["use_colors"] = False
    for handler in config["handlers"].values():
        handler["stream"] = "ext://sys.stdout"
    return config


def run_internal_api(bot: MyBot, settings: BotSettings):
    app = create_internal_api(bot, settings)
    config = uvicorn.Config(
        app,
        host=settings.internal_api.host,
        port=settings.internal_api.port,
        log_level="info",
        log_config=uvicorn_log_config(),
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
    # INFO de tous les modules, pas que de discord ; stdout et sans codes couleur : les logs
    # de conteneur ne sont pas un terminal (stderr s'afficherait en rouge)
    handler = logging.StreamHandler(sys.stdout)
    # via log_formatter : discord.py réapplique sinon son format coloré sur le handler
    formatter = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s %(message)s", "%Y-%m-%d %H:%M:%S")
    # httpx logge chaque URL, dont les liens signés du CDN Discord
    logging.getLogger("httpx").setLevel(logging.WARNING)
    bot.run(settings.discord.token, log_handler=handler, log_formatter=formatter, root_logger=True)


if __name__ == "__main__":
    main()

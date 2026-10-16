from fastapi import FastAPI

from bot_settings import BotSettings
from controllers.match_history_controller import router as match_history_router
from controllers.shameless_controller import router as shameless_router
from services.shameless_store import ProcessedEventStore


def create_internal_api(bot, settings: BotSettings):
    app = FastAPI(title="Internal Bot API")
    app.include_router(match_history_router)
    app.include_router(shameless_router)

    app.state.bot = bot
    app.state.bot_loop = bot.loop
    app.state.settings = settings
    app.state.shameless_settings = settings.shameless
    app.state.shameless_events_store = ProcessedEventStore(settings.shameless.db_path)
    return app

from fastapi import FastAPI
from controllers.match_history_controller import router as match_history_router
from controllers.shameless_controller import router as shameless_router
from services.shameless_store import ProcessedEventStore
from shameless_config import ShamelessSettings

def create_internal_api(bot, shameless_settings: ShamelessSettings | None = None):
    app = FastAPI(title="Internal Bot API")
    app.include_router(match_history_router)
    app.include_router(shameless_router)

    app.state.bot = bot
    app.state.bot_loop = bot.loop
    app.state.shameless_settings = shameless_settings or ShamelessSettings.from_env()
    app.state.shameless_events_store = ProcessedEventStore(app.state.shameless_settings.db_path)
    return app

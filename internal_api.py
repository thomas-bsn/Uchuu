from fastapi import FastAPI
from controllers.match_history_controller import router as match_history_router
from controllers.shameless_controller import router as shameless_router

def create_internal_api(bot):
    app = FastAPI(title="Internal Bot API")
    app.include_router(match_history_router)
    app.include_router(shameless_router)

    app.state.bot = bot
    app.state.bot_loop = bot.loop
    return app

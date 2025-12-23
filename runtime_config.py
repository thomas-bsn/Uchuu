import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN missing")

BOT_PREFIX = os.getenv("BOT_PREFIX", "$$")
BOT_STATUS = os.getenv("BOT_STATUS", "Online")

INTERNAL_API_HOST = os.getenv("INTERNAL_API_HOST", "127.0.0.1")
INTERNAL_API_PORT = int(os.getenv("INTERNAL_API_PORT", "9000"))
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "change-me")

BOT_DEBUG = os.getenv("BOT_DEBUG", "false").lower() == "true"

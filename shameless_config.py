"""Config de l'intégration Shameless (une seule Instance par déploiement).

Tout vient de l'env (préfixe SHAMELESS_), rien de spécifique à la commu n'est commité.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# Serveur Discord de l'Instance Shameless
SHAMELESS_GUILD_ID = int(os.getenv("SHAMELESS_GUILD_ID", "0"))

# Credential que l'API Shameless envoie au bot (Authorization: Bearer ...)
SHAMELESS_BOT_API_KEY = os.getenv("SHAMELESS_BOT_API_KEY", "")

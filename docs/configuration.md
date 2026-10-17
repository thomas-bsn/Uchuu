# Configuration du bot — guide opérateur

Toute la configuration vient de l'environnement (`.env` en local, `env_file` en Docker ; modèle : `.env.example`). Elle est lue **une seule fois** au démarrage par `bot_settings.BotSettings.from_env`, dans `main.py`, puis passée explicitement aux cogs et à l'API HTTP interne. Aucun ID communautaire ni secret n'est commité ; les textes des messages restent dans le code.

Si une variable requise manque ou si une valeur n'a pas le bon type, le bot refuse de démarrer et affiche **toutes** les variables fautives dans un seul message. Une variable vide compte comme absente.

## Discord

| Variable | Requis | Défaut | Rôle |
| --- | --- | --- | --- |
| `DISCORD_TOKEN` | oui | | Token du bot. |
| `BOT_PREFIX` | | `$$` | Préfixe des commandes. |
| `BOT_STATUS` | | `Online` | Statut affiché. |

## Salons

IDs Discord (clic droit > *Copier l'identifiant*, mode développeur activé).

| Variable | Requis | Rôle |
| --- | --- | --- |
| `CHANNEL_MATCH_HISTORY_ID` | oui | Salon par défaut des images d'historique de match (`POST /internal/matches/history-image` sans `channel_id`). Ancien nom accepté en repli : `CHANNEL_LOGS_ID`. |

## API HTTP interne

| Variable | Requis | Défaut | Rôle |
| --- | --- | --- | --- |
| `INTERNAL_API_KEY` | oui | | Valeur attendue dans `X-Internal-Key` (route match history). Générez-la (`openssl rand -hex 32`). |
| `INTERNAL_API_HOST` | | `127.0.0.1` | Interface d'écoute (`0.0.0.0` en Docker). |
| `INTERNAL_API_PORT` | | `9000` | Port d'écoute. |
| `FORWARDED_ALLOW_IPS` | | | Lu directement par uvicorn : IPs du reverse proxy autorisées à poser `X-Forwarded-*`. |

## Shameless

Variables `SHAMELESS_*`, toutes optionnelles : voir `docs/shameless.md`.

## Persistance

Le volume Docker monté sur `/data` contient `shameless.sqlite3` (voir `docs/shameless.md`). Il doit survivre aux redéploiements (dédup Shameless).

Le système de vote (admission Invité → Membre, promotion Confiance) a été retiré : les variables `GUILD_ID`, `ROLE_*`, `CHANNEL_VALIDATION_ID`, `*_VOTE_*`, `CONFIANCE_*` et `VOTES_DB_PATH` ne sont plus lues et peuvent être supprimées de votre `.env`. Un ancien fichier `/data/votes.sqlite3` n'est plus utilisé et peut être effacé.

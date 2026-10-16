# Configuration du bot — guide opérateur

Toute la configuration vient de l'environnement (`.env` en local, `env_file` en Docker ; modèle : `.env.example`). Elle est lue **une seule fois** au démarrage par `bot_settings.BotSettings.from_env`, dans `main.py`, puis passée explicitement aux cogs et à l'API HTTP interne. Aucun ID communautaire ni secret n'est commité ; les textes des messages restent dans le code.

Si une variable requise manque ou si une valeur n'a pas le bon type, le bot refuse de démarrer et affiche **toutes** les variables fautives dans un seul message. Une variable vide compte comme absente.

## Discord

| Variable | Requis | Défaut | Rôle |
| --- | --- | --- | --- |
| `DISCORD_TOKEN` | oui | | Token du bot. |
| `BOT_PREFIX` | | `$$` | Préfixe des commandes. |
| `BOT_STATUS` | | `Online` | Statut affiché. |

## Serveur, rôles, salons

IDs Discord (clic droit > *Copier l'identifiant*, mode développeur activé).

| Variable | Requis | Rôle |
| --- | --- | --- |
| `GUILD_ID` | oui | Serveur communautaire. |
| `ROLE_INVITE_ID` | oui | Rôle Invité (nouvel arrivant en attente de vote). |
| `ROLE_MEMBRE_ID` | oui | Rôle Membre. |
| `ROLE_CONFIANCE_ID` | oui | Rôle Confiance (seuls votants). |
| `CHANNEL_VALIDATION_ID` | oui | Salon des messages de vote. |
| `CHANNEL_LOGS_ID` | oui | Salon des logs du bot. |
| `CHANNEL_MATCH_HISTORY_ID` | | Salon par défaut des images d'historique de match (défaut : `CHANNEL_LOGS_ID`). |

## Règles de vote

| Variable | Défaut | Rôle |
| --- | --- | --- |
| `INVITE_VOTE_WINDOW_SECONDS` | `86400` (24 h) | Durée d'un vote Invité → Membre. |
| `CONFIANCE_VOTE_WINDOW_SECONDS` | `86400` (24 h) | Durée d'un vote Membre → Confiance. |
| `VOTE_APPROVALS_REQUIRED` | `1` | Approbations ✅ nécessaires. |
| `CONFIANCE_ELIGIBILITY_DAYS` | `30` | Ancienneté minimale sur le serveur pour être proposé Confiance. |
| `CONFIANCE_COOLDOWN_DAYS` | `30` | Délai avant de reproposer un Membre après un vote expiré. |
| `CONFIANCE_SCAN_INTERVAL_HOURS` | `24` | Fréquence du scan des candidats Confiance. |
| `VOTES_DB_PATH` | `/data/votes.sqlite3` | SQLite des votes, fichier dédié (distinct de la base Shameless), sur le volume persistant `/data`. Hors Docker, pointez-le vers un chemin accessible en écriture. |

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

Le volume Docker monté sur `/data` contient `shameless.sqlite3` et `votes.sqlite3`. Il doit survivre aux redéploiements (dédup Shameless, état des votes).

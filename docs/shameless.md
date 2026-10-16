# Intégration Shameless — guide opérateur

Une Instance Shameless par déploiement du bot. Toute la config passe par l'env (`SHAMELESS_*`, voir `.env.example`, lue par `shameless_config.ShamelessSettings.from_env()`) ; aucun ID communautaire ni secret n'est commité.

## Variables d'environnement

| Variable | Rôle |
| --- | --- |
| `SHAMELESS_GUILD_ID` | Serveur Discord de l'Instance. C'est le seul serveur inspecté. |
| `SHAMELESS_BOT_API_KEY` | Credential de l'identité machine de l'API Shameless pour appeler le bot. Vide = toutes les requêtes sont refusées. Distinct du secret webhook. |
| `SHAMELESS_WEBHOOK_SECRET` | Secret HMAC partagé avec l'API pour signer les webhooks API -> bot. Vide = le callback répond 503. |
| `SHAMELESS_WEBHOOK_TOLERANCE_SECONDS` | Écart max accepté entre `X-Shameless-Timestamp` et l'horloge du bot (défaut 300). |
| `SHAMELESS_HANDLER_TIMEOUT_SECONDS` | Délai max d'un handler Discord avant réponse 504 (défaut 30). |
| `SHAMELESS_DB_PATH` | Fichier SQLite local (dédup webhooks, présences). En Docker : `/data/shameless.sqlite3`. |
| `SHAMELESS_SHARED_VOICE_ID`, `SHAMELESS_TEAM1_VOICE_ID`, `SHAMELESS_TEAM2_VOICE_ID` | Salons vocaux commun / Team 1 / Team 2. |
| `SHAMELESS_ANNOUNCE_CHANNEL_ID` | Salon texte des annonces et récaps. |
| `SHAMELESS_WEB_URL` | URL publique du site (liens de récap). |
| `FORWARDED_ALLOW_IPS` | IPs du reverse proxy autorisées à poser `X-Forwarded-*` (lu directement par uvicorn). |

Credentials : générez des valeurs aléatoires longues (par ex. `openssl rand -hex 32`), stockez-les dans l'env du bot et dans celle de l'API. Rotation = changer les deux env puis redémarrer, aucun changement de code.

## Candidats vocaux (Picker)

`GET /internal/shameless/voice-candidates`, avec `Authorization: Bearer <SHAMELESS_BOT_API_KEY>`.

Seule l'API Shameless (côté serveur) appelle cet endpoint. Le navigateur passe par l'API et ne reçoit jamais le credential.

Réponse `200` :

```json
{ "channel_id": "123456789012345678", "member_ids": ["111...", "222..."] }
```

- Le salon retenu est le vocal du serveur configuré qui a le plus de membres humains. Les bots ne sont ni comptés ni renvoyés.
- En cas d'égalité, le salon avec le plus petit ID Discord gagne.
- Les IDs sont des chaînes (snowflakes Discord stables, triés par ordre croissant). Aucun nom ni surnom n'est renvoyé.
- Personne en vocal : `{ "channel_id": null, "member_ids": [] }`.

Erreurs : `401` si le credential est absent ou faux. `503` si le bot n'est pas prêt ou si le serveur configuré n'est pas dans son cache.

## Callback webhook

`POST /internal/shameless/webhook`, exposé en HTTPS par le reverse proxy public
(ex. `https://bot.example.org/internal/shameless/webhook` -> `http://127.0.0.1:9000`).

Headers :

- `X-Shameless-Timestamp` : timestamp Unix (secondes).
- `X-Shameless-Signature` : `sha256=` + hex(HMAC-SHA256(secret, `"{timestamp}." + body brut`)).

Enveloppe JSON (version 1) :

```json
{
  "version": 1,
  "event_id": "stable-unique-id",
  "type": "teams_formed | game_started | game_completed",
  "occurred_at": "2026-10-17T20:00:00Z",
  "data": { "...": "snapshot propre au type" }
}
```

Réponses :

| Code | Corps | Sens pour l'émetteur |
| --- | --- | --- |
| 200 | `{"status": "processed"}` | Traité. |
| 200 | `{"status": "duplicate"}` | `event_id` déjà pris en charge (même après redémarrage) : rien n'est rejoué. |
| 200 | `{"status": "ignored"}` | Type sans handler : acquitté, non enregistré. |
| 401 | | Signature absente, invalide ou expirée. |
| 422 | | Enveloppe invalide ou version non supportée. |
| 500 | | Le handler a échoué : réservation annulée, **retenter**. |
| 503 | | Secret non configuré ou bot pas encore prêt : retenter. |
| 504 | | Handler trop long : état Discord inconnu, l'`event_id` reste réservé et ne sera pas rejoué. |

L'`event_id` est persisté dans SQLite **avant** l'exécution du handler et l'accusé de réception :
le choix est « au plus une fois » pour les effets Discord (pas de double move / annonce / récap).

## Annonces, récaps et présences par Game (`game_started` / `game_completed`)

Cog `cogs.shameless_games`. Messages publiés dans `SHAMELESS_ANNOUNCE_CHANNEL_ID` (si absent : rien n'est publié, l'event est acquitté).

Snapshot `game_started` attendu :

```json
{
  "series_id": "s-1", "game_id": "g-1", "game_number": 1, "best_of": 3,
  "series_url": "https://…/series/s-1",
  "teams": {
    "A": { "name": "Les Chauves", "side": "blue", "players": [{ "name": "Zed Main", "discord_id": "101" }] },
    "B": { "name": "Les Barbus", "side": "red", "players": [ … ] }
  },
  "participant_discord_ids": ["101", "…"]
}
```

Snapshot `game_completed` attendu (stats joueur = contrat Shameless #52) :

```json
{
  "series_id": "s-1", "game_id": "g-1", "game_number": 1, "best_of": 3,
  "winner": "A", "series_score": { "A": 1, "B": 0 }, "duration_seconds": 1834,
  "recap_url": "https://…/games/g-1",
  "teams": { "A": { "name": "…", "side": "blue", "players": [{
      "name": "Zed Main", "discord_id": "101", "champion": "Zed", "role": "MID",
      "kills": 12, "deaths": 3, "assists": 7, "cs": 243, "cs_per_min": 7.9,
      "kill_participation": 0.61, "damage": 31250, "performance_score": 88 }] },
    "B": { … } },
  "participant_discord_ids": ["101", "…"]
}
```

- **Annonce de Série** : au `game_started` de la Game n°1 (ou sans `game_number`), une seule fois par `series_id`, même si l'API republie avec un autre `event_id` ou après redémarrage.
- **Récap** : un embed par `game_id` (vainqueur, deux Teams, score de Série, stats fournies, lien web). Lien = `recap_url`, sinon `SHAMELESS_WEB_URL/games/{game_id}`. Tous les champs sont optionnels : ce qui manque n'est pas affiché. Pas de vote MVP/DOFD (Phase 2).
- Si l'envoi Discord échoue, le webhook répond 500 et le retry republie.
- **Présences (Spectateurs)** : `game_started` ouvre une fenêtre pour `game_id`, `game_completed` la ferme. Pendant la fenêtre, les comptes humains vus dans les salons commun / Team 1 / Team 2 (présents au départ, arrivés ensuite, présents à la fin) sont enregistrés dans SQLite, hors `participant_discord_ids` (à défaut, les `discord_id` des Teams) et hors bots. Un ensemble par Game ; la fenêtre ouverte survit à un redémarrage (et au `on_ready`, les présents sont rattrapés). Lecture (Phase 2) : `GameAttendanceStore(db_path).spectators(game_id)`.

## Docker

```sh
cp .env.example .env   # puis remplir, ne jamais commiter
docker compose up -d --build
```

- Le volume nommé `shameless-data` est monté sur `/data` et contient `shameless.sqlite3`.
  **Il doit persister entre redéploiements** : le perdre fait rejouer des événements déjà traités.
  Sauvegarde : `docker compose cp bot:/data/shameless.sqlite3 ./backup.sqlite3`.
- Le port 9000 n'est publié que sur `127.0.0.1` de l'hôte ; seul le reverse proxy HTTPS l'expose.
- `.env` est exclu de l'image (`.dockerignore`) et fourni au runtime via `env_file`.

## Discord Developer Portal

- Scopes d'installation : `bot` et `applications.commands`.
- Gateway intents privilégiés : activez **Server Members Intent**, car le bot lit les membres présents en vocal (`main.py` démarre avec `Intents.all()`). L'intent `voice_states` (non privilégié) est indispensable.
- Permissions serveur : **View Channels** sur les salons vocaux à inspecter.
- Salon d'annonce (`SHAMELESS_ANNOUNCE_CHANNEL_ID`) : **Send Messages** et **Embed Links**.

## Tests

```sh
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

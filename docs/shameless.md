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

## Tests

```sh
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

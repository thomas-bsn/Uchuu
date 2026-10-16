# Intégration Shameless — guide opérateur

Une Instance Shameless par déploiement du bot. Toute la config passe par l'environnement
(voir `.env.example`, préfixe `SHAMELESS_`) ; aucun ID communautaire ni secret dans le dépôt.

## Variables d'environnement

| Variable | Rôle |
| --- | --- |
| `SHAMELESS_WEBHOOK_SECRET` | Secret HMAC partagé avec l'API pour signer les webhooks API -> bot. Sans lui, le callback répond 503. |
| `SHAMELESS_WEBHOOK_TOLERANCE_SECONDS` | Écart max accepté entre `X-Shameless-Timestamp` et l'horloge du bot (défaut 300). |
| `SHAMELESS_HANDLER_TIMEOUT_SECONDS` | Délai max d'un handler Discord avant réponse 504 (défaut 30). |
| `SHAMELESS_DB_PATH` | Fichier SQLite local (dédup webhooks, présences). En Docker : `/data/shameless.sqlite3`. |
| `SHAMELESS_BOT_API_KEY` | Clé des requêtes authentifiées API -> bot. Distincte du secret webhook. |
| `SHAMELESS_GUILD_ID` | Serveur Discord de l'Instance. |
| `SHAMELESS_SHARED_VOICE_ID`, `SHAMELESS_TEAM1_VOICE_ID`, `SHAMELESS_TEAM2_VOICE_ID` | Salons vocaux commun / Team 1 / Team 2. |
| `SHAMELESS_ANNOUNCE_CHANNEL_ID` | Salon texte des annonces et récaps. |
| `SHAMELESS_WEB_URL` | URL publique du site (liens de récap). |
| `FORWARDED_ALLOW_IPS` | IPs du reverse proxy autorisées à poser `X-Forwarded-*` (lu par uvicorn). |

Rotation : changer la valeur côté API et côté bot puis redémarrer, aucun changement de code.

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

À compléter par les tickets voix (#3/#4) : scopes `bot` + `applications.commands`, intents
(voice states, members), permissions (View Channels, Connect, Move Members, Send Messages, Embed Links).

## Tests

```sh
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

# Intégration Shameless — guide opérateur

Une Instance Shameless par déploiement du bot. Toute la config passe par l'env (`SHAMELESS_*`, voir `.env.example`), lue une seule fois au démarrage par `bot_settings.BotSettings.from_env` dans la sous-section `settings.shameless` (config générale du bot : `docs/configuration.md`) ; aucun ID communautaire ni secret n'est commité.

## Variables d'environnement

| Variable | Rôle |
| --- | --- |
| `SHAMELESS_GUILD_ID` | Serveur Discord de l'Instance. C'est le seul serveur inspecté. |
| `SHAMELESS_BOT_API_KEY` | Credential de l'identité machine de l'API Shameless pour appeler le bot. Vide = toutes les requêtes sont refusées. Distinct du secret webhook. |
| `SHAMELESS_WEBHOOK_SECRET` | Secret HMAC partagé avec l'API pour signer les webhooks API -> bot. Vide = le callback répond 503. |
| `SHAMELESS_WEBHOOK_TOLERANCE_SECONDS` | Écart max accepté entre `X-Shameless-Timestamp` et l'horloge du bot (défaut 300). |
| `SHAMELESS_HANDLER_TIMEOUT_SECONDS` | Délai max d'un handler Discord avant réponse 504 (défaut 30). |
| `SHAMELESS_CLAIM_LEASE_SECONDS` | Durée de réservation d'un event en cours de traitement (défaut 120). Passé ce délai (crash, timeout), un retry le reprend. Doit rester supérieur au timeout handler. |
| `SHAMELESS_DB_PATH` | Fichier SQLite local (dédup webhooks, présences). En Docker : `/data/shameless.sqlite3`. |
| `SHAMELESS_TEAM1_VOICE_ID`, `SHAMELESS_TEAM2_VOICE_ID` | Salons vocaux Team 1 / Team 2 (moves d'équipe). Il n'y a pas de vocal commun configuré : l'ancienne `SHAMELESS_SHARED_VOICE_ID` n'est plus lue (ignorée si encore présente). |
| `SHAMELESS_ANNOUNCE_CHANNEL_ID` | Salon texte des annonces et récaps. |
| `SHAMELESS_WEB_URL` | URL publique du site (liens de récap). |
| `SHAMELESS_API_URL` | Adresse de l'API Shameless que le bot appelle (`/bot/…` y est ajouté). Derrière le proxy de Shameless : adresse publique **suivie de `/api`**. Requise pour le dépôt des clips. |
| `SHAMELESS_BOT_TO_API_KEY` | Clé Bearer que le bot présente sur les routes `/bot/…` de l'API ; même valeur que `SHAMELESS_BOT_TO_API_KEY` côté Shameless. Distincte de `SHAMELESS_BOT_API_KEY` (sens inverse). |
| `SHAMELESS_CLIPS_CHANNEL_ID` | Salon texte `#clips` dont les vidéos sont déposées sur l'API. Sans lui (ou sans `SHAMELESS_API_URL` / `SHAMELESS_BOT_TO_API_KEY`), aucun dépôt. |
| `SHAMELESS_CLIPS_MAX_BYTES` | Taille max d'un clip en octets (défaut 524288000 = 500 Mo). **À garder égale** à la limite de l'API : au-delà, la vidéo est ignorée sans être téléchargée. |
| `FORWARDED_ALLOW_IPS` | IPs du reverse proxy autorisées à poser `X-Forwarded-*` (lu directement par uvicorn). |

Sens des appels : l'API Shameless appelle le bot (candidats vocaux, webhooks). Le bot n'appelle l'API que pour **déposer les clips** (`POST /bot/clips`, section ci-dessous), avec `SHAMELESS_API_URL` et `SHAMELESS_BOT_TO_API_KEY`. `SHAMELESS_WEB_URL` ne sert qu'à construire des liens affichés dans Discord.

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

`POST /internal/shameless/webhook`, exposé en HTTPS par le reverse proxy public.
L'URL de callback à configurer côté API est `https://<hôte public du bot>/internal/shameless/webhook`
(même chemin derrière le proxy, ex. `https://bot.example.org/internal/shameless/webhook` -> `http://127.0.0.1:9000/internal/shameless/webhook`).
Idem pour `GET https://<hôte public du bot>/internal/shameless/voice-candidates`.

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
| 200 | `{"status": "duplicate"}` | `event_id` déjà **traité avec succès** (même après redémarrage) : rien n'est rejoué. |
| 200 | `{"status": "ignored"}` | Type sans handler : acquitté, non enregistré. |
| 401 | | Signature absente, invalide ou expirée. |
| 409 | `{"detail": "in_progress"}` | Une autre livraison de cet `event_id` est en cours : **retenter** plus tard. |
| 422 | | Enveloppe invalide ou version non supportée. |
| 500 | | Le handler a échoué : réservation annulée, **retenter**. |
| 503 | | Secret non configuré ou bot pas encore prêt : retenter. |
| 504 | | Handler trop long (annulé) : **retenter**. La réservation expire après `SHAMELESS_CLAIM_LEASE_SECONDS` (409 d'ici là), puis le retry est exécuté. |

L'`event_id` est réservé dans SQLite (`processing`) **avant** l'exécution du handler, puis marqué
`done` après succès. Seul `done` répond `duplicate` : un event en cours, échoué, interrompu par un
timeout ou par un crash du bot finit par être ré-exécuté par un retry (« au moins une fois »).
Les effets Discord restent idempotents : un membre déjà dans son vocal d'équipe n'est pas
re-déplacé, et chaque annonce / récap est gardé par `(type, series_id | game_id)` en SQLite.

Compromis restant (« au plus une fois » pour les messages) : la garde d'un message est posée
juste avant `send`. Si Discord publie le message mais que le bot plante ou que le handler expire
avant d'avoir reçu la réponse, la garde est libérée (timeout) et le retry peut republier ce
message (doublon possible), ou bien elle est conservée (crash) et le message n'est jamais
republié. Ces cas exigent une panne au moment exact de l'envoi.

## Moves d'équipe (`teams_formed`)

Shameless envoie `teams_formed` quand le Picker valide les Teams et la Série, avant la Draft de champions. Snapshot attendu dans `data` :

```json
{
  "series_id": "s-1",
  "team_a": { "name": "...", "players": [{ "discord_id": "111111111111111111" }, { "discord_id": null }] },
  "team_b": { "name": "...", "players": [{ "discord_id": "222222222222222222" }] }
}
```

- Mapping unique (`services.shameless_payloads.team_voice_ids`) : Team A va dans `SHAMELESS_TEAM1_VOICE_ID`, Team B dans `SHAMELESS_TEAM2_VOICE_ID`, pour toute la Série et quel que soit le côté bleu/rouge.
- Sont déplacés uniquement les Joueurs dont le `discord_id` est fourni (string, snowflake) et qui sont connectés à un vocal du serveur. Les Joueurs sans lien Discord, les membres hors vocal et les Spectateurs ne bougent pas.
- Un membre déjà dans son vocal d'équipe n'est pas redéplacé. Si un move échoue (permissions, membre parti), l'erreur est loguée et les autres moves continuent.
- Si le serveur ou un vocal d'équipe est introuvable, le bot ne déplace personne et répond `500` : Shameless retente avec le même `event_id`.
- Payload mal formé (Team absente, `players` null ou pas une liste, `discord_id` invalide) : la partie invalide est ignorée et loguée, le reste est traité et l'event est acquitté `processed`. Un retry ne réparerait jamais le payload, donc pas de boucle de `500`.
- Un seul move par Série : `game_started` / `game_completed` ne déplacent personne. Les joueurs vont où ils veulent entre les Games et rejoignent leur vocal d'équipe quand ils veulent.
- Permissions Discord requises sur les salons Team 1 et Team 2 : **View Channel**, **Connect** et **Move Members** (Discord exige que le bot puisse voir et rejoindre le salon cible pour y déplacer quelqu'un).

## Annonces, récaps et présences par Game (`game_started` / `game_completed`)

Cog `cogs.shameless_games`. Messages publiés dans `SHAMELESS_ANNOUNCE_CHANNEL_ID`. Si la variable est absente ou si le salon est introuvable / inaccessible, le handler échoue (`500`) : l'event n'est pas marqué traité et le retry de Shameless publie une fois la config corrigée.

Teams au même format que `teams_formed` (`team_a` / `team_b`) ; `winner` et `series_score` utilisent `A` / `B`.

Snapshot `game_started` attendu :

```json
{
  "series_id": "s-1", "game_id": "g-1", "game_number": 1, "best_of": 3,
  "series_url": "https://…/series/s-1",
  "team_a": { "name": "Les Chauves", "side": "blue", "players": [{ "name": "Zed Main", "discord_id": "101" }] },
  "team_b": { "name": "Les Barbus", "side": "red", "players": [ … ] },
  "participant_discord_ids": ["101", "…"]
}
```

Snapshot `game_completed` attendu (stats joueur = contrat Shameless #52) :

```json
{
  "series_id": "s-1", "game_id": "g-1", "game_number": 1, "best_of": 3,
  "winner": "A", "series_score": { "A": 1, "B": 0 }, "duration_seconds": 1834,
  "recap_url": "https://…/games/g-1",
  "team_a": { "name": "…", "side": "blue", "players": [{
      "name": "Zed Main", "discord_id": "101", "champion": "Zed", "role": "MID",
      "kills": 12, "deaths": 3, "assists": 7, "cs": 243, "cs_per_min": 7.9,
      "kill_participation": 0.61, "damage": 31250, "performance_score": 88 }] },
  "team_b": { … },
  "participant_discord_ids": ["101", "…"]
}
```

- **Annonce de Série** : au premier `game_started` reçu pour un `series_id` (normalement la Game n°1, mais aussi une Game suivante si celui de la Game 1 a été raté), une seule fois par `series_id`, même si l'API republie avec un autre `event_id` ou après redémarrage.
- **Récap** : un embed par `game_id` (vainqueur, deux Teams, score de Série, stats fournies, lien web). Lien = `recap_url`, sinon `SHAMELESS_WEB_URL/games/{game_id}`. Tous les champs sont optionnels : ce qui manque n'est pas affiché. Pas de vote MVP/DOFD (Phase 2).
- Si l'envoi Discord échoue, le webhook répond 500 et le retry republie.
- **Présences (Spectateurs)** : `game_started` ouvre une fenêtre pour `game_id`, `game_completed` la ferme. Pendant la fenêtre, les comptes humains vus dans **n'importe quel salon vocal du serveur `SHAMELESS_GUILD_ID`** (Team 1, Team 2 ou tout autre vocal ; présents au départ, arrivés ensuite, présents à la fin) sont enregistrés dans SQLite, hors `participant_discord_ids` (à défaut, les `discord_id` des Teams) et hors bots. Les vocaux des autres serveurs sont ignorés. Le bot doit avoir **View Channel** sur tous les vocaux à observer : un salon invisible pour lui n'est pas compté. Un ensemble par Game ; la fenêtre ouverte survit à un redémarrage (et au `on_ready`, les présents sont rattrapés). Lecture (Phase 2) : `GameAttendanceStore(db_path).spectators(game_id)`.

## Clips (`#clips`)

Cog `cogs.shameless_clips`. Chaque message **humain** du salon `SHAMELESS_CLIPS_CHANNEL_ID` dont une pièce jointe est une vidéo (`video/mp4`, `video/webm`, `video/quicktime`) est téléchargé puis déposé sur `POST {SHAMELESS_API_URL}/bot/clips` (`multipart/form-data`, `Authorization: Bearer <SHAMELESS_BOT_TO_API_KEY>`) : `fichier`, `messageId`, `attachmentId`, `auteurDiscordId`, `auteurNom`, `publieLe`. Contrat et rattachement à la Game : ADR 0014 du dépôt Shameless.

- L'API conserve la vidéo (volume `api-clips`, à sauvegarder côté Shameless) ; le bot ne garde rien : le fichier passe par un temporaire supprimé après le dépôt.
- Dépôt idempotent sur `attachmentId` (201 puis 200) : rejouer est sans risque.
- Une vidéo plus grosse que `SHAMELESS_CLIPS_MAX_BYTES` est ignorée avant téléchargement (warning dans les logs).
- Échec réseau ou 5xx : 3 tentatives (le fichier n'est téléchargé qu'une fois). 400 / 401 / 409 / 413 : abandon immédiat, loggé. Les tentatives vivent en mémoire : un clip dont le dépôt échoue ou posté pendant que le bot est arrêté n'est pas rejoué au redémarrage.

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
- Gateway intents privilégiés : `main.py` démarre avec `discord.Intents.all()`, qui demande **les trois** intents privilégiés. Activez-les tous dans *Bot > Privileged Gateway Intents*, sinon la connexion est refusée :
  - **Presence Intent** ;
  - **Server Members Intent** (membres présents en vocal, Joueurs à déplacer) ;
  - **Message Content Intent** (commandes préfixées des autres cogs).
  L'intent `voice_states` (non privilégié) est indispensable.
- Permissions serveur : **View Channel** sur **tous** les salons vocaux du serveur à observer (Picker et présences Spectateurs) ; **View Channel**, **Connect** et **Move Members** sur les salons Team 1 / Team 2.
- Salon d'annonce (`SHAMELESS_ANNOUNCE_CHANNEL_ID`) : **Send Messages** et **Embed Links**.

## Tests

```sh
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

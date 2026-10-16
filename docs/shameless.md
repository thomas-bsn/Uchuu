# Intégration Shameless

Une Instance Shameless par déploiement du bot. Toute la config passe par l'env (`SHAMELESS_*`, voir `.env.example`), rien n'est commité.

## Variables d'environnement

| Variable | Rôle |
| --- | --- |
| `SHAMELESS_GUILD_ID` | Serveur Discord de l'Instance. C'est le seul serveur inspecté. |
| `SHAMELESS_BOT_API_KEY` | Credential de l'identité machine de l'API Shameless pour appeler le bot. Vide = toutes les requêtes sont refusées. |

## Candidats vocaux (Picker)

`GET /internal/shameless/voice-candidates`, avec `Authorization: Bearer <SHAMELESS_BOT_API_KEY>`.

Seule l'API Shameless (côté serveur) appelle cet endpoint. Le navigateur passe par l'API et ne reçoit jamais le credential. Générez une valeur aléatoire longue (par ex. `openssl rand -hex 32`), stockez-la dans l'env du bot et dans celle de l'API, et changez-la en changeant les deux env (aucun changement de code).

Réponse `200` :

```json
{ "channel_id": "123456789012345678", "member_ids": ["111...", "222..."] }
```

- Le salon retenu est le vocal du serveur configuré qui a le plus de membres humains. Les bots ne sont ni comptés ni renvoyés.
- En cas d'égalité, le salon avec le plus petit ID Discord gagne.
- Les IDs sont des chaînes (snowflakes Discord stables, triés par ordre croissant). Aucun nom ni surnom n'est renvoyé.
- Personne en vocal : `{ "channel_id": null, "member_ids": [] }`.

Erreurs : `401` si le credential est absent ou faux. `503` si le bot n'est pas prêt ou si le serveur configuré n'est pas dans son cache.

## Discord Developer Portal

- Scopes d'installation : `bot` et `applications.commands`.
- Gateway intents privilégiés : activez **Server Members Intent**, car le bot lit les membres présents en vocal (`main.py` démarre avec `Intents.all()`). L'intent `voice_states` (non privilégié) est indispensable.
- Permissions serveur : **View Channels** sur les salons vocaux à inspecter.

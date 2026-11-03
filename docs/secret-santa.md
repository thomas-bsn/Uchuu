# Secret Santa

Commandes à préfixe du bot (serveur uniquement) : `$$secret-santa test | draw | status | retry`. Détail et exemples : `$$helps secret-santa`.

Une commande à préfixe n'a pas de réponse éphémère : la liste des participants, le statut, la confirmation et les résultats sont envoyés **en MP à celui qui lance la commande** (il doit donc avoir ses MP ouverts) ; le salon ne reçoit qu'un accusé « Réponse envoyée en MP ». Seuls les résultats de `test` et les erreurs de saisie sont visibles dans le salon.

- **Permission** : *Gérer le serveur* pour `test`, `draw`, `status`. `retry` : en plus, uniquement l'organisateur enregistré au tirage.
- **Permissions du bot** : voir le salon + lire l'historique du message d'inscription (vérifié avant le tirage). Les MP ne demandent aucune permission, mais chaque participant doit autoriser les MP des membres du serveur.
- **Un tirage par serveur et par année**, irréversible : un second `draw` est refusé (garde atomique en base). Aucune commande de reset.
- **Persistance** : tables `secret_santa_*` dans `SHAMELESS_DB_PATH` (fichier en `0600`). Une attribution est effacée de la base dès que son MP est accepté ; seules celles des MP en échec subsistent, pour `retry`. Les logs ne contiennent que des compteurs. Ne pas ouvrir ce fichier avant la fin des envois si l'on veut rester ignorant des attributions.

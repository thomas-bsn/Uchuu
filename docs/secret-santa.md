# Secret Santa

Commandes à préfixe du bot (serveur uniquement) : `$$secret-santa test | draw | status | retry | info | on | off`. Détail et exemples : `$$helps secret-santa`.

Une commande à préfixe n'a pas de réponse éphémère : la liste des participants, le statut, la confirmation et les résultats sont envoyés **en MP à celui qui lance la commande** (il doit donc avoir ses MP ouverts) ; le salon ne reçoit qu'un accusé « Réponse envoyée en MP ». Seuls les résultats de `test` et les erreurs de saisie sont visibles dans le salon.

- **Autorisation** : seuls les IDs listés dans `include/secret_santa_organizers.txt` (un par ligne) peuvent utiliser les commandes ; pour en ajouter, modifier ce fichier et redéployer. `retry` : en plus, uniquement l'organisateur enregistré au tirage.
- **Permissions du bot** : voir le salon + lire l'historique du message d'inscription (vérifié avant le tirage). Les MP ne demandent aucune permission, mais chaque participant doit autoriser les MP des membres du serveur.
- **Un tirage par serveur et par année**, irréversible : un second `draw` est refusé (garde atomique en base). Aucune commande de reset.
- **Persistance** : tables `secret_santa_*` dans `SHAMELESS_DB_PATH` (fichier en `0600`). Une attribution est effacée de la base dès que son MP est accepté ; seules celles des MP en échec subsistent, pour `retry`. Les logs ne contiennent que des compteurs. Ne pas ouvrir ce fichier avant la fin des envois si l'on veut rester ignorant des attributions.
- **`info`** : second message à tous les participants (budget libre, livraison en main propre ou par la poste, révélation en vocal le dimanche 20 décembre — texte dans `info_text`, `services/secret_santa.py`). Aperçu en MP puis confirmation par bouton ; jamais envoyé deux fois à la même personne, relancer la commande ne recontacte que les échecs. Ne lit que les donneurs, jamais un destinataire.
- **`off` / `on`** : désactive / réactive `test`, `draw`, `status`, `retry`, `info` (état en base, survit aux redémarrages). Après `off`, `retry` est bloqué aussi : faire `on` d'abord.

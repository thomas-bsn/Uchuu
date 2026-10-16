from datetime import datetime, timezone

class Logger:
    def __init__(self, bot, logs_channel_id: int):
        self.bot = bot
        self.logs_channel_id = logs_channel_id

    @property
    def logs_channel(self):
        """Résolu à l'appel (pas au chargement, où le cache du bot est encore vide)."""
        return self.bot.get_channel(self.logs_channel_id)

    async def info(self, message: str):
        """Logge une information dans le channel #logs"""
        logs_channel = self.logs_channel
        if logs_channel:
            await logs_channel.send(f"{message}")


    async def log_promotion(self, member, approver_id: int | None, role_promoted: str):
        """Logge la promotion d'un membre dans le channel #logs avec un format structuré."""
        approver_txt = f"<@{approver_id}>" if approver_id else "Inconnu"
        now_ts = int(datetime.now(timezone.utc).timestamp())

        # Construire le message structuré avec des emojis et des informations claires
        log_message = (
            f"🎉 **Promotion réussie !** 🎉\n"
            f"👤 **Utilisateur :** {member.mention} ({member.id})\n"
            f"🔑 **Rôle :** '{role_promoted}' ajouté\n"
            f"✅ **Approuvé par :** {approver_txt}\n"
            f"🕒 **Date :** <t:{now_ts}:F>\n\n"
            f"📜 **Détails :**\n"
            f"📌 L'utilisateur a été promu au rôle de '{role_promoted}' après approbation."
        )

        # Envoi du message dans le canal des logs
        logs_channel = self.logs_channel
        if logs_channel:
            await logs_channel.send(log_message)

    
    async def error(self, message: str):
        """Logge une erreur dans le channel #logs"""
        logs_channel = self.logs_channel
        if logs_channel:
            await logs_channel.send(f"❌ [ERROR] {message}")

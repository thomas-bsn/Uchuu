import discord
from config import CHANNEL_LOGS_ID
from datetime import datetime, timezone

class Logger:
    def __init__(self, bot):
        self.bot = bot
        self.logs_channel = None
        self.setup()

    def setup(self):
        """Configure le channel de logs"""
        self.logs_channel = self.bot.get_channel(CHANNEL_LOGS_ID)

    async def info(self, message: str):
        """Logge une information dans le channel #logs"""
        if self.logs_channel:
            await self.logs_channel.send(f"{message}")


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
        await self.logs_channel.send(log_message)

    
    async def error(self, message: str):
        """Logge une erreur dans le channel #logs"""
        if self.logs_channel:
            await self.logs_channel.send(f"❌ [ERROR] {message}")

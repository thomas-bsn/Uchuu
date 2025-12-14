import discord
from .service import VerificationService
from .config import *

class VoteView(discord.ui.View):
    def __init__(self, service: VerificationService, target_id: int):  
        super().__init__(timeout=None)
        self.service = service
        self.target_id = target_id

    async def _handle_vote(self, interaction: discord.Interaction, vote_yes: bool):
        guild = interaction.guild
        voter = interaction.user

        if guild is None or guild.id != GUILD_ID:
            return await interaction.response.send_message("Serveur non supporté.", ephemeral=True)

        confiance_role = guild.get_role(ROLE_CONFIANCE_ID)
        if confiance_role is None or confiance_role not in voter.roles:
            return await interaction.response.send_message("Réservé aux Confiance.", ephemeral=True)

        try:
            # Appel à handle_vote via le service correctement initialisé
            result = await self.service.handle_vote(
                guild=guild,
                target_id=self.target_id,
                voter_id=voter.id,
                vote_yes=vote_yes,
            )
            
            # Vérifier si le message de résultat est vide avant de l'envoyer
            if not result:
                result = "Erreur interne. Veuillez réessayer plus tard."
            
            # Réponse directe sans defer
            return await interaction.response.send_message(result, ephemeral=True)

        except Exception as e:
            if DEBUG:
                logs_channel = guild.get_channel(CHANNEL_LOGS_ID)
                if logs_channel:
                    await logs_channel.send(f"❌ [verification] Erreur lors du vote : {type(e).__name__} - {str(e)}")
            return await interaction.response.send_message("Erreur interne. Veuillez réessayer plus tard.", ephemeral=True)


    @discord.ui.button(label="✅", style=discord.ButtonStyle.success)
    async def yes_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_vote(interaction, vote_yes=True)

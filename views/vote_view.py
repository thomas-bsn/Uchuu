import discord

class VoteView(discord.ui.View):
    def __init__(self, service, target_id: int, role_confiance_id: int):
        super().__init__(timeout=None)
        self.service = service
        self.target_id = target_id
        self.role_confiance_id = role_confiance_id

    @discord.ui.button(label="✅", style=discord.ButtonStyle.success)
    async def yes_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_vote(interaction, vote_yes=True)

    async def _handle_vote(self, interaction: discord.Interaction, vote_yes: bool):
        guild = interaction.guild
        voter = interaction.user

        if guild is None:
            return await interaction.response.send_message("Serveur non supporté.", ephemeral=True)

        confiance_role = guild.get_role(self.role_confiance_id)  # Mentionner le rôle Confiance
        if confiance_role is None:
            return await interaction.response.send_message("Rôle 'Confiance' non trouvé.", ephemeral=True)

        # Inclure la mention du rôle Confiance dans le message
        confiance_mention = confiance_role.mention  # Cela ajoute la mention dynamique du rôle

        try:
            # Appel au service pour gérer le vote
            result = await self.service.handle_vote(
                guild=guild,
                target_id=self.target_id,
                voter_id=voter.id,
                vote_yes=vote_yes,
            )

            # Modifier le message pour inclure la mention du rôle "Confiance"
            content = f"{result}\n\n**Rôle Confiance** : {confiance_mention}"
            return await interaction.response.send_message(content, ephemeral=True)

        except Exception as e:
            return await interaction.response.send_message("Erreur lors du vote. Veuillez réessayer plus tard.", ephemeral=True)

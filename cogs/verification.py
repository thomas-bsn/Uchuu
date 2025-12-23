import discord
from discord.ext import commands
from datetime import datetime, timezone
from services.verification_service import VerificationService
from views.vote_view import VoteView
from discord_config import *
from utils.logger import Logger

class Verification(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.service = VerificationService(bot)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Attribue le rôle 'Invité' et crée un vote pour l'adhésion"""
        if member.guild.id != GUILD_ID:
            return

        guild = member.guild
        invite_role = guild.get_role(ROLE_INVITE_ID)
        validation_channel = guild.get_channel(CHANNEL_VALIDATION_ID)

        if invite_role is None or validation_channel is None:
            return

        # Récupérer le rôle "Confiance"
        confiance_role = guild.get_role(ROLE_CONFIANCE_ID)  # Mentionner le rôle Confiance
        if confiance_role is None:
            return  # Si le rôle Confiance n'existe pas, on arrête l'exécution

        # Créer la mention dynamique du rôle Confiance
        confiance_mention = confiance_role.mention  # Cela ajoute la mention dynamique du rôle

        try:
            await member.add_roles(invite_role, reason="Nouveau membre invité pour validation")
        except discord.Forbidden:
            await self.service.logger.error(f"Impossible d'ajouter le rôle 'Invité' à {member.mention}.")
            return

        # Crée le vote pour valider l'invitation
        expires_at_ts = int(datetime.now(timezone.utc).timestamp()) + VOTE_WINDOW_SECONDS
        view = VoteView(self.service, target_id=member.id)

        # Passer la variable de la mention du rôle Confiance dans le template
        content = VOTE_MESSAGE_TEMPLATE.format(
            user=member.mention,
            required=APPROVALS_REQUIRED,
            expires_at=expires_at_ts,
            current=0,
            confiance_mention=confiance_mention  # Ajouter la mention du rôle Confiance dans le message
        )

        try:
            msg = await validation_channel.send(content, view=view)
            self.service.add_pending_vote(
                guild.id,
                member.id,
                yes=set(),
                no=set(),
                message_id=msg.id,
                channel_id=validation_channel.id,
                expires_at_ts=expires_at_ts
            )
        except Exception as e:
            await self.service.logger.error(f"Erreur lors de l'envoi du message de vote pour {member.mention}: {str(e)}")


async def setup(bot):
    await bot.add_cog(Verification(bot))
    print("Cog Verification chargé avec succès.")

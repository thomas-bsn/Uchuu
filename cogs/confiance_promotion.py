import discord
from discord.ext import commands, tasks
from datetime import datetime, timezone
from bot_settings import BotSettings
from services.confiance_service import ConfiancePromotionService

VOTE_PROMOTION_MESSAGE_TEMPLATE = (
    "🔐 **Nouveau vote de promotion**\n\n"
    "Utilisateur: {user}\n"
    "Votes requis: {required}\n"
    "Expiration: <t:{expires_at}:R>\n"
    "Votes actuels: {current}/{required}\n\n"

    "**Rôle Confiance** : {confiance_mention}\n\n"
)


class ConfiancePromotionCog(commands.Cog):
    def __init__(self, bot, settings: BotSettings):
        self.bot = bot
        self.settings = settings
        self.service = ConfiancePromotionService(bot, settings)

    async def cog_load(self):
        self.service.check_expired_votes.start()

    async def cog_unload(self):
        self.service.check_expired_votes.cancel()

    @tasks.loop(hours=24)  # Vérifie tous les jours
    async def check_promotion(self):
        """Vérifie tous les membres avec le rôle 'Membre' pour promotion automatique au rôle Confiance"""
        await self.bot.wait_until_ready()
        now = int(datetime.now(timezone.utc).timestamp())
        guild = self.bot.get_guild(self.settings.ids.guild_id)
        logs_channel = guild.get_channel(self.settings.ids.channel_logs_id)

        if guild is None or logs_channel is None:
            return  # On ne peut pas procéder sans la guild ou le channel de logs

        for member in guild.members:
            # On ignore les bots et ceux qui n'ont pas le rôle 'Membre'
            # on print les roles des membres
            
            if member.bot:
                continue  # Si c'est un bot, on passe au membre suivant

            # Ajout de print pour voir les rôles

            # Vérifie si le membre a bien le rôle "Membre"
            if self.settings.ids.role_membre_id not in [role.id for role in member.roles]:
                continue  # Si ce n'est pas un membre (n'a pas le rôle 'Membre'), on passe au suivant


            join_time = int(member.joined_at.timestamp())
            days_since_join = (now - join_time) // 86400  # Convertir en jours

            if days_since_join >= self.settings.votes.confiance_eligibility_days:
                # Le membre a dépassé le seuil de jours, créer un vote pour la promotion
                await self.create_promotion_vote(guild, member)

    async def create_promotion_vote(self, guild, member):
        """Crée un vote automatique pour promouvoir le membre au rôle Confiance"""
        # Vérification des rôles et du canal de validation
        validation_channel = guild.get_channel(self.settings.ids.channel_validation_id)
        if not validation_channel:
            return

        # Récupérer le rôle "Confiance"
        confiance_role = guild.get_role(self.settings.ids.role_confiance_id)  # Mentionner le rôle Confiance
        if confiance_role is None:
            return  # Si le rôle Confiance n'existe pas, on arrête l'exécution

        # Créer la mention dynamique du rôle Confiance
        confiance_mention = confiance_role.mention  # Cela ajoute la mention dynamique du rôle

        # Créer le message de vote
        expires_at_ts = int(datetime.now(timezone.utc).timestamp()) + self.settings.votes.confiance_window_seconds

        # Passer la variable de la mention du rôle Confiance dans le template
        content = VOTE_PROMOTION_MESSAGE_TEMPLATE.format(
            user=member.mention,
            required=self.settings.votes.approvals_required,
            expires_at=expires_at_ts,
            current=0,
            confiance_mention=confiance_mention  # Ajouter la mention du rôle Confiance dans le message
        )

        try:
            msg = await validation_channel.send(content)  # sans bouton : remplacé par le module Vote (#11)
            # Ajouter le vote en attente
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
            await self.service.gateway.log(f"❌ Erreur lors de la création du vote pour {member.mention}: {str(e)}")


    @commands.Cog.listener()
    async def on_ready(self):
        """Log du bot lorsqu'il est prêt et que le cog est chargé."""
        print(f"{self.bot.user} est prêt et vérifie les membres pour la promotion au rôle Confiance.")

# Enregistrer le cog
async def setup(bot):
    await bot.add_cog(ConfiancePromotionCog(bot, bot.settings))
    print("Cog de promotion Confiance chargé avec succès.")

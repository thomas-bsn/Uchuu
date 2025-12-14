from datetime import datetime, timedelta, timezone
import discord
from .config import ROLE_CONFIANCE_ID, ACTIVITY_THRESHOLD, MIN_MEMBERSHIP_DAYS, CHANNEL_LOGS_ID, ROLE_INVITE_ID, ROLE_MEMBRE_ID
from .activity import ActivityTracker

class PromotionService:
    def __init__(self, bot, store):
        self.bot = bot
        self.store = store
        self.activity_tracker = ActivityTracker(bot)
        self.logs_channel = bot.get_channel(CHANNEL_LOGS_ID)

    async def check_and_promote(self, member: discord.Member):
        """Vérifie si un membre peut être promu au rôle 'Confiance'"""
        
        # Critère 1 : Ancienneté (7 jours minimum) 
        if (datetime.now(timezone.utc) - member.joined_at).days < MIN_MEMBERSHIP_DAYS:
            return f"{member.display_name} n'a pas assez d'ancienneté."

        # Critère 2 : Activité A REGARDER AVEC LE BOT MEE6
        # Si tu veux intégrer le check avec Mee6 pour l'ancienneté, tu devrais utiliser son API ou son système de points d'ancienneté.
        # Par exemple, tu pourrais récupérer la date d'adhésion du membre et vérifier si elle dépasse 7 jours.
        messages_sent = await self.activity_tracker.get_user_activity(member)
        

        # Promouvoir le membre au rôle 'Confiance'
        confiance_role = member.guild.get_role(ROLE_CONFIANCE_ID)
        invite_role = member.guild.get_role(ROLE_INVITE_ID)
        membre_role = member.guild.get_role(ROLE_MEMBRE_ID)  # Le rôle "Membre" que tu veux retirer après la promotion.

        if confiance_role:
            # Ajouter le rôle 'Confiance'
            await member.add_roles(confiance_role, reason="Promotion au rôle Confiance")
            
            # Retirer le rôle 'Invite' si présent
            if invite_role in member.roles:
                await member.remove_roles(invite_role, reason="Retrait du rôle Invite après promotion")
            
            # Retirer le rôle 'Membre' après promotion
            if membre_role in member.roles:
                await member.remove_roles(membre_role, reason="Retrait du rôle Membre après promotion")

            # Envoi d'un message de log dans le channel de logs
            await self.logs_channel.send(f"{member.display_name} a été promu au rôle 'Confiance'.")
            
            return f"{member.display_name} a été promu au rôle 'Confiance'."
        else:
            return "Le rôle Confiance n'est pas disponible."


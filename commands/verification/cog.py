import discord
from discord.ext import commands
from datetime import datetime, timezone
from .store import Store
from .service import VerificationService
from .scheduler import ExpiryScheduler
from .tasks import TaskScheduler
from .views import VoteView
from .config import *

class Verification(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.store = Store()
        self.pending_votes = {}
        self.service = VerificationService(bot, self.store, self.pending_votes)
        self.scheduler = ExpiryScheduler(self.service)
        self.task_scheduler = TaskScheduler(bot, self.store)
        self.task_scheduler.promote_trusted_members.start()

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.guild.id != GUILD_ID:
            return

        guild = member.guild
        invite_role = guild.get_role(ROLE_INVITE_ID)
        logs_channel = guild.get_channel(CHANNEL_LOGS_ID)
        validation_channel = guild.get_channel(CHANNEL_VALIDATION_ID)

        if invite_role is None or validation_channel is None:
            if logs_channel:
                await logs_channel.send("❌ [verification] Rôle Invité ou salon validation introuvable.")
            return

        try:
            await member.add_roles(invite_role, reason="New member: assign Invité")
        except discord.Forbidden:
            if logs_channel:
                await logs_channel.send(
                    f"❌ [verification] Forbidden: impossible d'ajouter Invité à {member.mention}. "
                    "Hiérarchie rôles ou permissions bot."
                )
            return
        except Exception as e:
            if logs_channel and DEBUG:
                await logs_channel.send(f"❌ [verification] Erreur add_roles: `{type(e).__name__}: {e}`")
            return

        expires_at_ts = int(datetime.now(timezone.utc).timestamp()) + VOTE_WINDOW_SECONDS
        view = VoteView(self.service, target_id=member.id)  # Changer self par self.service pour l'appel du service

        content = VOTE_MESSAGE_TEMPLATE.format(
            user=member.mention,
            required=APPROVALS_REQUIRED,
            expires_at=expires_at_ts,
            current=0,
        )

        try:
            # Envoi du message avec le bouton de vote et enregistrement du message_id
            msg = await validation_channel.send(content, view=view)
            
            # Sauvegarder le message_id avec l'état du vote
            self.pending_votes[(guild.id, member.id)] = {
                "yes": set(),
                "no": set(),
                "message_id": msg.id,  # Assure-toi que le message_id est bien stocké
                "channel_id": validation_channel.id,
                "expires_at_ts": expires_at_ts,
            }
            
            print(f"Message ID créé : {msg.id}")  # Ajout d'un log pour vérifier le message_id
        except Exception as e:
            if logs_channel and DEBUG:
                await logs_channel.send(f"❌ [verification] Erreur création vote msg: `{type(e).__name__}: {e}`")
            return

        # Logs de création du vote
        if logs_channel:
            now_ts = int(datetime.now(timezone.utc).timestamp())
            await logs_channel.send(
                "✅ [verification] Nouveau vote créé\n"
                f"- User: {member.mention} ({member.id})\n"
                f"- Expire: <t:{expires_at_ts}:R>\n"
                f"- Date: <t:{now_ts}:F>"
            )

async def setup(bot):
    await bot.add_cog(Verification(bot))
    print("Extension Verification chargée avec succès.")

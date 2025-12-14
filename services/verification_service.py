from datetime import datetime, timezone
from discord.ext import tasks
import discord
from config import APPROVALS_REQUIRED, ROLE_INVITE_ID, ROLE_MEMBRE_ID, CHANNEL_LOGS_ID, VOTE_WINDOW_SECONDS
from utils.logger import Logger

class VerificationService:
    def __init__(self, bot):
        self.bot = bot
        self.pending_votes = {}
        self.logger = Logger(bot)
        self.check_expired_votes.start()

    def add_pending_vote(self, guild_id, target_id, yes, no, message_id, channel_id, expires_at_ts):
        """Ajoute un vote en attente"""
        self.pending_votes[(guild_id, target_id)] = {
            "yes": yes,
            "no": no,
            "message_id": message_id,
            "channel_id": channel_id,
            "expires_at_ts": expires_at_ts
        }

    async def handle_vote(self, guild, target_id, voter_id, vote_yes: bool) -> str:
        """Gère l'enregistrement du vote et vérifie si le seuil est atteint"""
        key = (guild.id, target_id)
        state = self.pending_votes.get(key)
        if not state:
            return "Le vote a expiré."

        yes, no = state["yes"], state["no"]

        # Mise à jour du vote
        if vote_yes:
            no.discard(voter_id)
            yes.add(voter_id)
        else:
            yes.discard(voter_id)
            no.add(voter_id)

        # Persist l'état mis à jour
        # self.store.persist_pending(guild.id, target_id, yes=yes, no=no, ...)

        # Vérifie le statut du vote et détermine si le membre doit être promu ou refusé
        result = await self.check_vote_status(state, guild, target_id)

        # Si le vote est terminé, supprime-le de la liste des votes en attente
        if result in ["✅ Validé", "❌ Refusé"]:
            self.pending_votes.pop(key, None)  # Supprimer le vote une fois qu'il est terminé

            # Supprimer le message du vote
            channel = self.bot.get_channel(state["channel_id"])
            message = await channel.fetch_message(state["message_id"])  # Récupérer le message par son ID
            if message:
                await message.delete()  # Supprimer le message du vote

        return result


    async def check_vote_status(self, state, guild, target_id):
        """Vérifie l'état du vote et effectue les actions nécessaires"""
        yes_count = len(state["yes"])

        # Si le nombre de votes "oui" est suffisant pour approuver
        if yes_count >= APPROVALS_REQUIRED:
            await self.approve_member(guild, target_id, state["yes"])  # Passer les approvers
            return "✅ Validé"

        return "Le vote est en cours, en attente de plus de votes."

    @tasks.loop(seconds=10)  # Vérifie toutes les 60 secondes
    async def check_expired_votes(self):
        """Vérifie les votes expirés toutes les 60 secondes."""
        now = int(datetime.now(timezone.utc).timestamp())  # Heure actuelle
        to_expire = []

        # Cherche les votes expirés
        for (guild_id, target_id), state in list(self.pending_votes.items()):
            expires_at = state["expires_at_ts"]
            # Compare l'expiration du vote avec le seuil de temps
            if expires_at and now >= expires_at:
                to_expire.append((guild_id, target_id))

        for guild_id, target_id in to_expire:
            await self.expire_member(guild_id, target_id)


    async def expire_member(self, guild_id: int, user_id: int):
        """Expire un membre et effectue un kick si nécessaire"""
        print("Expiration du membre...")
        key = (guild_id, user_id)
        state = self.pending_votes.pop(key, None)
        if state is None:
            return

        yes_ids = state.get("yes", set())
        yes_mentions = ", ".join(f"<@{uid}>" for uid in yes_ids) or "aucun"

        guild = self.bot.get_guild(guild_id)

        # Expirer le membre (kick), mais d'abord vérifier si le rôle invité a été supprimé
        member = guild.get_member(user_id)
        if member:
            invite_role = guild.get_role(ROLE_INVITE_ID)

            # Vérifier si le rôle "invité" a été retiré
            if invite_role and invite_role not in member.roles:
                # Loggue l'événement dans le canal des logs via Logger
                await self.logger.info(
                    f"Rôle 'Invité' retiré avant expiration ou refus pour l'utilisateur <@{user_id}> ({user_id})."
                )
                return  # Bypass le kick

            # Si le rôle invité n'a pas été retiré, procéder au kick comme prévu
            try:
                await member.send("Votre invitation a expiré et vous avez été expulsé.")
                await guild.kick(member, reason="Verification expired")
            except Exception as e:
                await self.logger.error(f"Erreur lors de l'expulsion de {member.mention} ({user_id}): {str(e)}")

        # Log des résultats dans #logs via Logger
        await self.logger.info(
            f"⏱️ **Kick automatique (expiration)**\n"
            f"👤 Utilisateur : <@{user_id}> ({user_id})\n"
            f"👍 Pour ({len(yes_ids)}) : {yes_mentions}\n"
        )

        # Supprimer le message du vote si le rôle n'a pas été retiré
        try:
            # Récupérer le message de vote via son message_id
            channel = self.bot.get_channel(state["channel_id"])
            message = await channel.fetch_message(state["message_id"])  # Récupérer le message par son ID
            if message:
                await message.delete()  # Supprimer le message du vote
                print(f"Message du vote supprimé pour l'utilisateur {user_id}")
        except discord.NotFound:
            print(f"Message du vote non trouvé pour l'utilisateur {user_id}")
        except Exception as e:
            await self.logger.error(f"Erreur lors de la suppression du message de vote : {str(e)}")

    async def approve_member(self, guild, user_id: int, approvers_ids: set = None):
        """Retire le rôle 'Invité' et donne le rôle 'Membre' à l'utilisateur"""
        member = guild.get_member(user_id)
        if member is None:
            return

        invite_role = guild.get_role(ROLE_INVITE_ID)
        membre_role = guild.get_role(ROLE_MEMBRE_ID)
        logs_channel = guild.get_channel(CHANNEL_LOGS_ID)

        if membre_role is None:
            if logs_channel:
                await logs_channel.send("❌ [verification] ROLE_MEMBRE_ID introuvable.")
            return

        # Vérifie si le rôle invité est toujours là
        if invite_role and invite_role in member.roles:
            try:
                await member.remove_roles(invite_role, reason="Invitation approuvée.")
                await member.add_roles(membre_role, reason="Membre validé après approbation.")
                
                # Logguer dans #logs
                approvers_mentions = ", ".join(f"<@{uid}>" for uid in approvers_ids) if approvers_ids else "Aucun"
                await self.logger.log_promotion(member, approvers_mentions)
                return f"✅ **Invitation approuvée** — {member.mention} a été promu au rôle 'Membre'."

            except discord.Forbidden:
                await self.logger.error(f"Impossible de promouvoir {member.mention} ({user_id}).")
            except Exception as e:
                await self.logger.error(f"Erreur lors de l'activation du rôle pour {member.mention} ({user_id}): {str(e)}")
                return None

        return None

from datetime import datetime, timezone
import discord
from discord.ext import tasks
from discord_config import APPROVALS_REQUIRED, ROLE_INVITE_ID, ROLE_MEMBRE_ID, ROLE_CONFIANCE_ID, CHANNEL_LOGS_ID, VOTE_WINDOW_SECONDS
from utils.logger import Logger

class ConfiancePromotionService:
    def __init__(self, bot):
        self.bot = bot
        self.pending_votes = {}  # Dictionnaire pour les votes en attente
        self.logger = Logger(bot)  # Logger pour enregistrer les événements

    def add_pending_vote(self, guild_id, target_id, yes, no, message_id, channel_id, expires_at_ts):
        """Ajoute un vote en attente"""
        self.pending_votes[(guild_id, target_id)] = {
            "yes": yes,
            "no": no,
            "message_id": message_id,
            "channel_id": channel_id,
            "expires_at_ts": expires_at_ts
        }

    @tasks.loop(seconds=10)  # Vérifie toutes les 10 secondes
    async def check_expired_votes(self):
        """Vérifie les votes expirés et supprime ceux qui n'ont pas été décidés."""
        await self.bot.wait_until_ready()
        now = int(datetime.now(timezone.utc).timestamp())  # Temps actuel
        to_remove = []  # Liste pour les votes expirés sans décision

        # Parcours des votes en attente
        for (guild_id, target_id), state in list(self.pending_votes.items()):
            expires_at = state["expires_at_ts"]
            if now >= expires_at + VOTE_WINDOW_SECONDS:  # Si le vote a expiré
                to_remove.append((guild_id, target_id))  # Ajouter à la liste des votes expirés

        # Supprimer les votes expirés
        for guild_id, target_id in to_remove:
            await self.remove_expired_vote(guild_id, target_id)

    @check_expired_votes.error
    async def check_expired_votes_error(self, exc):
        await self.logger.error(f"❌ [promotion] check_expired_votes crashed: {exc!r}")

    async def remove_expired_vote(self, guild_id: int, target_id: int):
        """Supprime un vote expiré et le message associé."""
        key = (guild_id, target_id)
        state = self.pending_votes.pop(key, None)  # Récupérer et supprimer le vote expiré
        if not state:
            return  # Si le vote n'existe pas, rien à faire

        # Récupérer le canal et le message du vote
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return

        channel = guild.get_channel(state["channel_id"])
        if not channel:
            return

        try:
            message = await channel.fetch_message(state["message_id"])
            if message:
                await message.delete()  # Supprimer le message de vote expiré

            # Loggue l'expiration du vote dans le canal des logs
            await self.logger.info(f"⏱️ [promotion] Vote expiré et supprimé pour {target_id} dans {guild.name}.")
        except Exception as e:
            await self.logger.error(f"❌ [promotion] Erreur lors de la suppression du vote expiré : {str(e)}")

    async def handle_vote(self, guild, target_id, voter_id, vote_yes: bool) -> str:
        """Gère l'enregistrement du vote de promotion et vérifie si le seuil est atteint."""
        key = (guild.id, target_id)
        state = self.pending_votes.get(key)
        if not state:
            return "Le vote a expiré."
        
        yes, no = state["yes"], state["no"]

        # Mise à jour des votes
        if vote_yes:
            no.discard(voter_id)
            yes.add(voter_id)
        else:
            yes.discard(voter_id)
            no.add(voter_id)

        # Persist l'état mis à jour
        self.pending_votes[key] = {
            "yes": yes,
            "no": no,
            "message_id": state["message_id"],
            "channel_id": state["channel_id"],
            "expires_at_ts": state["expires_at_ts"]
        }

        # Vérifie le statut du vote
        return await self.check_vote_status(state, guild, target_id)

    async def check_vote_status(self, state, guild, target_id):
        """Vérifie l'état du vote et effectue les actions nécessaires."""
        yes_count = len(state["yes"])

        # Si le nombre de votes "oui" est suffisant pour approuver
        if yes_count >= APPROVALS_REQUIRED:
            await self.promote_to_confiance(guild, target_id, state["yes"])  # Passer les approvers
            return "✅ Validé"
        
        # Si le vote n'atteint pas le seuil requis
        if len(state["yes"]) + len(state["no"]) >= APPROVALS_REQUIRED:
            return "Le vote est terminé, mais il n'a pas atteint le quota nécessaire."
        
        return "Le vote est en cours, en attente de plus de votes."

    async def promote_to_confiance(self, guild, user_id: int, approvers_ids: set):
            """Promouvoir le membre au rôle 'Confiance'."""
            print(f"Promoting user {user_id} to Confiance")
            member = guild.get_member(user_id)
            if member is None:
                print(f"User {user_id} not found")
                return

            membre_role = guild.get_role(ROLE_MEMBRE_ID)
            confiance_role = guild.get_role(ROLE_CONFIANCE_ID)
            logs_channel = guild.get_channel(CHANNEL_LOGS_ID)

            if confiance_role is None:
                if logs_channel:
                    await logs_channel.send("❌ [promotion] ROLE_CONFIANCE_ID introuvable.")
                return

            # Vérifie si le membre a le rôle 'Membre'
            if membre_role and membre_role in member.roles:
                try:
                    await member.remove_roles(membre_role, reason="Promotion à Confiance")
                    await member.add_roles(confiance_role, reason="Promotion au rôle Confiance après validation.")
                    
                    # Logguer la promotion dans #logs
                    approvers_mentions = ", ".join(f"<@{uid}>" for uid in approvers_ids) if approvers_ids else "Aucun"
                    await self.logger.log_promotion(member, approvers_mentions, role_promoted="Confiance")

                    # Supprimer le vote une fois qu'il est validé
                    key = (guild.id, user_id)
                    state = self.pending_votes.pop(key, None)
                    if state:
                        # Supprimer le message du vote
                        channel = self.bot.get_channel(state["channel_id"])
                        message = await channel.fetch_message(state["message_id"])  # Récupérer le message par son ID
                        if message:
                            await message.delete()  # Supprimer le message du vote

                    return f"✅ **Promotion réussie** — {member.mention} a été promu au rôle 'Confiance'."

                except discord.Forbidden:
                    if logs_channel:
                        await logs_channel.send(f"❌ [promotion] Forbidden: impossible de promouvoir {member.mention}.")
                except Exception as e:
                    if logs_channel:
                        await logs_channel.send(f"❌ [promotion] Erreur lors de la promotion: `{str(e)}`")
                    return None

            return None
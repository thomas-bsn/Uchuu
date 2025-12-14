from datetime import datetime, timezone
import discord
from .store import Store
from .config import *

class VerificationService:
    def __init__(self, bot, store: Store, pending_votes: dict):
        self.bot = bot
        self.store = store
        self.pending_votes = pending_votes

    async def handle_vote(self, guild, target_id, voter_id, vote_yes: bool) -> str:
        key = (guild.id, target_id)
        state = self.pending_votes.get(key)
        if not state:
            return "Vote expiré."

        # Mise à jour du vote
        self.update_vote_count(state, voter_id, vote_yes)

        # Persistence de l'état mis à jour
        self.store.persist_pending(
            guild.id,
            target_id,
            yes=state["yes"],
            no=state["no"],
            message_id=state["message_id"],
            channel_id=state["channel_id"],
            expires_at_ts=state["expires_at_ts"]
        )

        # Vérification du statut du vote
        return await self.check_vote_status(state, guild, target_id)

    def update_vote_count(self, state, voter_id, vote_yes):
        """Met à jour les votes pour le membre"""
        yes, no = state["yes"], state["no"]
        if vote_yes:
            no.discard(voter_id)
            yes.add(voter_id)
        else:
            yes.discard(voter_id)
            no.add(voter_id)

    async def check_vote_status(self, state, guild, target_id):
        """Vérifie l'état des votes et effectue les actions nécessaires"""
        yes_count = len(state["yes"])

        # Si le nombre de votes "oui" atteint le seuil d'approbation
        if yes_count >= APPROVALS_REQUIRED:
            # Ferme le vote, approuve le membre et met à jour le message
            return await self.approve_member(guild, target_id, state["message_id"], state["channel_id"])

        return "Le vote est en cours, en attente de plus de votes."

    async def process_expirations(self, now: int):
        """Gère les expirations des votes"""
        to_expire = []

        # Vérifie si les votes ont expiré
        for (guild_id, user_id), state in list(self.pending_votes.items()):
            expires_at = state.get("expires_at_ts")
            if expires_at and now >= expires_at + KICK_GRACE_SECONDS:
                to_expire.append((guild_id, user_id))

        # Expirer les votes
        for guild_id, user_id in to_expire:
            await self.expire_member(guild_id, user_id)
    
    async def expire_member(self, guild_id: int, user_id: int):
        """Expire un membre si le seuil d'approbation n'est pas atteint"""
        key = (guild_id, user_id)
        state = self.pending_votes.pop(key, None)
        if not state:
            return

        yes_ids = state.get("yes", set())
        no_ids = state.get("no", set())

        # S'assurer que les mentions sont définies
        yes_mentions = ", ".join(f"<@{uid}>" for uid in yes_ids) if yes_ids else "aucun"
        no_mentions = ", ".join(f"<@{uid}>" for uid in no_ids) if no_ids else "aucun"

        guild = self.bot.get_guild(guild_id)
        logs_channel = guild.get_channel(state["channel_id"])

        # Si les mentions sont valides, on envoie les logs
        if logs_channel:
            await logs_channel.send(
                f"⏱️ **Kick automatique (expiration)**\n"
                f"👤 Utilisateur : <@{user_id}> ({user_id})\n"
                f"👍 Pour ({len(yes_ids)}) : {yes_mentions}\n"
                f"👎 Contre ({len(no_ids)}) : {no_mentions}\n"
            )

    async def approve_member(self, guild, user_id: int, message_id: int, channel_id: int):
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

        # Si le membre a le rôle "Invité", on le retire et on lui donne "Membre"
        if invite_role and invite_role in member.roles:
            try:
                await member.remove_roles(invite_role, reason="Invitation approuvée.")
                await member.add_roles(membre_role, reason="Membre validé après approbation.")
                
                # Logguer l'action dans le canal #logs
                if logs_channel:
                    await logs_channel.send(
                        f"✅ [verification] Rôle 'Invité' retiré et rôle 'Membre' ajouté à {member.mention} ({user_id})"
                    )

                # Mettre à jour le message avec l'état du vote et désactiver les boutons
                message = await guild.get_channel(channel_id).fetch_message(message_id)
                if message:
                    # Mise à jour du message avec un contenu final et désactivation des boutons
                    await message.edit(content="✅ **Invitation approuvée**. Le rôle 'Membre' a été attribué.", view=None)

                # Supprimer le vote de la liste en attente
                self.pending_votes.pop((guild.id, user_id), None)

            except discord.Forbidden:
                if logs_channel:
                    await logs_channel.send(
                        f"❌ [verification] Forbidden: impossible de promouvoir {member.mention}. "
                        "Hiérarchie rôles ou permissions bot."
                    )
            except Exception as e:
                if logs_channel and DEBUG:
                    await logs_channel.send(f"❌ [verification] Erreur lors de l'activation du rôle : `{type(e).__name__}: {e}`")

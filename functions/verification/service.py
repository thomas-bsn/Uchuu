from datetime import datetime, timezone
from .store import Store
from .config import KICK_GRACE_SECONDS, APPROVALS_REQUIRED, DENY_REQUIRED, DEBUG, ROLE_INVITE_ID, ROLE_MEMBRE_ID, CHANNEL_LOGS_ID, VOTE_APPROVED_MESSAGE
import discord

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

        yes, no = state["yes"], state["no"]

        if vote_yes:
            no.discard(voter_id)
            yes.add(voter_id)
        else:
            yes.discard(voter_id)
            no.add(voter_id)

        self.store.persist_pending(
            guild.id,
            target_id,
            yes=yes,
            no=no,
            message_id=state["message_id"],
            channel_id=state["channel_id"],
            expires_at_ts=state["expires_at_ts"]
        )

        if len(yes) >= APPROVALS_REQUIRED:
            await self.approve_member(guild, target_id, voter_id)
            return "✅ Validé"

        if DENY_REQUIRED and len(no) >= DENY_REQUIRED:
            await self.deny_member(guild, target_id, voter_id)
            return "❌ Refusé"

        return "Vote enregistré"

    async def process_expirations(self, now: int):
        """Cette méthode gère les expirations des votes."""
        to_expire = []

        # Cherche les votes expirés et ajoutés à la liste des éléments à expirer
        for (guild_id, user_id), state in list(self.pending_votes.items()):
            expires_at = state.get("expires_at_ts")
            if expires_at and now >= expires_at + KICK_GRACE_SECONDS:
                to_expire.append((guild_id, user_id))

        # Traiter les expirations
        for guild_id, user_id in to_expire:
            await self.expire_member(guild_id, user_id)

    async def expire_member(self, guild_id: int, user_id: int):
        """Expire un membre (kick si nécessaire)"""
        key = (guild_id, user_id)
        state = self.pending_votes.pop(key, None)
        if state is None:
            return

        yes_ids = state.get("yes", set())
        no_ids = state.get("no", set())

        yes_mentions = ", ".join(f"<@{uid}>" for uid in yes_ids) or "aucun"
        no_mentions = ", ".join(f"<@{uid}>" for uid in no_ids) or "aucun"

        guild = self.bot.get_guild(guild_id)
        logs_channel = guild.get_channel(state["channel_id"])

        # Expirer le membre (kick), mais d'abord vérifier si le rôle invité a été supprimé
        member = guild.get_member(user_id)
        if member:
            invite_role = guild.get_role(ROLE_INVITE_ID)
            
            # Vérifier si le rôle "invité" a été retiré
            if invite_role and invite_role not in member.roles:
                # Si le rôle invité est retiré, bypass le kick et loggue l'événement
                if logs_channel:
                    now_ts = int(datetime.now(timezone.utc).timestamp())
                    await logs_channel.send(
                        f"⚠️ [verification] Rôle 'Invité' retiré avant expiration ou refus\n"
                        f"👤 Utilisateur : <@{user_id}> ({user_id})\n"
                        f"🎯 Rôle 'Invité' retiré avant kick\n"
                        f"🕒 Date : <t:{now_ts}:F>"
                    )
                return  # Bypass le kick

            # Si le rôle invité n'a pas été retiré, procéder au kick comme prévu
            try:
                await member.send("Votre invitation a expiré et vous avez été expulsé.")
                await guild.kick(member, reason="Verification expired")
            except Exception as e:
                if logs_channel and DEBUG:
                    await logs_channel.send(f"❌ [verification] Erreur kick (expire): `{type(e).__name__}: {e}`")

        # Log des résultats dans #logs
        if logs_channel:
            now_ts = int(datetime.now(timezone.utc).timestamp())
            await logs_channel.send(
                f"⏱️ **Kick automatique (expiration)**\n"
                f"👤 Utilisateur : <@{user_id}> ({user_id})\n"
                f"👍 Pour ({len(yes_ids)}) : {yes_mentions}\n"
                f"👎 Contre ({len(no_ids)}) : {no_mentions}\n"
                f"🕒 Date : <t:{now_ts}:F>"
            )

    async def approve_member(self, guild, user_id: int, approved_by: int | None = None):
        """Accorde le rôle de membre à l'utilisateur"""
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
                await member.remove_roles(invite_role, reason="Approved: remove Invité")
                await member.add_roles(membre_role, reason="Approved: add Membre")
            except discord.Forbidden:
                if logs_channel:
                    await logs_channel.send(
                        f"❌ [verification] Forbidden: impossible de promouvoir {member.mention}. "
                        "Hiérarchie rôles ou permissions bot."
                    )
                return
            except Exception as e:
                if logs_channel and DEBUG:
                    await logs_channel.send(f"❌ [verification] Erreur promote: `{type(e).__name__}: {e}`")
                return
        else:
            # Si le rôle "invité" a été retiré avant la validation, loggue l'événement
            if logs_channel:
                now_ts = int(datetime.now(timezone.utc).timestamp())
                await logs_channel.send(
                    f"⚠️ [verification] Rôle 'Invité' retiré avant approbation\n"
                    f"👤 Utilisateur : <@{user_id}> ({user_id})\n"
                    f"🎯 Rôle 'Invité' retiré avant validation\n"
                    f"🕒 Date : <t:{now_ts}:F>"
                )
            return

        key = (guild.id, user_id)
        state = self.pending_votes.pop(key, None)
        if state and "message" in state:
            try:
                await state["message"].edit(content=VOTE_APPROVED_MESSAGE, view=None)
            except Exception:
                pass

        if logs_channel:
            approver_txt = f"<@{approved_by}>" if approved_by else "inconnu"
            now_ts = int(datetime.now(timezone.utc).timestamp())
            await logs_channel.send(
                "✅ [verification] Promotion\n"
                f"- User: {member.mention} ({member.id})\n"
                f"- Par: {approver_txt}\n"
                f"- Date: <t:{now_ts}:F>"
            )

    async def deny_member(self, guild, user_id: int, denied_by: int | None = None):
        """Refuse un membre et expulse-le"""
        key = (guild.id, user_id)
        state = self.pending_votes.pop(key, None)
        logs_channel = guild.get_channel(CHANNEL_LOGS_ID)

        if state is None:
            return

        yes_ids = state.get("yes", set())
        no_ids = state.get("no", set())
        yes_mentions = ", ".join(f"<@{uid}>" for uid in yes_ids) or "aucun"
        no_mentions = ", ".join(f"<@{uid}>" for uid in no_ids) or "aucun"
        now_ts = int(datetime.now(timezone.utc).timestamp())

        member = guild.get_member(user_id)
        if member:
            # Vérifie si le rôle invité est toujours là
            invite_role = guild.get_role(ROLE_INVITE_ID)
            if invite_role and invite_role in member.roles:
                try:
                    await member.send("Votre invitation a été refusée et vous avez été expulsé.")
                    await guild.kick(member, reason="Verification denied by vote")
                except discord.Forbidden:
                    if logs_channel:
                        await logs_channel.send(
                            f"❌ [verification] Forbidden: impossible de kick (deny) {member.mention}."
                        )
                    # remettre l'état si kick impossible
                    if state is not None:
                        self.pending_votes[key] = state
                    return
                except Exception as e:
                    if logs_channel and DEBUG:
                        await logs_channel.send(f"❌ [verification] Erreur kick deny: `{type(e).__name__}: {e}`")
                    if state is not None:
                        self.pending_votes[key] = state
                    return
            else:
                # Si le rôle "invité" a été retiré avant le refus, loggue l'événement
                if logs_channel:
                    await logs_channel.send(
                        f"⚠️ [verification] Rôle 'Invité' retiré avant refus\n"
                        f"👤 Utilisateur : <@{user_id}> ({user_id})\n"
                        f"🎯 Rôle 'Invité' retiré avant refus\n"
                        f"🕒 Date : <t:{now_ts}:F>"
                    )
                return

        # Logs complets dans #logs
        if logs_channel:
            denier_txt = f"<@{denied_by}>" if denied_by else "inconnu"
            await logs_channel.send(
                "❌ **Kick automatique (refus)**\n"
                f"👤 Utilisateur : <@{user_id}> ({user_id})\n"
                f"👍 Pour ({len(yes_ids)}) : {yes_mentions}\n"
                f"👎 Contre ({len(no_ids)}) : {no_mentions}\n"
                f"🙅 Déclenché par : {denier_txt}\n"
                f"🕒 Date : <t:{now_ts}:F>"
            )

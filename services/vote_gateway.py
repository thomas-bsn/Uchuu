"""Seam Discord du module Vote : tous ses effets passent par `VoteGateway`.

`DiscordVoteGateway` (prod) résout serveur, rôles et salons à l'appel, jamais au
chargement ; un objet absent ou une action refusée est loggé, jamais levé.
Le fake des tests vit dans tests/vote_fakes.py.
"""
from __future__ import annotations

import logging
from typing import Protocol

import discord

from services.vote_types import MemberInfo, MessageRef
from views.vote_button import vote_view

logger = logging.getLogger(__name__)


def _member_info(member) -> MemberInfo:
    joined = member.joined_at.timestamp() if member.joined_at else None
    return MemberInfo(member.id, frozenset(r.id for r in member.roles), bot=member.bot, joined_at=joined)


class VoteGateway(Protocol):
    async def member(self, member_id: int) -> MemberInfo | None: ...
    async def members(self) -> list[MemberInfo]:
        """Tous les membres du serveur (vide si le serveur est introuvable)."""
    async def add_role(self, member_id: int, role_id: int, reason: str) -> bool: ...
    async def remove_role(self, member_id: int, role_id: int, reason: str) -> bool: ...
    async def send_dm(self, member_id: int, content: str) -> bool: ...
    async def kick(self, member_id: int, reason: str) -> bool: ...
    async def post_vote(self, vote_id: int, content: str) -> MessageRef | None:
        """Poste le message de vote (bouton ✅ persistant) dans le salon de validation."""
    async def edit_vote(self, ref: MessageRef, content: str) -> None: ...
    async def delete_vote(self, ref: MessageRef) -> None: ...
    async def log(self, content: str) -> None:
        """Publie dans le salon de logs."""


class DiscordVoteGateway:
    """Adapter de prod sur le serveur GUILD_ID. Chaque appel résout ses objets Discord ;
    un objet absent ou une erreur Discord est loggé (salon de logs, sinon logging) et
    l'appel renvoie False / None au lieu de lever."""

    def __init__(self, bot, settings) -> None:
        self.bot = bot
        self.ids = settings.ids

    # --- résolution paresseuse ---
    async def _guild(self):
        guild = self.bot.get_guild(self.ids.guild_id)
        if guild is None:
            await self.log(f"❌ [votes] Serveur {self.ids.guild_id} (GUILD_ID) introuvable.")
        return guild

    async def _member(self, member_id: int):
        guild = await self._guild()
        if guild is None:
            return None, None
        return guild, guild.get_member(member_id)

    async def _role(self, guild, role_id: int):
        role = guild.get_role(role_id)
        if role is None:
            await self.log(f"❌ [votes] Rôle {role_id} introuvable.")
        return role

    async def _failed(self, action: str, error: Exception) -> bool:
        await self.log(f"❌ [votes] {action} : {error}")
        return False

    # --- VoteGateway ---
    async def member(self, member_id: int) -> MemberInfo | None:
        _, member = await self._member(member_id)
        if member is None:
            return None
        return _member_info(member)

    async def members(self) -> list[MemberInfo]:
        guild = await self._guild()
        return [] if guild is None else [_member_info(member) for member in guild.members]

    async def add_role(self, member_id: int, role_id: int, reason: str) -> bool:
        return await self._change_role(member_id, role_id, reason, add=True)

    async def remove_role(self, member_id: int, role_id: int, reason: str) -> bool:
        return await self._change_role(member_id, role_id, reason, add=False)

    async def _change_role(self, member_id: int, role_id: int, reason: str, *, add: bool) -> bool:
        guild, member = await self._member(member_id)
        if guild is None or member is None:
            return False
        role = await self._role(guild, role_id)
        if role is None:
            return False
        try:
            await (member.add_roles if add else member.remove_roles)(role, reason=reason)
            return True
        except discord.HTTPException as error:
            verb = "ajout" if add else "retrait"
            return await self._failed(f"{verb} du rôle {role_id} pour <@{member_id}> impossible", error)

    async def send_dm(self, member_id: int, content: str) -> bool:
        _, member = await self._member(member_id)
        if member is None:
            return False
        try:
            await member.send(content)
            return True
        except discord.HTTPException as error:
            return await self._failed(f"DM à <@{member_id}> impossible", error)

    async def kick(self, member_id: int, reason: str) -> bool:
        guild, member = await self._member(member_id)
        if member is None:
            return False
        try:
            await guild.kick(member, reason=reason)
            return True
        except discord.HTTPException as error:
            return await self._failed(f"kick de <@{member_id}> impossible", error)

    async def post_vote(self, vote_id: int, content: str) -> MessageRef | None:
        channel = self.bot.get_channel(self.ids.channel_validation_id)
        if channel is None:
            await self.log(f"❌ [votes] Salon de validation {self.ids.channel_validation_id} introuvable.")
            return None
        try:
            message = await channel.send(content, view=vote_view(vote_id))
        except discord.HTTPException as error:
            await self._failed(f"envoi du message du vote {vote_id} impossible", error)
            return None
        return MessageRef(channel.id, message.id)

    async def edit_vote(self, ref: MessageRef, content: str) -> None:
        await self._on_message(ref, "mise à jour", lambda message: message.edit(content=content))

    async def delete_vote(self, ref: MessageRef) -> None:
        await self._on_message(ref, "suppression", lambda message: message.delete())

    async def _on_message(self, ref: MessageRef, action: str, operation) -> None:
        channel = self.bot.get_channel(ref.channel_id)
        if channel is None:
            await self.log(f"❌ [votes] Salon {ref.channel_id} introuvable ({action} du message de vote).")
            return
        try:
            await operation(channel.get_partial_message(ref.message_id))
        except discord.NotFound:
            pass  # déjà supprimé à la main
        except discord.HTTPException as error:
            await self._failed(f"{action} du message de vote impossible", error)

    async def log(self, content: str) -> None:
        channel = self.bot.get_channel(self.ids.channel_logs_id)
        if channel is None:
            logger.warning("salon de logs %s introuvable ; log : %s", self.ids.channel_logs_id, content)
            return
        try:
            # Les mentions s'affichent (votants, cible) sans notifier personne.
            await channel.send(content, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            logger.exception("log Discord impossible : %s", content)

"""Politiques de vote : ce qui diffère entre les flux, au-dessus du module Vote."""
from __future__ import annotations

from bot_settings import CommunityIds, VoteSettings
from services.vote import mentions
from services.vote_gateway import VoteGateway
from services.vote_store import VoteRecord

KICK_DM_MESSAGE = (
    "Tu as été retiré du serveur.\n"
    "Raison : validation non obtenue dans le délai imparti.\n"
    "Serveur privé à intérêt commun."
)

INVITE_VOTE_TEMPLATE = (
    "🔐 **Nouvel invité**\n\n"
    "Utilisateur : {user}\n"
    "Votes : {current}/{required}\n"
    "Expiration : <t:{expires_at}:R>\n\n"
    "**Rôle Confiance** : {confiance}"
)


class InvitePolicy:
    """Invité → Membre : rôle Invité à l'ouverture, Membre au quorum, DM + kick à l'expiration."""

    kind = "invite"

    def __init__(self, ids: CommunityIds, votes: VoteSettings) -> None:
        self.ids = ids
        self.window_seconds = votes.invite_window_seconds

    async def on_open(self, gateway: VoteGateway, target_id: int) -> bool:
        return await gateway.add_role(target_id, self.ids.role_invite_id, "Nouvel arrivant : vote d'admission")

    def render(self, vote: VoteRecord, approvals_required: int) -> str:
        return INVITE_VOTE_TEMPLATE.format(
            user=f"<@{vote.target_id}>",
            current=len(vote.approvers),
            required=approvals_required,
            expires_at=int(vote.expires_at),
            confiance=f"<@&{self.ids.role_confiance_id}>",
        )

    async def on_approved(self, gateway: VoteGateway, vote: VoteRecord) -> str:
        target = vote.target_id
        await gateway.remove_role(target, self.ids.role_invite_id, "Admission approuvée")
        await gateway.add_role(target, self.ids.role_membre_id, "Admission approuvée")
        return (
            "✅ **Admission approuvée**\n"
            f"👤 Utilisateur : <@{target}> ({target})\n"
            f"👍 Pour ({len(vote.approvers)}) : {mentions(vote.approvers)}"
        )

    async def on_expired(self, gateway: VoteGateway, vote: VoteRecord) -> str:
        target = vote.target_id
        voters = f"👍 Pour ({len(vote.approvers)}) : {mentions(vote.approvers)}"
        member = await gateway.member(target)
        if member is None:
            return f"⏱️ **Vote d'admission expiré** — <@{target}> ({target}) a déjà quitté le serveur.\n{voters}"
        if self.ids.role_invite_id not in member.role_ids:
            return (
                f"⏱️ **Vote d'admission expiré** — rôle Invité retiré manuellement, "
                f"<@{target}> ({target}) n'est pas expulsé.\n{voters}"
            )
        await gateway.send_dm(target, KICK_DM_MESSAGE)
        kicked = await gateway.kick(target, "Admission non validée dans le délai")
        status = "Kick automatique (expiration)" if kicked else "Expiration : kick impossible"
        return f"⏱️ **{status}**\n👤 Utilisateur : <@{target}> ({target})\n{voters}"

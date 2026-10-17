"""Politiques de vote : ce qui diffère entre les flux, au-dessus du module Vote."""
from __future__ import annotations

from bot_settings import CommunityIds, VoteSettings
from services.vote import mentions
from services.vote_gateway import VoteGateway
from services.vote_store import VoteRecord
from services.vote_types import MemberInfo, VoteKind

DAY_SECONDS = 24 * 3600

KICK_DM_MESSAGE = (
    "Tu as été retiré du serveur.\n"
    "Raison : validation non obtenue dans le délai imparti.\n"
    "Serveur privé à intérêt commun."
)

VOTE_TEMPLATE = (
    "🔐 **{title}**\n\n"
    "{label} : {user}\n"
    "Votes : {current}/{required}\n"
    "Expiration : <t:{expires_at}:R>\n\n"
    "**Rôle Confiance** : {confiance}"
)


def voters_line(vote: VoteRecord) -> str:
    """Ligne des votants, commune à tous les logs de vote."""
    return f"👍 Pour ({len(vote.approvers)}) : {mentions(vote.approvers)}"


class _RenderedPolicy:
    """Rendu commun des messages de vote ; chaque politique fournit son titre et son libellé."""

    title: str
    target_label: str
    ids: CommunityIds

    def render(self, vote: VoteRecord, approvals_required: int) -> str:
        return VOTE_TEMPLATE.format(
            title=self.title,
            label=self.target_label,
            user=f"<@{vote.target_id}>",
            current=len(vote.approvers),
            required=approvals_required,
            expires_at=int(vote.expires_at),
            confiance=f"<@&{self.ids.role_confiance_id}>",
        )


class InvitePolicy(_RenderedPolicy):
    """Invité → Membre : rôle Invité à l'ouverture, Membre au quorum, DM + kick à l'expiration."""

    kind = VoteKind.INVITE
    title = "Nouvel invité"
    target_label = "Utilisateur"

    def __init__(self, ids: CommunityIds, votes: VoteSettings) -> None:
        self.ids = ids
        self.window_seconds = votes.invite_window_seconds

    def is_newcomer(self, member: MemberInfo) -> bool:
        journey = {self.ids.role_invite_id, self.ids.role_membre_id, self.ids.role_confiance_id}
        return not member.bot and not journey & member.role_ids

    async def prepare(self, gateway: VoteGateway, target_id: int) -> bool:
        return await gateway.add_role(target_id, self.ids.role_invite_id, "Nouvel arrivant : vote d'admission")

    async def on_approved(self, gateway: VoteGateway, vote: VoteRecord) -> str:
        target = vote.target_id
        who = f"👤 Utilisateur : <@{target}> ({target})"
        if not await gateway.add_role(target, self.ids.role_membre_id, "Admission approuvée"):
            return (
                "❌ **Admission votée, mais rôle Membre impossible à attribuer** "
                "(membre parti ou permission refusée) : action manuelle requise.\n"
                f"{who}\n{voters_line(vote)}"
            )
        if not await gateway.remove_role(target, self.ids.role_invite_id, "Admission approuvée"):
            return (
                "⚠️ **Admission approuvée**, mais rôle Invité impossible à retirer : à retirer à la main.\n"
                f"{who}\n{voters_line(vote)}"
            )
        return f"✅ **Admission approuvée**\n{who}\n{voters_line(vote)}"

    async def on_expired(self, gateway: VoteGateway, vote: VoteRecord) -> str:
        target = vote.target_id
        voters = voters_line(vote)
        member = await gateway.member(target)
        if member is None:
            return f"⏱️ **Vote d'admission expiré** — <@{target}> ({target}) a déjà quitté le serveur.\n{voters}"
        if vote.prepared and self.ids.role_invite_id not in member.role_ids:
            return (
                f"⏱️ **Vote d'admission expiré** — rôle Invité retiré manuellement, "
                f"<@{target}> ({target}) n'est pas expulsé.\n{voters}"
            )
        await gateway.send_dm(target, KICK_DM_MESSAGE)
        kicked = await gateway.kick(target, "Admission non validée dans le délai")
        status = "Kick automatique (expiration)" if kicked else "Expiration : kick impossible"
        return f"⏱️ **{status}**\n👤 Utilisateur : <@{target}> ({target})\n{voters}"


class ConfiancePolicy(_RenderedPolicy):
    """Membre → Confiance : candidats proposés par le scan, rôle Confiance au quorum,
    rien à l'expiration (le cooldown démarre)."""

    kind = VoteKind.CONFIANCE
    title = "Promotion Confiance"
    target_label = "Membre"

    def __init__(self, ids: CommunityIds, votes: VoteSettings) -> None:
        self.ids = ids
        self.window_seconds = votes.confiance_window_seconds
        self.eligibility_seconds = votes.confiance_eligibility_days * DAY_SECONDS
        self.cooldown_seconds = votes.confiance_cooldown_days * DAY_SECONDS

    def is_candidate(self, member: MemberInfo, now: float) -> bool:
        if member.bot or self.ids.role_membre_id not in member.role_ids:
            return False
        if self.ids.role_confiance_id in member.role_ids:
            return False
        return member.joined_at is not None and now - member.joined_at >= self.eligibility_seconds

    async def prepare(self, gateway: VoteGateway, target_id: int) -> bool:
        return True

    async def on_approved(self, gateway: VoteGateway, vote: VoteRecord) -> str:
        target = vote.target_id
        who = f"👤 Membre : <@{target}> ({target})"
        if not await gateway.add_role(target, self.ids.role_confiance_id, "Promotion Confiance approuvée"):
            return (
                "❌ **Promotion votée, mais rôle Confiance impossible à attribuer** "
                "(membre parti ou permission refusée) : action manuelle requise.\n"
                f"{who}\n{voters_line(vote)}"
            )
        return f"🎉 **Promotion Confiance approuvée**\n{who}\n{voters_line(vote)}"

    async def on_expired(self, gateway: VoteGateway, vote: VoteRecord) -> str:
        target = vote.target_id
        return (
            f"⏱️ **Promotion Confiance non obtenue** — <@{target}> ({target}) reste Membre "
            f"(nouvelle proposition possible après le cooldown).\n"
            f"{voters_line(vote)}"
        )

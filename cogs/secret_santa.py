"""Cog « Secret Santa » : /secret-santa test | draw | status | retry.

Tout est éphémère et guild-only. Aucune réponse, aucun message de salon, aucun log ne
contient une attribution donneur -> destinataire (voir services/secret_santa.py).
Le tirage passe toujours par une confirmation explicite par bouton.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands

from services.secret_santa import (
    MIN_PARTICIPANTS,
    TEST_DM,
    DeliveryReport,
    Participant,
    SecretSantaStore,
    collect_participants,
    deliver_pending,
    derangement,
    parse_message_url,
    send_dm,
)
from shameless_config import ShamelessSettings

logger = logging.getLogger(__name__)

CONFIRM_TIMEOUT_SECONDS = 300
MAX_LISTED = 40  # noms affichés avant « … et N autres » (limite de 2000 caractères par message)

NOT_ORGANIZER = "⛔ Il faut la permission **Gérer le serveur** pour utiliser cette commande."
NOT_THE_ORGANIZER = "⛔ Seul l'organisateur de ce tirage peut relancer les envois."


def format_names(names: list[str]) -> str:
    shown = ", ".join(names[:MAX_LISTED])
    return shown + (f" … et {len(names) - MAX_LISTED} autres" if len(names) > MAX_LISTED else "")


def failure_summary(report: DeliveryReport) -> str:
    lines = [f"⚠️ **{len(report.failed)}** MP en échec — à relancer avec `/secret-santa retry` :"]
    lines += [f"• <@{giver_id}> ({name}) : {reason.value}" for giver_id, name, reason in report.failed]
    return "\n".join(lines)


def delivery_summary(report: DeliveryReport, total: int) -> str:
    if not report.failed:
        return f"✅ **{report.sent}/{total}** MP envoyés. Tout le monde a reçu son tirage."
    return f"📬 **{report.sent}/{total}** MP envoyés.\n{failure_summary(report)}"


class ConfirmDrawView(discord.ui.View):
    """Seul l'organisateur qui a lancé la commande peut cliquer ; usage unique."""

    def __init__(self, cog: "SecretSanta", organizer_id: int, guild_id: int, participants: list[Participant]):
        super().__init__(timeout=CONFIRM_TIMEOUT_SECONDS)
        self.cog = cog
        self.organizer_id = organizer_id
        self.guild_id = guild_id
        self.participants = participants
        self.used = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.organizer_id:
            await interaction.response.send_message("⛔ Ce bouton ne t'est pas destiné.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Lancer le tirage", style=discord.ButtonStyle.danger, emoji="🎁")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.used:  # double clic
            await interaction.response.send_message("Tirage déjà en cours.", ephemeral=True)
            return
        self.used = True
        self.stop()
        await interaction.response.edit_message(content="⏳ Tirage et envoi des MP en cours…", view=None)
        try:
            text = await self.cog.execute_draw(self.guild_id, self.organizer_id, self.participants)
        except Exception:
            logger.exception("secret santa : échec inattendu pendant le tirage")
            text = (
                "❌ Erreur inattendue pendant le tirage. Vérifie `/secret-santa status` : "
                "si le tirage est enregistré, utilise `/secret-santa retry` (jamais de nouveau tirage)."
            )
        await interaction.edit_original_response(content=text)

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.used = True
        self.stop()
        await interaction.response.edit_message(content="Tirage annulé. Rien n'a été envoyé.", view=None)


@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)  # simple masquage côté client ; le contrôle réel est _is_admin
class SecretSanta(commands.GroupCog, group_name="secret-santa", group_description="Secret Santa"):
    def __init__(self, bot, settings: ShamelessSettings):
        self.bot = bot
        self.store = SecretSantaStore(settings.db_path)
        self._locks: dict[int, asyncio.Lock] = {}
        super().__init__()

    # =========================
    # LOGIQUE
    # =========================

    def _lock(self, guild_id: int) -> asyncio.Lock:
        return self._locks.setdefault(guild_id, asyncio.Lock())

    async def execute_draw(self, guild_id: int, organizer_id: int, participants: list[Participant]) -> str:
        """Tire, enregistre (une seule fois par serveur et par année) puis envoie les MP."""
        year = datetime.now().year
        async with self._lock(guild_id):
            if len(participants) < MIN_PARTICIPANTS:
                return f"❌ Il faut au moins {MIN_PARTICIPANTS} participants."
            assignments = derangement([p.id for p in participants])
            created = await asyncio.to_thread(
                self.store.create_draw, guild_id, year, organizer_id, participants, assignments
            )
            del assignments  # n'existe plus qu'en base, vidée au fil des envois
            if not created:
                return (
                    f"⛔ Un tirage {year} existe déjà sur ce serveur : aucun nouveau tirage. "
                    "Utilise `/secret-santa status`, ou `/secret-santa retry` pour les MP en échec."
                )
            report = await deliver_pending(self.store, self.bot.fetch_user, guild_id, year)
        return delivery_summary(report, len(participants))

    # =========================
    # COMMANDES
    # =========================

    @staticmethod
    def _is_admin(interaction: discord.Interaction) -> bool:
        return interaction.guild is not None and interaction.permissions.manage_guild

    @app_commands.command(name="test", description="Envoie un MP de test (aucun tirage, aucun état modifié)", extras=dict(examples=["/secret-santa test", "/secret-santa test user:@Alice"], permission="Gérer le serveur"))
    @app_commands.describe(user="Utilisateur à contacter (toi par défaut)")
    async def test(self, interaction: discord.Interaction, user: discord.User | None = None):
        if not self._is_admin(interaction):
            await interaction.response.send_message(NOT_ORGANIZER, ephemeral=True)
            return
        target = user or interaction.user
        if target.bot:
            await interaction.response.send_message("❌ Impossible d'envoyer un MP à un bot.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        reason = await send_dm(target, TEST_DM)
        if reason is None:
            text = f"✅ Discord a accepté le MP de test pour {target.mention}. Aucun tirage effectué."
        else:
            text = f"❌ MP de test impossible pour {target.mention} : {reason.value}."
            if reason.name == "DMS_CLOSED":
                text += "\nLes MP sont fermés : Paramètres de confidentialité du serveur → « Autoriser les messages privés »."
        await interaction.followup.send(text, ephemeral=True)

    @app_commands.command(name="draw", description="Prépare le tirage depuis les réactions d'un message (confirmation requise)", extras=dict(examples=["/secret-santa draw message_url:https://discord.com/channels/123/456/789 emoji:🎅"], permission="Gérer le serveur ; le bot doit voir le salon et l'historique du message"))
    @app_commands.describe(
        message_url="Lien du message contenant les réactions d'inscription",
        emoji="Emoji utilisé pour s'inscrire (ex. 🎅)",
    )
    async def draw(self, interaction: discord.Interaction, message_url: str, emoji: str):
        if not self._is_admin(interaction):
            await interaction.response.send_message(NOT_ORGANIZER, ephemeral=True)
            return
        guild = interaction.guild
        year = datetime.now().year
        if await asyncio.to_thread(self.store.draw_exists, guild.id, year):
            await interaction.response.send_message(
                f"⛔ Un tirage {year} existe déjà sur ce serveur. Voir `/secret-santa status`.", ephemeral=True
            )
            return

        parsed = parse_message_url(message_url)
        if parsed is None:
            await interaction.response.send_message(
                "❌ Lien invalide. Clic droit sur le message → « Copier le lien du message ».", ephemeral=True
            )
            return
        guild_id, channel_id, message_id = parsed
        if guild_id != guild.id:
            await interaction.response.send_message("❌ Ce message n'est pas sur ce serveur.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        message, error = await self._fetch_message(guild, channel_id, message_id)
        if message is None:
            await interaction.followup.send(error, ephemeral=True)
            return

        participants, skipped, found = await collect_participants(message, guild, emoji)
        if not found:
            await interaction.followup.send(f"❌ Aucune réaction {emoji} sur ce message.", ephemeral=True)
            return
        if len(participants) < MIN_PARTICIPANTS:
            await interaction.followup.send(
                f"❌ Il faut au moins {MIN_PARTICIPANTS} participants (trouvés : {len(participants)}).", ephemeral=True
            )
            return

        text = (
            f"🎅 **{len(participants)} participants** (bots et doublons exclus"
            + (f", {skipped} absent(s) du serveur ignoré(s)" if skipped else "")
            + f") :\n{format_names([p.name for p in participants])}\n\n"
            "Le tirage est **définitif** et les MP partent immédiatement. "
            "Personne, toi compris, ne verra les attributions. Confirmer ?"
        )
        view = ConfirmDrawView(self, interaction.user.id, guild.id, participants)
        await interaction.followup.send(text, view=view, ephemeral=True)

    async def _fetch_message(self, guild: discord.Guild, channel_id: int, message_id: int):
        channel = guild.get_channel_or_thread(channel_id)
        if channel is None:
            return None, "❌ Salon introuvable ou invisible pour le bot."
        permissions = channel.permissions_for(guild.me)
        missing = [
            label
            for label, ok in (
                ("Voir le salon", permissions.view_channel),
                ("Lire l'historique des messages", permissions.read_message_history),
            )
            if not ok
        ]
        if missing:
            return None, f"❌ Il manque au bot dans {channel.mention} : {', '.join(missing)}."
        try:
            return await channel.fetch_message(message_id), ""
        except discord.NotFound:
            return None, "❌ Message introuvable."
        except discord.Forbidden:
            return None, "❌ Discord refuse au bot l'accès à ce message."
        except discord.HTTPException:
            logger.exception("secret santa : lecture du message impossible")
            return None, "❌ Erreur Discord en lisant le message, réessaie dans un instant."

    @app_commands.command(name="status", description="État du Secret Santa (sans les attributions)", extras=dict(examples=["/secret-santa status"], permission="Gérer le serveur"))
    async def status(self, interaction: discord.Interaction):
        if not self._is_admin(interaction):
            await interaction.response.send_message(NOT_ORGANIZER, ephemeral=True)
            return
        latest = await asyncio.to_thread(self.store.latest_draw, interaction.guild.id)
        if latest is None:
            await interaction.response.send_message(
                "Aucun tirage pour ce serveur. Teste les MP avec `/secret-santa test`, "
                "puis lance `/secret-santa draw`.",
                ephemeral=True,
            )
            return
        year, organizer_id = latest
        sent, waiting = await asyncio.to_thread(self.store.progress, interaction.guild.id, year)
        text = f"🎁 **Secret Santa {year}** — tirage effectué, organisé par <@{organizer_id}>.\n"
        text += f"MP envoyés : **{sent}/{sent + len(waiting)}**."
        if waiting:
            text += "\nMP en attente (à relancer avec `/secret-santa retry`) :\n"
            text += "\n".join(f"• <@{giver_id}> ({name})" for giver_id, name in waiting)
        await interaction.response.send_message(text, ephemeral=True)

    @app_commands.command(name="retry", description="Renvoie uniquement les MP en échec (sans nouveau tirage)", extras=dict(examples=["/secret-santa retry"], permission="Organisateur du tirage uniquement"))
    async def retry(self, interaction: discord.Interaction):
        if not self._is_admin(interaction):
            await interaction.response.send_message(NOT_ORGANIZER, ephemeral=True)
            return
        guild_id = interaction.guild.id
        latest = await asyncio.to_thread(self.store.latest_draw, guild_id)
        if latest is None:
            await interaction.response.send_message("Aucun tirage à relancer.", ephemeral=True)
            return
        year, organizer_id = latest
        if interaction.user.id != organizer_id:
            await interaction.response.send_message(NOT_THE_ORGANIZER, ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with self._lock(guild_id):
            _, waiting = await asyncio.to_thread(self.store.progress, guild_id, year)
            if not waiting:
                await interaction.followup.send("✅ Tous les MP ont déjà été envoyés.", ephemeral=True)
                return
            report = await deliver_pending(self.store, self.bot.fetch_user, guild_id, year)
        await interaction.followup.send(delivery_summary(report, len(waiting)), ephemeral=True)


async def setup(bot):
    await bot.add_cog(SecretSanta(bot, bot.settings.shameless))

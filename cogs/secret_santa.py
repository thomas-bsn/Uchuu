"""Cog « Secret Santa » : `$$secret-santa test | draw | status | retry` (préfixe du bot).

Une commande à préfixe n'a pas de réponse éphémère : tout ce qui n'est pas anodin (liste des
participants, statut, confirmation, résultats) part en MP à celui qui a lancé la commande, le
salon ne reçoit qu'un accusé de réception. Aucune réponse, aucun message de salon, aucun log ne
contient une attribution donneur -> destinataire (voir services/secret_santa.py).
Le tirage passe toujours par une confirmation explicite par bouton.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path

import discord
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

# Seuls ces comptes peuvent utiliser les commandes. Dans un fichier texte : un ID Discord n'a pas sa place dans du code.
ORGANIZERS_FILE = Path(__file__).resolve().parent.parent / "include" / "secret_santa_organizers.txt"


def load_organizer_ids(path: Path = ORGANIZERS_FILE) -> frozenset[int]:
    lines = (line.split("#")[0].strip() for line in path.read_text(encoding="utf-8").splitlines())
    return frozenset(int(line) for line in lines if line)


ORGANIZER_IDS = load_organizer_ids()

CONFIRM_TIMEOUT_SECONDS = 300
MAX_LISTED = 40  # noms affichés avant « … et N autres » (limite de 2000 caractères par message)

NOT_ORGANIZER = "⛔ Tu n'es pas autorisé à utiliser cette commande."
NOT_THE_ORGANIZER = "⛔ Seul l'organisateur de ce tirage peut relancer les envois."
DM_CLOSED_FOR_ORGANIZER = (
    "❌ Je ne peux pas t'écrire en MP : les réponses du Secret Santa (listes, statut, résultats) "
    "te sont envoyées en privé. Ouvre tes MP et relance la commande."
)


def format_names(names: list[str]) -> str:
    shown = ", ".join(names[:MAX_LISTED])
    return shown + (f" … et {len(names) - MAX_LISTED} autres" if len(names) > MAX_LISTED else "")


def failure_summary(report: DeliveryReport, prefix: str) -> str:
    lines = [f"⚠️ **{len(report.failed)}** MP en échec — à relancer avec `{prefix}secret-santa retry` :"]
    lines += [f"• <@{giver_id}> ({name}) : {reason.value}" for giver_id, name, reason in report.failed]
    return "\n".join(lines)


def delivery_summary(report: DeliveryReport, total: int, prefix: str) -> str:
    if not report.failed:
        return f"✅ **{report.sent}/{total}** MP envoyés. Tout le monde a reçu son tirage."
    return f"📬 **{report.sent}/{total}** MP envoyés.\n{failure_summary(report, prefix)}"


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
            p = self.cog.prefix
            text = (
                f"❌ Erreur inattendue pendant le tirage. Vérifie `{p}secret-santa status` : "
                f"si le tirage est enregistré, utilise `{p}secret-santa retry` (jamais de nouveau tirage)."
            )
        await interaction.edit_original_response(content=text)

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.used = True
        self.stop()
        await interaction.response.edit_message(content="Tirage annulé. Rien n'a été envoyé.", view=None)


class SecretSanta(commands.Cog):
    def __init__(self, bot, settings: ShamelessSettings):
        self.bot = bot
        self.store = SecretSantaStore(settings.db_path)
        self._locks: dict[int, asyncio.Lock] = {}

    @property
    def prefix(self) -> str:
        return self.bot.command_prefix

    # =========================
    # LOGIQUE
    # =========================

    def _lock(self, guild_id: int) -> asyncio.Lock:
        return self._locks.setdefault(guild_id, asyncio.Lock())

    async def execute_draw(self, guild_id: int, organizer_id: int, participants: list[Participant]) -> str:
        """Tire, enregistre (une seule fois par serveur et par année) puis envoie les MP."""
        year = datetime.now().year
        p = self.prefix
        async with self._lock(guild_id):
            if len(participants) < MIN_PARTICIPANTS:
                return f"❌ Il faut au moins {MIN_PARTICIPANTS} participants."
            assignments = derangement([part.id for part in participants])
            created = await asyncio.to_thread(
                self.store.create_draw, guild_id, year, organizer_id, participants, assignments
            )
            del assignments  # n'existe plus qu'en base, vidée au fil des envois
            if not created:
                return (
                    f"⛔ Un tirage {year} existe déjà sur ce serveur : aucun nouveau tirage. "
                    f"Utilise `{p}secret-santa status`, ou `{p}secret-santa retry` pour les MP en échec."
                )
            report = await deliver_pending(self.store, self.bot.fetch_user, guild_id, year)
        return delivery_summary(report, len(participants), p)

    @staticmethod
    def _is_admin(ctx) -> bool:
        return ctx.guild is not None and ctx.author.id in ORGANIZER_IDS

    async def _private(self, ctx, content: str, **kwargs) -> bool:
        """Envoie en MP à l'auteur de la commande ; accusé de réception dans le salon."""
        try:
            await ctx.author.send(content, **kwargs)
        except discord.HTTPException:
            await ctx.send(DM_CLOSED_FOR_ORGANIZER)
            return False
        await ctx.send("📬 Réponse envoyée en MP.")
        return True

    # =========================
    # COMMANDES
    # =========================

    @commands.group(
        name="secret-santa",
        invoke_without_command=True,
        help="Secret Santa : test, draw, status, retry",
    )
    @commands.guild_only()
    async def secret_santa(self, ctx):
        p = ctx.prefix
        await ctx.send(
            f"Sous-commandes : `{p}secret-santa test|draw|status|retry`. Détails : `{p}helps secret-santa`."
        )

    @secret_santa.command(
        name="test",
        help="Envoie un MP de test (aucun tirage, aucun état modifié)",
        usage="[user]",
        extras={
            "params": "user (optionnel) : utilisateur à contacter, toi par défaut",
            "examples": ["secret-santa test", "secret-santa test @Alice"],
            "permission": "Organisateur autorisé",
        },
    )
    async def test(self, ctx, user: discord.User = None):
        if not self._is_admin(ctx):
            await ctx.send(NOT_ORGANIZER)
            return
        target = user or ctx.author
        if target.bot:
            await ctx.send("❌ Impossible d'envoyer un MP à un bot.")
            return
        reason = await send_dm(target, TEST_DM)
        if reason is None:
            await ctx.send(f"✅ Discord a accepté le MP de test pour {target.mention}. Aucun tirage effectué.")
            return
        text = f"❌ MP de test impossible pour {target.mention} : {reason.value}."
        if reason.name == "DMS_CLOSED":
            text += "\nLes MP sont fermés : Paramètres de confidentialité du serveur → « Autoriser les messages privés »."
        await ctx.send(text)

    @secret_santa.command(
        name="draw",
        help="Prépare le tirage depuis les réactions d'un message (confirmation requise)",
        usage="<message_url> <emoji>",
        extras={
            "params": "message_url (requis) : lien du message d'inscription ; emoji (requis) : emoji d'inscription",
            "examples": ["secret-santa draw https://discord.com/channels/123/456/789 🎅"],
            "permission": "Organisateur autorisé ; le bot doit voir le salon et lire l'historique du message",
        },
    )
    async def draw(self, ctx, message_url: str, emoji: str):
        if not self._is_admin(ctx):
            await ctx.send(NOT_ORGANIZER)
            return
        guild = ctx.guild
        year = datetime.now().year
        p = ctx.prefix
        if await asyncio.to_thread(self.store.draw_exists, guild.id, year):
            await ctx.send(f"⛔ Un tirage {year} existe déjà sur ce serveur. Voir `{p}secret-santa status`.")
            return

        parsed = parse_message_url(message_url)
        if parsed is None:
            await ctx.send("❌ Lien invalide. Clic droit sur le message → « Copier le lien du message ».")
            return
        guild_id, channel_id, message_id = parsed
        if guild_id != guild.id:
            await ctx.send("❌ Ce message n'est pas sur ce serveur.")
            return

        message, error = await self._fetch_message(guild, channel_id, message_id)
        if message is None:
            await ctx.send(error)
            return

        participants, skipped, found = await collect_participants(message, guild, emoji)
        if not found:
            await ctx.send(f"❌ Aucune réaction {emoji} sur ce message.")
            return
        if len(participants) < MIN_PARTICIPANTS:
            await ctx.send(f"❌ Il faut au moins {MIN_PARTICIPANTS} participants (trouvés : {len(participants)}).")
            return

        text = (
            f"🎅 **{len(participants)} participants** (bots et doublons exclus"
            + (f", {skipped} absent(s) du serveur ignoré(s)" if skipped else "")
            + f") :\n{format_names([part.name for part in participants])}\n\n"
            "Le tirage est **définitif** et les MP partent immédiatement. "
            "Personne, toi compris, ne verra les attributions. Confirmer ?"
        )
        await self._private(ctx, text, view=ConfirmDrawView(self, ctx.author.id, guild.id, participants))

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

    @secret_santa.command(
        name="status",
        help="État du Secret Santa (sans les attributions)",
        extras={"examples": ["secret-santa status"], "permission": "Organisateur autorisé"},
    )
    async def status(self, ctx):
        if not self._is_admin(ctx):
            await ctx.send(NOT_ORGANIZER)
            return
        p = ctx.prefix
        latest = await asyncio.to_thread(self.store.latest_draw, ctx.guild.id)
        if latest is None:
            await ctx.send(
                f"Aucun tirage pour ce serveur. Teste les MP avec `{p}secret-santa test`, "
                f"puis lance `{p}secret-santa draw`."
            )
            return
        year, organizer_id = latest
        sent, waiting = await asyncio.to_thread(self.store.progress, ctx.guild.id, year)
        text = f"🎁 **Secret Santa {year}** — tirage effectué, organisé par <@{organizer_id}>.\n"
        text += f"MP envoyés : **{sent}/{sent + len(waiting)}**."
        if waiting:
            text += f"\nMP en attente (à relancer avec `{p}secret-santa retry`) :\n"
            text += "\n".join(f"• <@{giver_id}> ({name})" for giver_id, name in waiting)
        await self._private(ctx, text)

    @secret_santa.command(
        name="retry",
        help="Renvoie uniquement les MP en échec (sans nouveau tirage)",
        extras={"examples": ["secret-santa retry"], "permission": "Organisateur du tirage uniquement"},
    )
    async def retry(self, ctx):
        if not self._is_admin(ctx):
            await ctx.send(NOT_ORGANIZER)
            return
        guild_id = ctx.guild.id
        latest = await asyncio.to_thread(self.store.latest_draw, guild_id)
        if latest is None:
            await ctx.send("Aucun tirage à relancer.")
            return
        year, organizer_id = latest
        if ctx.author.id != organizer_id:
            await ctx.send(NOT_THE_ORGANIZER)
            return
        async with self._lock(guild_id):
            _, waiting = await asyncio.to_thread(self.store.progress, guild_id, year)
            if not waiting:
                await ctx.send("✅ Tous les MP ont déjà été envoyés.")
                return
            report = await deliver_pending(self.store, self.bot.fetch_user, guild_id, year)
        await self._private(ctx, delivery_summary(report, len(waiting), ctx.prefix))

    async def cog_command_error(self, ctx, error):
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"❌ Argument manquant : `{error.param.name}`. Voir `{ctx.prefix}helps secret-santa`.")
        elif isinstance(error, (commands.BadArgument, commands.UserInputError)):
            await ctx.send(f"❌ Argument invalide. Voir `{ctx.prefix}helps secret-santa`.")
        elif isinstance(error, commands.NoPrivateMessage):
            await ctx.send("❌ Commande utilisable uniquement sur un serveur.")
        else:
            raise error


async def setup(bot):
    await bot.add_cog(SecretSanta(bot, bot.settings.shameless))

"""Secret Santa : tirage, persistance et envoi des MP. Aucune dépendance au cog.

Confidentialité (voulue par l'organisateur, qui participe) :
- les attributions n'existent que le temps de l'envoi : une ligne est vidée (destinataire
  effacé) dès que son MP est accepté par Discord. Ne restent en base que les MP en échec,
  nécessaires à `retry` ;
- rien n'expose une attribution (ni commande, ni endpoint, ni log, ni réponse) ;
- les logs ne contiennent que des compteurs et des IDs de donneurs, jamais de destinataire.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import secrets
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import discord

from services.sqlite_store import SqliteStore

logger = logging.getLogger(__name__)

MIN_PARTICIPANTS = 2
# Pause entre deux MP : discord.py gère les 429, mais l'envoi en rafale de MP à des inconnus
# est ce qui fait flagger un bot par l'anti-spam de Discord.
SEND_DELAY_SECONDS = 1.0

TEST_DM = "🎅 Ceci est un message de test du Secret Santa. Aucun tirage n'a encore été effectué."

_MESSAGE_URL = re.compile(
    r"^https?://(?:(?:ptb|canary)\.)?discord(?:app)?\.com/channels/(\d+)/(\d+)/(\d+)/?$"
)


# Le lien contient des IDs Discord : gardé hors du code (test_no_discord_id_committed_in_python_code)
GIF_URL = (Path(__file__).resolve().parent.parent / "include" / "secret_santa_gif.txt").read_text(encoding="utf-8").strip()


def dm_text(year: int, giver_name: str, recipient_name: str) -> str:
    return (
        f"🎄 **SECRET SANTA {year}** 🎁\n\n"
        f"Salut {giver_name} ! 🎅\n\n"
        f"🎁 Tu as été tiré au sort pour offrir un cadeau à **@{recipient_name}** !\n\n"
        "🤫 Garde son identité secrète jusqu'au jour de l'échange des cadeaux.\n\n"
        "🎄 Joyeux Secret Santa et amuse-toi bien !\n\n"
        + GIF_URL
    )


# =========================
# PARTICIPANTS
# =========================

@dataclass(frozen=True)
class Participant:
    id: int
    name: str


def parse_message_url(url: str) -> tuple[int, int, int] | None:
    """(guild_id, channel_id, message_id) d'un lien de message Discord, sinon None."""
    match = _MESSAGE_URL.match(url.strip())
    return tuple(int(g) for g in match.groups()) if match else None


def _normalize_emoji(value: str) -> str:
    # ❤ et ❤️ ne diffèrent que par le sélecteur de variation U+FE0F
    return value.strip().replace("️", "")


async def collect_participants(message, guild, emoji: str) -> tuple[list[Participant], int, bool]:
    """(participants, ignorés, emoji_trouvé) pour les réactions `emoji` du message.

    `reaction.users()` pagine seul (pages de 100) tant qu'on ne lui donne pas de limite.
    Exclut les bots et les doublons ; ignore (et compte) ceux qui ont quitté le serveur.
    """
    wanted = _normalize_emoji(emoji)
    reactions = [r for r in message.reactions if _normalize_emoji(str(r.emoji)) == wanted]
    if not reactions:
        return [], 0, False

    seen: dict[int, Participant] = {}
    skipped_ids: set[int] = set()
    for reaction in reactions:
        async for user in reaction.users():
            if user.bot or user.id in seen or user.id in skipped_ids:
                continue
            member = guild.get_member(user.id)
            if member is None:
                try:
                    member = await guild.fetch_member(user.id)
                except discord.NotFound:
                    member = None
            if member is None or member.bot:
                skipped_ids.add(user.id)
                continue
            seen[user.id] = Participant(user.id, member.display_name)
    return sorted(seen.values(), key=lambda p: p.name.casefold()), len(skipped_ids), True


# =========================
# TIRAGE
# =========================

def derangement(ids: list[int], rng: secrets.SystemRandom | None = None) -> dict[int, int]:
    """donneur -> destinataire : permutation sans point fixe, uniforme parmi les dérangements.

    Rejet : on mélange (CSPRNG) jusqu'à ne plus avoir personne face à soi-même. La
    probabilité de succès tend vers 1/e, soit ~2,7 essais en moyenne ; contrairement à
    l'algorithme de Sattolo, tous les dérangements restent possibles (pas que les cycles uniques).
    """
    unique = list(dict.fromkeys(ids))
    if len(unique) < MIN_PARTICIPANTS:
        raise ValueError(f"il faut au moins {MIN_PARTICIPANTS} participants")
    rng = rng or secrets.SystemRandom()
    receivers = list(unique)
    while True:
        rng.shuffle(receivers)
        if all(giver != receiver for giver, receiver in zip(unique, receivers)):
            return dict(zip(unique, receivers))


# =========================
# PERSISTANCE
# =========================

class SecretSantaStore(SqliteStore):
    """Un tirage par (serveur, année), irréversible. `recipient_id` / `recipient_name` sont
    NULL une fois le MP accepté : plus aucune trace de l'attribution en base."""

    SCHEMA = (
        """
        CREATE TABLE IF NOT EXISTS secret_santa_draws (
            guild_id     INTEGER NOT NULL,
            year         INTEGER NOT NULL,
            organizer_id INTEGER NOT NULL,
            created_at   REAL NOT NULL,
            PRIMARY KEY (guild_id, year)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS secret_santa_assignments (
            guild_id       INTEGER NOT NULL,
            year           INTEGER NOT NULL,
            giver_id       INTEGER NOT NULL,
            giver_name     TEXT NOT NULL,
            recipient_id   INTEGER,  -- NULL une fois le MP envoyé
            recipient_name TEXT,     -- NULL une fois le MP envoyé
            sent_at        REAL,
            PRIMARY KEY (guild_id, year, giver_id)
        )
        """,
    )

    def create_schema(self) -> None:
        super().create_schema()
        try:  # le fichier peut contenir des attributions en attente : lecture réservée au bot
            os.chmod(self.db_path, 0o600)
        except OSError:
            pass

    def draw_exists(self, guild_id: int, year: int) -> bool:
        with self._conn() as conn:
            return conn.execute(
                "SELECT 1 FROM secret_santa_draws WHERE guild_id = ? AND year = ?", (guild_id, year)
            ).fetchone() is not None

    def create_draw(
        self,
        guild_id: int,
        year: int,
        organizer_id: int,
        participants: list[Participant],
        assignments: dict[int, int],
    ) -> bool:
        """Enregistre tirage + attributions en une transaction. False si ce serveur a déjà un
        tirage cette année (rien n'est alors écrit) : c'est le garde-fou anti-double tirage."""
        names = {p.id: p.name for p in participants}
        with self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                cur = conn.execute(
                    "INSERT OR IGNORE INTO secret_santa_draws (guild_id, year, organizer_id, created_at)"
                    " VALUES (?, ?, ?, ?)",
                    (guild_id, year, organizer_id, time.time()),
                )
                if cur.rowcount != 1:
                    conn.execute("ROLLBACK")
                    return False
                conn.executemany(
                    "INSERT INTO secret_santa_assignments"
                    " (guild_id, year, giver_id, giver_name, recipient_id, recipient_name)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    [
                        (guild_id, year, giver, names[giver], receiver, names[receiver])
                        for giver, receiver in assignments.items()
                    ],
                )
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        return True

    def latest_draw(self, guild_id: int) -> tuple[int, int] | None:
        """(année, organizer_id) du tirage le plus récent du serveur."""
        with self._conn() as conn:
            return conn.execute(
                "SELECT year, organizer_id FROM secret_santa_draws WHERE guild_id = ? ORDER BY year DESC LIMIT 1",
                (guild_id,),
            ).fetchone()

    def pending(self, guild_id: int, year: int) -> list[tuple[int, str, int, str]]:
        """(giver_id, giver_name, recipient_id, recipient_name) des MP pas encore acceptés.
        Réservé à `deliver_pending` : ne jamais l'exposer."""
        with self._conn() as conn:
            return conn.execute(
                "SELECT giver_id, giver_name, recipient_id, recipient_name FROM secret_santa_assignments"
                " WHERE guild_id = ? AND year = ? AND sent_at IS NULL ORDER BY giver_id",
                (guild_id, year),
            ).fetchall()

    def mark_sent(self, guild_id: int, year: int, giver_id: int) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE secret_santa_assignments SET sent_at = ?, recipient_id = NULL, recipient_name = NULL"
                " WHERE guild_id = ? AND year = ? AND giver_id = ?",
                (time.time(), guild_id, year, giver_id),
            )

    def progress(self, guild_id: int, year: int) -> tuple[int, list[tuple[int, str]]]:
        """(nombre de MP envoyés, [(giver_id, giver_name)] des MP en attente). Aucune attribution."""
        with self._conn() as conn:
            sent = conn.execute(
                "SELECT COUNT(*) FROM secret_santa_assignments WHERE guild_id = ? AND year = ? AND sent_at IS NOT NULL",
                (guild_id, year),
            ).fetchone()[0]
            waiting = conn.execute(
                "SELECT giver_id, giver_name FROM secret_santa_assignments"
                " WHERE guild_id = ? AND year = ? AND sent_at IS NULL ORDER BY giver_name",
                (guild_id, year),
            ).fetchall()
        return sent, waiting


# =========================
# ENVOI DES MP
# =========================

class FailureReason(Enum):
    DMS_CLOSED = "MP fermés"
    NOT_FOUND = "compte introuvable"
    DISCORD_ERROR = "erreur Discord"


@dataclass(frozen=True)
class DeliveryReport:
    sent: int
    failed: list[tuple[int, str, FailureReason]]  # (giver_id, giver_name, raison) : pas de destinataire


async def send_dm(user, content: str) -> FailureReason | None:
    """None si Discord a accepté le MP, sinon la raison de l'échec."""
    try:
        await user.send(content)
    except discord.Forbidden:
        return FailureReason.DMS_CLOSED
    except discord.HTTPException:
        return FailureReason.DISCORD_ERROR
    return None


async def deliver_pending(store: SecretSantaStore, resolve_user, guild_id: int, year: int) -> DeliveryReport:
    """Envoie les MP encore en attente et marque chacun dès qu'il est accepté.

    Ne tire jamais : les attributions viennent de la base. `resolve_user(id)` est une coroutine
    renvoyant l'utilisateur (ex. `bot.fetch_user`). Réexécutable à volonté : seuls les échecs restent.
    """
    pending = await asyncio.to_thread(store.pending, guild_id, year)
    sent = 0
    failed: list[tuple[int, str, FailureReason]] = []
    for index, (giver_id, giver_name, _recipient_id, recipient_name) in enumerate(pending):
        if index:
            await asyncio.sleep(SEND_DELAY_SECONDS)
        try:
            user = await resolve_user(giver_id)
        except discord.NotFound:
            failed.append((giver_id, giver_name, FailureReason.NOT_FOUND))
            continue
        except discord.HTTPException:
            failed.append((giver_id, giver_name, FailureReason.DISCORD_ERROR))
            continue
        reason = await send_dm(user, dm_text(year, giver_name, recipient_name))
        if reason is None:
            await asyncio.to_thread(store.mark_sent, guild_id, year, giver_id)
            sent += 1
        else:
            failed.append((giver_id, giver_name, reason))
    logger.info("secret santa : %s MP envoyés, %s en échec (serveur %s)", sent, len(failed), guild_id)
    return DeliveryReport(sent, failed)

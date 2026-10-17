"""Cog Shameless « Votes » (#15) : bulletin MVP/DOFD d'une Game, annonce à la clôture.

À `game_completed`, le bot lit le contexte de la Game (`GET /bot/games/{id}`) et propose le
bulletin (MVP + DOFD) dans `SHAMELESS_VOTE_CHANNEL_ID`. Chaque bulletin validé part vers
`PUT /bot/games/{id}/votes` ; une erreur 400/409 de l'API est affichée au votant. Dix minutes
après `completedAt`, le bot relit `GET /bot/games/{id}/votes` et annonce les gagnants (tous les
ex æquo). L'API reste la seule source des résultats : le bot ne conserve ni décompte ni gagnant.

Redémarrage : l'échéance et les Joueurs vivent dans SQLite (`GameVoteStore`) ; `cog_load` et
`on_ready` reconcilient les fenêtres en attente et réenregistrent la vue persistante. Un `call_later`
assure la clôture en cours de vie ; la réconciliation couvre l'arrêt/redémarrage.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from functools import partial
from typing import Any, Callable

import discord
from discord.ext import commands

from services.shameless_client import ShamelessApiClient, ShamelessApiError, client_from_settings
from services.shameless_events import EVENT_GAME_COMPLETED, ShamelessEvent, get_dispatcher
from services.shameless_payloads import game_id_of
from services.shameless_vote_view import (
    BulletinDeVote,
    bulletin_embed,
    linked_player_id,
    players_of_context,
    results_embed,
)
from services.shameless_votes_store import GameVoteStore
from shameless_config import ShamelessSettings

logger = logging.getLogger(__name__)

# Relecture des résultats si l'API ne les donne pas encore clos (horloges désynchronisées)
RETRY_DELAY_SECONDS = 30.0


def deadline_of(completed_at: str | None, duration_seconds: float) -> float | None:
    """Échéance du vote : `completedAt` (ISO 8601 UTC) + la durée (10 min par défaut)."""
    if not completed_at:
        return None
    try:
        moment = datetime.fromisoformat(str(completed_at).replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.timestamp() + duration_seconds


class ShamelessVotes(commands.Cog):
    def __init__(
        self,
        bot,
        settings: ShamelessSettings,
        api: ShamelessApiClient | None = None,
        clock: Callable[[], float] = time.time,
    ):
        self.bot = bot
        self.settings = settings
        self.store = GameVoteStore(settings.db_path)
        # client injecté en test ; sinon construit à la première transmission depuis la config
        self._api = api
        self._clock = clock
        self._closers: dict[str, asyncio.TimerHandle] = {}

    async def cog_load(self):
        get_dispatcher(self.bot).register(EVENT_GAME_COMPLETED, self.on_game_completed)
        await self._reconcile()

    async def cog_unload(self):
        get_dispatcher(self.bot).unregister(EVENT_GAME_COMPLETED, self.on_game_completed)
        for handle in self._closers.values():
            handle.cancel()
        self._closers.clear()
        if self._api is not None:
            await self._api.aclose()

    @commands.Cog.listener()
    async def on_ready(self):
        # (re)connexion / redémarrage : rattrape les fenêtres dont l'échéance est passée
        await self._reconcile()

    # =========================
    # OUVERTURE DU VOTE (game_completed)
    # =========================

    async def on_game_completed(self, event: ShamelessEvent) -> None:
        game_id = game_id_of(event.data)
        if game_id is None:
            logger.warning(
                "shameless: game_id absent ou invalide, vote MVP/DOFD ignoré : %r", event.data.get("game_id")
            )
            return

        try:
            game = await self._api_client().get_game(game_id)
        except ShamelessApiError as error:
            if error.is_permanent:
                # Game inconnue : aucune fenêtre de vote possible, inutile de retenter
                logger.warning("shameless: contexte de la Game %s indisponible : %s", game_id, error)
                return
            raise  # panne réseau / 5xx / clé : Shameless retente

        deadline = deadline_of(game.get("completedAt"), self.settings.vote_duration_seconds)
        players = players_of_context(game)
        if game.get("status") != "completed" or deadline is None:
            logger.warning("shameless: Game %s non terminée, pas de vote MVP/DOFD", game_id)
            return
        if not players:
            logger.warning("shameless: Game %s sans Joueurs, pas de vote MVP/DOFD", game_id)
            return

        key = str(game_id)
        await asyncio.to_thread(self.store.open_window, key, deadline, players)
        await self._post_bulletin_once(key, game, self._build_view(key, players))
        self._schedule_close(key, deadline)

    # =========================
    # BULLETIN (vue persistante)
    # =========================

    def _build_view(self, game_id: str, players: list[dict[str, Any]]) -> BulletinDeVote:
        return BulletinDeVote(
            game_id=game_id,
            players=players,
            on_submit=partial(self._submit_bulletin, game_id, players),
        )

    async def _post_bulletin_once(self, game_id: str, game: dict[str, Any], view: BulletinDeVote) -> None:
        # salon résolu AVANT la réservation : absent / inaccessible -> exception, l'event
        # n'est pas marqué traité et Shameless retente
        channel = await self._vote_channel()
        if not await asyncio.to_thread(self.store.claim_bulletin, game_id):
            return
        try:
            await channel.send(embed=bulletin_embed(game), view=view)
            self._register_view(view)
        except BaseException:
            await asyncio.shield(asyncio.to_thread(self.store.release_bulletin, game_id))
            raise

    def _register_view(self, view: BulletinDeVote) -> None:
        add_view = getattr(self.bot, "add_view", None)
        if callable(add_view):
            add_view(view)  # persistance : la vue survit au redémarrage

    async def _submit_bulletin(
        self,
        game_id: str,
        players: list[dict[str, Any]],
        interaction: discord.Interaction,
        mvp_player_id: int | None,
        dofd_player_id: int | None,
    ) -> None:
        own = linked_player_id(players, interaction.user.id)
        for titre, player_id in (("MVP", mvp_player_id), ("DOFD", dofd_player_id)):
            if player_id is not None and own is not None and player_id == own:
                await self._reply(interaction, f"❌ Tu ne peux pas voter pour toi-même ({titre}).")
                return
        try:
            await self._api_client().put_votes(
                int(game_id),
                str(interaction.user.id),
                mvp_player_id=mvp_player_id,
                dofd_player_id=dofd_player_id,
            )
        except ShamelessApiError as error:
            if error.is_permanent:
                # 400/404/409 : refus définitif, le message de l'API explique pourquoi
                await self._reply(interaction, f"❌ Vote refusé : {error.detail or error}")
            else:
                # réseau / 5xx / 401 : la panne se répare, on invite à réessayer (jamais « refusé »)
                await self._reply(interaction, "⚠️ Vote non transmis : l'API Shameless est injoignable, réessaie dans un instant.")
            return
        await self._reply(
            interaction, "✅ Ton bulletin est enregistré. Tu peux le modifier jusqu'à la clôture du vote."
        )

    async def _reply(self, interaction: discord.Interaction, message: str) -> None:
        await interaction.response.send_message(message, ephemeral=True)

    # =========================
    # CLÔTURE ET ANNONCE
    # =========================

    async def _reconcile(self) -> None:
        """Relit les fenêtres non annoncées : enregistre la vue, clôt celles échues."""
        now = self._clock()
        pending = await asyncio.to_thread(self.store.pending)
        for game_id, deadline, players in pending:
            self._register_view(self._build_view(game_id, players))
            if deadline <= now:
                await self._close_and_announce(game_id)
            else:
                self._schedule_close(game_id, deadline)

    def _schedule_close(self, game_id: str, deadline: float) -> None:
        previous = self._closers.pop(game_id, None)
        if previous is not None:
            previous.cancel()
        delay = max(0.0, deadline - self._clock())
        handle = asyncio.get_running_loop().call_later(
            delay, lambda: asyncio.ensure_future(self._close_and_announce(game_id))
        )
        self._closers[game_id] = handle

    async def _close_and_announce(self, game_id: str) -> None:
        self._closers.pop(game_id, None)
        if not await asyncio.to_thread(self.store.claim_announce, game_id):
            return  # déjà annoncé (rejeu, double réveil)
        try:
            results = await self._api_client().get_votes(int(game_id))
        except ShamelessApiError as error:
            await asyncio.to_thread(self.store.release_announce, game_id)
            logger.warning("shameless: résultats des votes de la Game %s indisponibles : %s", game_id, error)
            if not error.is_permanent:
                self._schedule_close(game_id, self._clock() + RETRY_DELAY_SECONDS)
            return
        if str(results.get("statut")) != "clos":
            # l'API ne dit pas encore clos (horloges) : on ne dévoile rien et on réessaie
            await asyncio.to_thread(self.store.release_announce, game_id)
            self._schedule_close(game_id, self._clock() + RETRY_DELAY_SECONDS)
            return
        try:
            channel = await self._vote_channel()
            await channel.send(embed=results_embed(results))
        except Exception:
            await asyncio.shield(asyncio.to_thread(self.store.release_announce, game_id))
            logger.exception("shameless: annonce des résultats de la Game %s impossible", game_id)
            self._schedule_close(game_id, self._clock() + RETRY_DELAY_SECONDS)

    # =========================
    # HELPERS
    # =========================

    async def _vote_channel(self):
        channel_id = self.settings.vote_channel_id
        if channel_id is None:
            raise RuntimeError("SHAMELESS_VOTE_CHANNEL_ID absent : bulletin MVP/DOFD impossible")
        # pas dans le cache -> fetch ; s'il lève, le webhook répond 500 et Shameless retente
        return self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)

    def _api_client(self) -> ShamelessApiClient:
        # config absente -> ShamelessApiError : l'event n'est pas acquitté, Shameless retente
        if self._api is None:
            self._api = client_from_settings(self.settings)
        return self._api


async def setup(bot):
    await bot.add_cog(ShamelessVotes(bot, bot.settings.shameless))

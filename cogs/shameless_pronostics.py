"""Cog Shameless « Pronostics » (#16).

Avant chaque Game, les Spectateurs pronostiquent dans Discord l'équipe gagnante, le MVP et
le DOFD ; le bot transmet via `PUT /bot/series/{id}/pronostics` (verrouillé au
`game_started`) et, après `game_completed`, annonce les bonnes réponses (vainqueur, MVP,
DOFD séparément) lues sur `GET /bot/games/{id}/pronostics`. Aucun point, classement ni
titre Doyen.

Branchement : le dispatcher webhook chaîne plusieurs handlers par type d'event (#16
observe `teams_formed`, `game_started` et `game_completed` sans remplacer ceux de #4/#5).
L'aperçu de la Game ouverte vient de `GET /bot/series/{id}/pronostics` : sur `teams_formed`
(Game 1) et après chaque `game_completed` (Game suivante), une seule fois par (Série, Game).

SQLite et HTTP sont hors de la boucle du bot (jamais d'I/O bloquante). Un payload non
réparable est logué et acquitté ; une panne réseau / 5xx / clé à corriger n'est pas
acquittée (Shameless retente). La clé machine n'apparaît jamais dans un message.
"""
from __future__ import annotations

import asyncio
import logging

from discord.ext import commands

from services.shameless_client import ShamelessApiClient, ShamelessApiError, client_from_settings
from services.shameless_events import (
    EVENT_GAME_COMPLETED,
    EVENT_GAME_STARTED,
    EVENT_TEAMS_FORMED,
    ShamelessEvent,
    get_dispatcher,
)
from services.shameless_payloads import game_id_of, series_id_of
from services.shameless_pronostics import (
    Composition,
    PronosticChoice,
    PronosticsView,
    composition_of,
    pronostics_embed,
    result_embed,
)
from services.shameless_pronostics_store import TITLE_DOFD, TITLE_EQUIPE, TITLE_MVP, TITLES, PronosticsStore
from shameless_config import ShamelessSettings

logger = logging.getLogger(__name__)


class ShamelessPronostics(commands.Cog):
    def __init__(
        self,
        bot,
        settings: ShamelessSettings,
        api: ShamelessApiClient | None = None,
        store: PronosticsStore | None = None,
    ):
        self.bot = bot
        self.settings = settings
        self.store = store or PronosticsStore(settings.db_path)
        self._api = api  # client injecté en test ; sinon construit au premier appel
        self._task: asyncio.Task | None = None

    @property
    def enabled(self) -> bool:
        """Sans salon de pronostics configuré, la fonctionnalité est désactivée."""
        return self.settings.pronostics_channel_id is not None

    async def cog_load(self):
        if not self.enabled:
            return
        dispatcher = get_dispatcher(self.bot)
        dispatcher.register(EVENT_TEAMS_FORMED, self.on_teams_formed)
        dispatcher.register(EVENT_GAME_COMPLETED, self.on_game_completed)
        dispatcher.register(EVENT_GAME_STARTED, self.on_game_started)
        if self.settings.pronostics_reconcile_seconds > 0:
            self._task = asyncio.create_task(self._reconcile_loop())

    async def cog_unload(self):
        if not self.enabled:
            return
        dispatcher = get_dispatcher(self.bot)
        dispatcher.unregister(EVENT_TEAMS_FORMED, self.on_teams_formed)
        dispatcher.unregister(EVENT_GAME_COMPLETED, self.on_game_completed)
        dispatcher.unregister(EVENT_GAME_STARTED, self.on_game_started)
        if self._task is not None:
            self._task.cancel()
            self._task = None
        if self._api is not None:
            await self._api.aclose()

    # =========================
    # HANDLERS WEBHOOK
    # =========================

    async def on_teams_formed(self, event: ShamelessEvent) -> None:
        series_id = series_id_of(event.data)
        if series_id is None:
            logger.warning("shameless: series_id absent ou invalide, pronostics non proposés : %r",
                           event.data.get("series_id"))
            return
        await self._open_pronostics(series_id)

    async def on_game_started(self, event: ShamelessEvent) -> None:
        data = event.data
        series_id = series_id_of(data)
        game_number = data.get("game_number")
        if series_id is None or isinstance(game_number, bool) or not isinstance(game_number, int):
            return
        # verrou local : la Game lancée ferme les pronostics de son numéro (l'API 409 aussi)
        await asyncio.to_thread(self.store.lock, series_id, game_number)

    async def on_game_completed(self, event: ShamelessEvent) -> None:
        data = event.data
        game_id = game_id_of(data)
        series_id = series_id_of(data)
        if game_id is not None:
            await self._announce_results(game_id, series_id, winner=data.get("winner"))
        if series_id is not None:
            # la Game suivante est ouverte aux pronostics jusqu'à son game_started
            await self._open_pronostics(series_id)

    # =========================
    # PROPOSITION DU BULLETIN
    # =========================

    async def _open_pronostics(self, series_id: int) -> None:
        try:
            preview = await self._api_client().get_series_pronostics(series_id)
        except ShamelessApiError as error:
            if error.is_permanent:
                logger.warning("shameless: aperçu des pronostics de la Série %s refusé : %s", series_id, error)
                return
            raise  # panne réseau, 5xx ou clé à corriger : Shameless retente
        composition = composition_of(preview, series_id)
        if composition is None:
            return  # aucune Game ouverte : rien à proposer
        if not await asyncio.to_thread(self.store.claim_bulletin, series_id, composition.game_number):
            return  # bulletin déjà publié pour cette Game

        channel = await self._pronostics_channel()
        try:
            view = PronosticsView(composition, on_submit=self._submit)
            await channel.send(embed=pronostics_embed(composition), view=view)
            self._register_view(view)
        except BaseException:
            # pas publié -> on libère pour que le retry republie
            await asyncio.shield(asyncio.to_thread(self.store.release_bulletin, series_id, composition.game_number))
            raise

    def _register_view(self, view: PronosticsView) -> None:
        add_view = getattr(self.bot, "add_view", None)
        if callable(add_view):
            add_view(view)

    # =========================
    # SOUMISSION D'UN PRONOSTIC (interactions)
    # =========================

    async def _submit(self, interaction, composition: Composition, choice: PronosticChoice) -> None:
        user_id = str(interaction.user.id)
        if user_id in composition.linked_discord_ids:
            await self._reply(
                interaction,
                "Les pronostics sont réservés aux Spectateurs : les Joueurs de la Série ne pronostiquent pas.",
            )
            return
        if not choice.is_valid_for(composition):
            await self._reply(
                interaction,
                "Choix invalide : le MVP et le DOFD doivent être des Joueurs de la Série, "
                "et l'équipe gagnante « A » ou « B ».",
            )
            return
        if await asyncio.to_thread(self.store.is_locked, composition.series_id, composition.game_number):
            await self._reply(interaction, "Cette game est lancée : ses pronostics sont verrouillés.")
            return

        try:
            await self._api_client().put_pronostic(
                composition.series_id,
                discord_id=user_id,
                nom=self._display_name(interaction),
                game_number=composition.game_number,
                equipe_gagnante=choice.equipe_gagnante,
                mvp_player_id=choice.mvp_player_id,
                dofd_player_id=choice.dofd_player_id,
            )
        except ShamelessApiError as error:
            if error.is_permanent:
                # 400/409 : l'API explique déjà pourquoi (Game lancée, Joueur, mauvais numéro)
                await self._reply(interaction, f"Pronostic refusé par Shameless : {error}")
                return
            logger.warning("shameless: pronostic de %s non transmis : %s", user_id, error)
            await self._reply(interaction, "L'API Shameless est injoignable, réessaie dans un instant.")
            return

        await self._reply(interaction, self._confirmation(choice))

    async def _reply(self, interaction, content: str) -> None:
        await interaction.response.send_message(content, ephemeral=True)

    @staticmethod
    def _display_name(interaction) -> str | None:
        user = interaction.user
        return getattr(user, "display_name", None) or getattr(user, "name", None)

    @staticmethod
    def _confirmation(choice: PronosticChoice) -> str:
        parts = []
        if choice.equipe_gagnante:
            parts.append(f"vainqueur Team {choice.equipe_gagnante}")
        if choice.mvp_player_id is not None:
            parts.append("MVP")
        if choice.dofd_player_id is not None:
            parts.append("DOFD")
        recap = ", ".join(parts) if parts else "aucun choix (pronostic retiré)"
        return f"Pronostic enregistré : {recap}."

    # =========================
    # ANNONCE DES RÉSULTATS
    # =========================

    async def _announce_results(self, game_id: int, series_id: int | None, winner: str | None = None) -> None:
        try:
            result = await self._api_client().get_game_pronostics(game_id)
        except ShamelessApiError as error:
            if error.is_permanent:
                logger.warning("shameless: pronostics de la Game %s refusés : %s", game_id, error)
                return
            raise
        if not isinstance(result, dict):
            return

        pending = False
        for title in TITLES:
            if not self._result_available(title, result):
                pending = True
                continue
            if not await asyncio.to_thread(self.store.claim_result, game_id, title):
                continue  # déjà annoncé
            channel = await self._pronostics_channel()
            await channel.send(embed=result_embed(title, result, winner=winner))
        if pending:
            if series_id is not None:
                await asyncio.to_thread(self.store.mark_pending, game_id, series_id, result.get("gameNumber"))
        else:
            await asyncio.to_thread(self.store.clear_pending, game_id)

    @staticmethod
    def _result_available(title: str, result: dict) -> bool:
        # le vainqueur se connaît à la clôture de la Game, le MVP/DOFD à la clôture des votes
        return result.get("votesClos") is True if title in (TITLE_MVP, TITLE_DOFD) else result.get("vainqueurConnu") is True

    async def reconcile_pronostics(self) -> None:
        """Re-vérifie les Games en attente : MVP/DOFD arrivent après la clôture des votes."""
        for game_id, series_id, _game_number in await asyncio.to_thread(self.store.pending):
            await self._announce_results(game_id, series_id)

    async def _reconcile_loop(self) -> None:
        interval = self.settings.pronostics_reconcile_seconds
        while True:
            await asyncio.sleep(interval)
            try:
                await self.reconcile_pronostics()
            except Exception:  # une itération ratée ne tue pas la boucle
                logger.exception("shameless: réconciliation des pronostics échouée")

    # =========================
    # HELPERS
    # =========================

    async def _pronostics_channel(self):
        channel_id = self.settings.pronostics_channel_id
        if channel_id is None:
            raise RuntimeError("SHAMELESS_PRONOSTICS_CHANNEL_ID absent : bulletin impossible")
        return self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)

    def _api_client(self) -> ShamelessApiClient:
        if self._api is None:
            self._api = client_from_settings(self.settings)
        return self._api


async def setup(bot):
    await bot.add_cog(ShamelessPronostics(bot, bot.settings.shameless))

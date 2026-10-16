"""Bouton ✅ persistant des messages de vote.

`custom_id` stable `vote:<id>:approve` : discord.py retrouve le vote après un
redémarrage dès que `bot.add_dynamic_items(VoteButton)` a été appelé (cogs/votes.py).
Le bouton ne fait que transmettre au module Vote et afficher sa réponse éphémère.
"""
from __future__ import annotations

import logging

import discord

VOTES_COG = "VotesCog"

log = logging.getLogger(__name__)


class VoteButton(discord.ui.DynamicItem[discord.ui.Button], template=r"vote:(?P<vote_id>\d+):approve"):
    def __init__(self, vote_id: int) -> None:
        super().__init__(
            discord.ui.Button(label="✅", style=discord.ButtonStyle.success, custom_id=f"vote:{vote_id}:approve")
        )
        self.vote_id = vote_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match):
        return cls(int(match["vote_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        cog = interaction.client.get_cog(VOTES_COG)
        try:
            reply = await cog.votes.approve(self.vote_id, interaction.user.id)
        except Exception:
            log.exception("vote %s : échec du bulletin de %s", self.vote_id, interaction.user.id)
            reply = "Erreur lors du vote. Réessaie plus tard."
        await interaction.followup.send(reply, ephemeral=True)


def vote_view(vote_id: int) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(VoteButton(vote_id))
    return view

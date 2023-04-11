import random
import asyncio
import discord  # Ajouter cette ligne
from discord.ext import commands, tasks


class Citation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.source_channel_id = 979525063655178270  # ID du channel source
        self.target_channel_id = 1051204919249612903  # ID du channel cible
        self.command_enabled = False  # État actuel de la commande
        self.send_random_message.start()  # Démarrer la boucle asynchrone

    def cog_unload(self):
        self.send_random_message.cancel()  # Arrêter la boucle asynchrone

    @tasks.loop(minutes=5)
    async def send_random_message(self):
        if self.command_enabled is False:
            return
        print("Citation S.A.M.")
        source_channel = self.bot.get_channel(self.source_channel_id)
        target_channel = self.bot.get_channel(self.target_channel_id)
        messages = []
        async for message in source_channel.history(limit=None):
            messages.append(message)
        if messages:
            random_message = random.choice(messages)
            try:
                await target_channel.send(f"De **{random_message.author.display_name}** : *{random_message.content}*")
            except discord.errors.Forbidden:
                print("Citation S.A.M. : pas les droits gros")
        else:
            print("Citation S.A.M. : pas de messages disponibles")


    @send_random_message.before_loop
    async def before_send_random_message(self):
        await self.bot.wait_until_ready()  # Attendre que le bot soit prêt

    @commands.command(name='citation', help='Envoie une citation aléatoire')
    async def citation(self, ctx):
        source_channel = self.bot.get_channel(self.source_channel_id)
        messages = []
        async for message in source_channel.history(limit=None):
            messages.append(message)
        if messages:
            random_message = random.choice(messages)
            await ctx.send(f"De **{random_message.author.display_name}** : *{random_message.content}*")
        else:
            await ctx.send("Il n'y a pas de message à citer.")

async def setup(bot):
    await bot.add_cog(Citation(bot))
    print("Extension Citation chargée avec succès.")

import random
import asyncio
import os
from discord.ext import commands, tasks


class Daily(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.channel_id = 1095149174430900335  # ID du channel où envoyer le message 801074831897526304
        self.blagues_folder = 'include/blagues'
        self.send_random_message.start()  # Démarrer la boucle asynchrone

    def cog_unload(self):
        self.send_random_message.cancel()  # Arrêter la boucle asynchrone

    @tasks.loop(seconds=300)  # Envoyer le message toutes les 5 minutes
    async def send_random_message(self):
        print("Zoubir Harcelement")
        channel = self.bot.get_channel(self.channel_id)
        folders = [f for f in os.listdir(self.blagues_folder) if os.path.isdir(os.path.join(self.blagues_folder, f))]
        targeted_folder = os.path.join(self.blagues_folder, random.choice(folders))
        while os.path.basename(targeted_folder) == "kenza": # On evite le dossier kenza
            targeted_folder = os.path.join(self.blagues_folder, random.choice(folders))
        files = [f for f in os.listdir(targeted_folder) if os.path.isfile(os.path.join(targeted_folder, f)) and f.endswith('.txt')]
        targeted_file = os.path.join(targeted_folder, random.choice(files))
        with open(targeted_file, 'r', encoding='utf-8') as file:
            lines = file.readlines()
            await channel.send(random.choice(lines))


    @send_random_message.before_loop
    async def before_send_random_message(self):
        await self.bot.wait_until_ready()  # Attendre que le bot soit prêt

    @commands.Cog.listener()
    async def on_ready(self):
        while not self.bot.is_closed():
            await self.send_random_message()
            await asyncio.sleep(300)  # Attendre 10 secondes


async def setup(bot):
    await bot.add_cog(Daily(bot))
    print("Extension Daily chargée avec succès.")

import os
import random
import asyncio
from discord.ext import commands, tasks


class Daily(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.channel_id = 801074831897526304  # ID du channel où envoyer le message

        self.send_random_message.start()  # Démarrer la boucle asynchrone

    def cog_unload(self):
        self.send_random_message.cancel()  # Arrêter la boucle asynchrone

    @tasks.loop(seconds=10)  # Envoyer le message toutes les 10 secondes
    async def send_random_message(self):
        channel = self.bot.get_channel(self.channel_id)
        blagues_folder = 'blagues'
        target = ["zoubir"]
        folder_path = os.path.join(blagues_folder, random.choice(target))
        await channel.send("folder_path")
        print("teesdtet")
        files = [f for f in os.listdir(folder_path) if os.path.isfile(os.path.join(folder_path, f)) and f.endswith('.txt')]
        await channel.send("foldedsfgdfgr_path")
        file_path = os.path.join(folder_path, random.choice(files))
        with open(file_path, 'r', encoding='utf-8') as file:
            lines = file.readlines()
            await channel.send(random.choice(lines))


    @send_random_message.before_loop
    async def before_send_random_message(self):
        await self.bot.wait_until_ready()  # Attendre que le bot soit prêt

    @commands.Cog.listener()
    async def on_ready(self):
        while not self.bot.is_closed():
            await self.send_random_message()
            await asyncio.sleep(10)  # Attendre 10 secondes


async def setup(bot):
    await bot.add_cog(Daily(bot))
    print("Extension Daily chargée avec succès.")

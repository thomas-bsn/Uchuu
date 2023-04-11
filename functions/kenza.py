import random
import asyncio
import os
from discord.ext import commands, tasks

temps = 300
class Kenza(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.channel_id = 1095156547786637312  # ID du channel où envoyer le message
        self.blagues_folder = 'include/blagues/kenza'
        self.send_random_message.start()  # Démarrer la boucle asynchrone

    def cog_unload(self):
        self.send_random_message.cancel()  # Arrêter la boucle asynchrone

    @tasks.loop(seconds=temps)  # Envoyer le message toutes les 10 secondes
    async def send_random_message(self):
        print("Kenza Harcelement")
        channel = self.bot.get_channel(self.channel_id)
        targeted = os.path.join(self.blagues_folder, "amoureux_fares.txt")
        with open(targeted, 'r', encoding='utf-8') as file:
            lines = [line.strip() for line in file.readlines() if line.strip()]
            await channel.send(f"<@577182193248370737> {random.choice(lines)}")


    @send_random_message.before_loop
    async def before_send_random_message(self):
        await self.bot.wait_until_ready()  # Attendre que le bot soit prêt

    @commands.Cog.listener()
    async def on_ready(self):
        while not self.bot.is_closed():
            await self.send_random_message()
            await asyncio.sleep(temps)  # Attendre 10 secondes


async def setup(bot):
    await bot.add_cog(Kenza(bot))
    print("Extension Kenza chargée avec succès.")

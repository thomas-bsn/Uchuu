import random
import discord
from discord.ext import commands

class Agresseur(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='agresseur', help='Insulte un utilisateur au hasard')
    async def agresseur(self, ctx, user: discord.Member):
        # Ouvre le fichier insulte.txt
        with open('include/insultes/insulte.txt', 'r') as file:
            # Lit les lignes du fichier et les stocke dans une liste
            insultes = file.readlines()
        # Sélectionne une insulte aléatoirement dans la liste
        insulte = random.choice(insultes)
        # Mentionne l'utilisateur et envoie l'insulte
        await ctx.send(f'{user.mention} {insulte}')

async def setup(bot):
    await bot.add_cog(Agresseur(bot))
    print("Extension Agresseur chargée avec succès.")

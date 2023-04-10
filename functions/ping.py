from discord.ext import commands

class Ping(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def ping(self, ctx):
        await ctx.send('Ta gueule le zink')

async def setup(bot):  # Changez cette ligne pour définir la fonction setup comme asynchrone
    await bot.add_cog(Ping(bot))  # Ajoutez 'await' avant bot.add_cog(Ping(bot))
    print("Extension Ping chargée avec succès.")  # Ajoutez cette ligne

from discord.ext import commands

class Commands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='commands', help='Affiche la liste des commandes disponibles')
    async def cmd(self, ctx):
        response = "Liste des commandes disponibles :\n\n"
        for command in self.bot.commands:
            response += f"{command.name} : {command.help}\n"
        await ctx.send(response)

async def setup(bot):
    await bot.add_cog(Commands(bot))
    print("Extension Commands chargée avec succès.")

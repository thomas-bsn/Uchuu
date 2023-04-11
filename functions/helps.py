from discord.ext import commands

class Help(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='helps', help='Affiche la liste des commandes disponibles')
    async def help_command(self, ctx, *args):
        if not args:
            # Si aucun argument n'est donné, afficher la liste des commandes disponibles
            response = "Liste des commandes disponibles :\n\n"
            for command in self.bot.commands:
                response += f"{command.name} : {command.help}\n"
            await ctx.send(response)
        else:
            # Sinon, afficher l'aide pour la commande donnée
            command = args[0]
            if command := self.bot.get_command(command):
                response = f"Aide pour la commande `{command.name}` :\n"
                response += f"Description : {command.help}\n"
                response += f"Utilisation : `{self.bot.command_prefix}{command.name} {command.signature}`"
                await ctx.send(response)
            else:
                await ctx.send(f"La commande `{command}` n'existe pas.")

async def setup(bot):
    await bot.add_cog(Help(bot))
    print("Extension Help chargée avec succès.")

import discord
from discord.ext import commands

class Clean(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='clean', help='Supprime un certain nombre de messages ou les messages d\'un utilisateur')
    async def clean(self, ctx, number: int, user: discord.Member = None):
        if number < 0 or number > 100:
            await ctx.send("Le nombre de messages à supprimer doit être compris entre 0 et 100.")
            return
        if not ctx.author.guild_permissions.manage_messages:
            await ctx.send("J'ai pas les droits gros")
            print("Clean : J'ai pas les droits gros")
            return
        if user is not None:
            def is_user_message(message):
                return message.author == user
            deleted = await ctx.channel.purge(limit=number+1, check=is_user_message)
            await ctx.send(f"{len(deleted)-1} messages de {user.mention} ont été supprimés.")
        else:
            deleted = await ctx.channel.purge(limit=number+1)
            await ctx.send(f"{len(deleted)-1} messages ont été supprimés.")

    @clean.error
    async def clean_error(self, ctx, error):
        if isinstance(error, commands.BadArgument):
            await ctx.send('Mentionne un utilisateur valide.')
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send('Il manque un argument : nombre de messages à supprimer.')


async def setup(bot):
    await bot.add_cog(Clean(bot))
    print("Extension Clean chargée avec succès.")

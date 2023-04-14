import discord
from discord.ext import commands

DELETE_LIMIT = 100
DELETE_ERROR_MESSAGE = "Le nombre de messages à supprimer doit être compris entre 0 et 100."
PERMISSION_ERROR_MESSAGE = "Vous n'avez pas les permissions nécessaires pour effectuer cette action."
USER_NOT_FOUND_ERROR_MESSAGE = "Mentionne un utilisateur valide."
MISSING_ARGUMENT_ERROR_MESSAGE = "Il manque un argument : nombre de messages à supprimer."


class Clean(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def delete_messages(self, ctx, number, user=None):
        if number < 0 or number > DELETE_LIMIT:
            await ctx.send(DELETE_ERROR_MESSAGE)
            return

        if not ctx.author.guild_permissions.manage_messages:
            await ctx.send(PERMISSION_ERROR_MESSAGE)
            return

        if user is not None:
            messages = []
            async for message in ctx.channel.history(limit=DELETE_LIMIT):
                if message.author == user:
                    messages.append(message)
                    if len(messages) == number:
                        break
            await ctx.channel.delete_messages(messages)
            await ctx.send(f"{len(messages)} messages de {user.mention} ont été supprimés.")
        else:
            deleted = await ctx.channel.purge(limit=number)
            await ctx.send(f"{len(deleted)} messages ont été supprimés.")

    @commands.command(name='clean', help='Supprime un certain nombre de messages ou les messages d\'un utilisateur')
    async def clean(self, ctx, number: int, user: discord.Member = None):
        await self.delete_messages(ctx, number, user)

    @clean.error
    async def clean_error(self, ctx, error):
        if isinstance(error, commands.BadArgument):
            await ctx.send(USER_NOT_FOUND_ERROR_MESSAGE)
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(MISSING_ARGUMENT_ERROR_MESSAGE)


async def setup(bot):
    await bot.add_cog(Clean(bot))
    print("Extension Clean chargée avec succès.")

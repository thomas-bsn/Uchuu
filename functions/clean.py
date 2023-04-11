import discord
from discord.ext import commands

class Clean(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='clean', help='Supprime un certain nombre de messages')
    async def clean(self, ctx, number: int):
        if number < 0 or number > 100:
            await ctx.send("Le nombre de messages à supprimer doit être compris entre 0 et 100.")
            return
        if not ctx.author.guild_permissions.manage_messages:
            await ctx.send("J'ai pas les droits gros")
            print("Clean : J'ai pas les droits gros")
            return
        try:
            deleted = await ctx.channel.purge(limit=number+1)
            await ctx.send(f"{len(deleted)-1} messages ont été supprimés.")
        except discord.errors.Forbidden:
            print("Clean : J'ai pas les droits gros")

async def setup(bot):
    await bot.add_cog(Clean(bot))
    print("Extension Clean chargée avec succès.")

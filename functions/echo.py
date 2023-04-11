import discord
from discord.ext import commands

class Echo(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.source_channel = bot.get_channel(801074831897526304)  # ID du channel source
        self.dest_channel = bot.get_channel(801074831897526304)  # ID du channel de destination

    @commands.command(name='echo', help='Répète le message sur un autre channel')
    async def echo(self, ctx, *args):
        if not args:
            await ctx.send("Il faut un message à répéter.")
            return
        message = " ".join(args)
        if not message:
            await ctx.send("Le message ne peut pas être vide.")
            return
        await self.dest_channel.send(message)



async def setup(bot):
    await bot.add_cog(Echo(bot))
    print("Extension Echo chargée avec succès.")

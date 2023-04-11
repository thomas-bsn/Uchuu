from discord.ext import commands
from include.libs.functions import *

class Target(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.target_file_path = 'include/target.txt'
        self.user_id_to_check = load_user_id_to_check(self.target_file_path)

    @commands.command(name='target', help='Affiche la liste des utilisateurs à target')
    async def target(self, ctx):
        self.user_id_to_check = load_user_id_to_check(self.target_file_path)
        # Create the formatted string to send
        target_list = "Liste des utilisateurs à target :```"
        for name, user_id in self.user_id_to_check.items():
            target_list += f"\n- {name:<12} | {user_id}"
        target_list += "```"

        # Send the target list to the channel
        await ctx.send(target_list)
        print_user_id_to_check(self.user_id_to_check)


async def setup(bot):
    await bot.add_cog(Target(bot))
    print("Extension Target chargée avec succès.")

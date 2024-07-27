import discord
from discord.ext import commands
import os
import requests

class ProfilePictures(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='download_pp', help='Télécharge les PP de tous les membres et les envoie dans le canal.')
    async def download_pp(self, ctx):
        if not os.path.exists('pp_members'):
            os.makedirs('pp_members')

        await ctx.guild.chunk()
        print([member.name for member in ctx.guild.members])
        for member in ctx.guild.members:
            if member.avatar:
                avatar_url = member.avatar.url
                response = requests.get(avatar_url)
                
                # Utilisez le pseudo de l'utilisateur comme nom de fichier, en remplaçant les caractères non valides
                sanitized_name = "".join([c if c.isalnum() else "_" for c in member.name])
                file_path = os.path.join('pp_members', f'{sanitized_name}.png')
                
                with open(file_path, 'wb') as file:
                    file.write(response.content)
                
                await ctx.send(file=discord.File(file_path, f'{sanitized_name}.png'))
                # os.remove(file_path)  # Supprimez le fichier après l'envoi pour économiser de l'espace disque
        print('Téléchargement terminé.')

async def setup(bot):
    await bot.add_cog(ProfilePictures(bot))
    print("Extension ProfilePictures chargée avec succès.")

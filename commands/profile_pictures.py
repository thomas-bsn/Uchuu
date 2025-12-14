import discord
from discord.ext import commands
import os
import requests

class ProfilePictures(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='download_pp', help='Télécharge les PP de tous les membres et les envoie dans le canal.')
    async def download_pp(self, ctx):
        print("Commande download_pp lancée.")

        # Crée le dossier pour stocker les avatars
        if not os.path.exists('include/pp_members'):
            os.makedirs('include/pp_members')
            print("Répertoire 'pp_members' créé.")

        # Vide le répertoire s'il existe déjà
        for file in os.listdir('include/pp_members'):
            os.remove(os.path.join('include/pp_members', file))
            print(f"Fichier supprimé: {file}")

        # Utilisation de ctx.guild.members pour récupérer les membres directement
        # ctx.guild.members contient les membres qui ont déjà été chargés dans le cache du bot
        print("Membres du serveur chargés.")

        for member in ctx.guild.members:
            if member.bot:
                continue  # Ignore les bots
            print(f"Traitement de {member.name}...")

            # Vérifie si le membre a un avatar
            if member.avatar:
                avatar_url = member.avatar.url
                print(f"Téléchargement de l'avatar pour {member.name} : {avatar_url}")

                # Télécharge l'avatar
                response = requests.get(avatar_url)
                if response.status_code == 200:
                    print(f"Avatar de {member.name} téléchargé avec succès.")
                    sanitized_name = "".join([c if c.isalnum() else "_" for c in member.name])
                    file_path = os.path.join('include/pp_members', f'{sanitized_name}.png')
                    
                    # Sauvegarde l'avatar en local
                    with open(file_path, 'wb') as file:
                        file.write(response.content)

                    # Envoie le fichier dans le canal
                    await ctx.send(file=discord.File(file_path, f'{sanitized_name}.png'))
                    print(f"Avatar de {member.name} envoyé dans le canal.")
                    
                    # os.remove(file_path)  # Optionnel : Supprime le fichier après l'envoi pour économiser de l'espace disque
                else:
                    print(f"Échec du téléchargement de l'avatar de {member.name}, statut HTTP: {response.status_code}")
            else:
                print(f"{member.name} n'a pas d'avatar.")
        
        print('Téléchargement terminé.')

async def setup(bot):
    await bot.add_cog(ProfilePictures(bot))
    print("Extension ProfilePictures chargée avec succès.")

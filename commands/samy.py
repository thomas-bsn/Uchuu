import discord
import os
import random
from discord.ext import commands
from moviepy.editor import *
from typing import Optional

#path = "/mnt/d/Vidéos/"
path = "/mnt/e/Vidéos/"

# liste_dossiers = ["SCP  Secret Laboratory","Among Us","Call of Duty  Black Ops 3",
#            "Game.exe","EA Desktop","Elden Ring","Detroit  Become Human",
#            "Counter-strike  Global Offensive","Call of Duty  Modern Warfare 2 (2022)",
#            "Call of Duty  Modern Warfare 2019","Garry's Mod","Fortnite","Roblox VR",
#            "Phasmophobia","VRChat","Portal 2","Star Wars Jedi  Fallen Order","Desktop",
#            "League of Legends","Sea of Thieves","Valorant","Base Profile","Tiger","Stray",
#            "Overwatch 2","NieR Automata","Muck","Fall Guys","4dcd188552ce8876d5e55e1f6d22505109bfa4cb","1.7"]


liste_dossiers = ["Among Us", "Desktop", "League of Legends", "Plutonium",
    "BlueStacks", "Elden Ring", "Lethal Company", "Roblox VR",
    "Content Warning", "Fortnite", "Lethal Company mods", "SCP Secret Laboratory",
    "Counter-strike 2", "Garry's Mod", "Lies of P", "Tekken 8",
    "Dark Souls III", "Hollow Knight", "Valorant"]


class Samy(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.video_folder_path = path + random.choice(liste_dossiers)
        self.max_file_size = 8 * 1024 * 1024  # 8 Mo
        self.game_name = os.path.basename(self.video_folder_path)

    async def compress_video(self, video_file_path, compressed_video_file_path, quality=23):
        video = VideoFileClip(video_file_path)
        video_bitrate = f"{video.reader.fps * video.size[0] * video.size[1] * 0.1}k"  # Calculate a reasonable bitrate based on video dimensions and fps
        video.write_videofile(compressed_video_file_path, codec='libx264', audio_codec='aac', bitrate=video_bitrate, ffmpeg_params=['-crf', str(quality)])
        video.close()

    async def pretty_video_info(self, video_file_name, video_file_path, video_file_size, video_duration):
        name_length = len(os.path.splitext(video_file_name)[0])
        frame_length = name_length + 24
        frame_top = "+" + "=" * frame_length + "+"
        name_line = f"- Vidéo sélectionnée : {os.path.splitext(video_file_name)[0]}"
        size_line = f"- Taille : {video_file_size / 1024 / 1024:.2f} Mo"
        duration_line = f"- Durée : {video_duration:.2f} secondes"
        print(f"{frame_top}\n{name_line}\n\n{size_line}\n\n{duration_line}\n{frame_top}")



    @commands.command(name='videoslist', help=f'Liste les vidéos du dossier')
    async def videoslist(self, ctx):
        message = "Voici la liste des dossiers (à copier à l'espace près avec les guillemets):\n"
        for item in liste_dossiers:
            print("\"" + item + "\"")
            message += "\"" + item + "\"" + "\n"
        await ctx.send("```" + message + "```")


    @commands.command(name='samy', help=f'Envoie une vidéo aléatoire de la liste des jeux (Fais $videoslist)')
    async def samy(self, ctx, *args):
        if len(args) > 0 and not args[0].startswith('-'):
            await ctx.send(f"L'argument '{args[0]}' n'est pas valide.")
            await ctx.send(f"Usage : `$samy [-d \"nom_dossier\"] [-t \"date\"]` (utilisez la commande $videoslist pour obtenir la liste des dossiers)")
            return

        dossier_selectionne = ''
        annee_selectionnee = ''
        for i in range(len(args)):
            if args[i] == '-d' and i < len(args) - 1:
                dossier_selectionne = args[i + 1]
            elif args[i] == '-t' and i < len(args) - 1:
                annee_selectionnee = args[i + 1]
            elif args[i].startswith('-'):
                await ctx.send(f"L'argument '{args[i]}' n'est pas valide.")
                await ctx.send(f"Usage : `$samy [-d \"nom_dossier\"] [-t \"date\"]` (utilisez la commande $videoslist pour obtenir la liste des dossiers)")
                return

        video_files = []

        if annee_selectionnee != '':
            for folder in liste_dossiers:
                folder_path = path + folder
                folder_files = os.listdir(folder_path)
                # Filtrer les fichiers qui ne sont pas des vidéos
                folder_files = [f for f in folder_files if f.endswith(('.mp4', '.avi', '.mkv'))]
                # Rechercher les fichiers contenant l'année dans leur nom
                folder_files = [f for f in folder_files if annee_selectionnee in f]
                video_files.extend([(folder, f) for f in folder_files])

            if len(video_files) == 0:
                await ctx.send(f"Il n'y a pas de vidéos de la date '{annee_selectionnee}'.")
                return

            if dossier_selectionne != '':
                video_files = [f for f in video_files if f[0] == dossier_selectionne]

                if len(video_files) == 0:
                    await ctx.send(f"Le dossier '{dossier_selectionne}' ne contient pas de vidéos de la date '{annee_selectionnee}'.")
                    return

            random_folder, random_video_file = random.choice(video_files)
            video_folder_path = path + random_folder
        else:
            if dossier_selectionne != '':
                video_folder_path = path + dossier_selectionne
            else:
                video_folder_path = path + random.choice(liste_dossiers)

            video_files = os.listdir(video_folder_path)
            video_files = [f for f in video_files if f.endswith(('.mp4', '.avi', '.mkv'))]

            if len(video_files) == 0:
                await ctx.send(f"Le dossier '{dossier_selectionne}' ne contient pas de vidéos.")
                return

            random_video_file = random.choice(video_files)

        video_file_path = os.path.join(video_folder_path, random_video_file)
        video_file_size = os.path.getsize(video_file_path)
        video_size_mb = round(video_file_size / (1024 * 1024), 2)
        video_duration = VideoFileClip(video_file_path).duration

        await self.pretty_video_info(random_video_file, video_file_path, video_file_size, video_duration)

        # Envoie le message indiquant que la vidéo est en cours d'envoi
        await ctx.send(f"Envoi de la vidéo : `{os.path.splitext(random_video_file)[0]}`")
        await ctx.send(f"Taille : {video_size_mb:.2f} Mo | Durée : {video_duration:.2f} secondes")
        await ctx.send("Ne spammez pas et veuillez patienter...")
        if video_file_size > self.max_file_size:
            # Compresser la vidéo
            compressed_video_file_path = os.path.join("include", "traitement_video", "compressed_" + random_video_file)
            await self.compress_video(video_file_path, compressed_video_file_path)
            # Envoie la vidéo compressée
            await ctx.send(file=discord.File(compressed_video_file_path))
            # Supprimer la vidéo compressée après l'envoi
            os.remove(compressed_video_file_path)
        else:
            await ctx.send(file=discord.File(video_file_path))

   





async def setup(bot):
    await bot.add_cog(Samy(bot))
    print("Extension Samy chargée avec succès.")

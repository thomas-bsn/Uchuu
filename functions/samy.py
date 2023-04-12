import discord
import os
import random
from discord.ext import commands
from moviepy.editor import *

path = "/mnt/d/Vidéos/SCP  Secret Laboratory"

class Samy(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.video_folder_path = path
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
        name_line = f"| Vidéo sélectionnée : {os.path.splitext(video_file_name)[0]}"
        size_line = f"| Taille : {video_file_size / 1024 / 1024:.2f} Mo"
        duration_line = f"| Durée : {video_duration:.2f} secondes"
        print(f"{frame_top}\n{name_line}\n\n{size_line}\n\n{duration_line}\n{frame_top}")





    @commands.command(name='samy', help=f'Envoie une vidéo aléatoire de {os.path.basename(path)}')
    async def samy(self, ctx):
        # Liste les fichiers du dossier de vidéos
        video_files = os.listdir(self.video_folder_path)
        # Filtrer les fichiers qui ne sont pas des vidéos
        video_files = [f for f in video_files if f.endswith(('.mp4', '.avi', '.mkv'))]
        # Vérifie si il y a des vidéos dans le dossier
        if len(video_files) == 0:
            await ctx.send("Il n'y a pas de vidéos dans le dossier.")
            return
        # Sélectionne un fichier vidéo aléatoire
        random_video_file = random.choice(video_files)
        # Vérifie la taille du fichier vidéo
        video_file_path = os.path.join(self.video_folder_path, random_video_file)
        video_file_size = os.path.getsize(video_file_path)
        video_size_mb = round(video_file_size / (1024 * 1024), 2)
        # Vérifie la durée de la vidéo
        video_duration = VideoFileClip(video_file_path).duration

        # Affiche le poids et la durée de la vidéo sélectionnée
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
            # Envoie le fichier vidéo
            await ctx.send(file=discord.File(video_file_path))

async def setup(bot):
    await bot.add_cog(Samy(bot))
    print("Extension Samy chargée avec succès.")

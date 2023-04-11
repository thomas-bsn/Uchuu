import os
import random
import discord
import moviepy.editor as mp
from discord.ext import commands
from include.libs.functions import *

class MessageReaction(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.target_file_path = 'include/target.txt'
        self.user_id_to_check = load_user_id_to_check(self.target_file_path)
        self.command_enabled = False  # État actuel de la commande
        print_user_id_to_check(self.user_id_to_check)

    async def lgbt(self, message):
        emojis = ["🏳️‍🌈", "🌈", "💜", "❤️‍🔥", "❤️‍🩹", "🌟", "🦄", "🐾", "🎉", "🎊", "🎈", "🎁", "🎶", "🍻", "🍷", "🍔", "🍟", "🍕", "🌺", "🌸", "🌼", "🌻", "🌹"]
        for emoji in emojis:
            await message.add_reaction(emoji)
    
    async def dispense(self, message):
        pass

    @commands.command(name='manyl', help='Envoie une photo au pif')
    async def manyl(self, message):
        folder = 'include/pictures'
        gif_path = os.path.join(folder, random.choice(os.listdir(folder)))
        await message.channel.send(file=discord.File(gif_path))

    async def gif(self, message):
        folder = 'include/pictures'
        gif_path = os.path.join(folder, random.choice(os.listdir(folder)))
        await message.channel.send("PLEURE") 
        await message.channel.send(file=discord.File(gif_path))

    async def insulte_walid(self, message):
        folder = 'include/insultes'
        file_path = os.path.join(folder, random.choice(os.listdir(folder)))

        with open(file_path, 'r', encoding='utf-8') as file:
            content = file.read()

        for chunk in [content[i:i+2000] for i in range(0, len(content), 2000)]:
            await message.channel.send(chunk)

    async def random_function(self, message):
        functions_list = [self.lgbt, self.gif, self.insulte_walid, self.dispense]
        random_function = random.choice(functions_list)
        # si la fonction est lgbt, on ne mentionne pas l'utilisateur
        if message.author.id in self.user_id_to_check.values():
            user_index = list(self.user_id_to_check.keys())[list(self.user_id_to_check.values()).index(message.author.id)]
            print(f"{user_index} : {random_function.__name__}")
        if random_function == self.lgbt:
            await random_function(message)
        elif random_function == self.dispense:
            await random_function(message)
        else:
            await message.channel.send(f"<@{message.author.id}>")
            await random_function(message)

    @commands.Cog.listener()
    async def on_message(self, message):
        self.user_id_to_check = load_user_id_to_check(self.target_file_path)

        if self.command_enabled is False:
            return

        # Vérifier que le message n'est pas une commande
        if not message.content.startswith(self.bot.command_prefix):
            # on regarde si l'id est dans la liste
            if message.author.id in self.user_id_to_check.values():
                # si c'est thomas on skip
                try:
                    if message.author.id == self.user_id_to_check['thomas']:
                        print("Je m'attaque PAS")
                        #pass
                        await self.lgbt(message)
                        # await self.random_function(message)
                    elif message.author.id == self.user_id_to_check['yazid']:
                        await message.channel.send(f"Arrete de flirter avec FEMME <@{message.author.id}>") 
                        await self.random_function(message)
                    elif message.author.id == self.user_id_to_check['zoubir']:
                        await message.channel.send("Alexandre le grand est une grosse pute et GEN G est une equipe de merde, faut vraiment etre timbré mentalement pour idolatrer ces trucs")
                        await self.random_function(message)
                    elif message.author.id == self.user_id_to_check['nabil']:
                        await message.channel.send("Mon petit cochon d'ARAP, tu veux que je te fasse un petit cadeau ?")
                        await self.random_function(message)
                    elif message.author.id == self.user_id_to_check['leila']:
                        await message.channel.send("ARRETE DE FLEURTER AVEC FEMBOYS SUBMISSIVES")
                        await self.gif(message)
                        await self.random_function(message)
                    else:
                        await self.random_function(message)
                    # Permettre aux commandes de fonctionner normalement
                    await self.bot.process_commands(message)
                except:
                    pass
                
    @commands.command(name='turn', help='Activer ou désactiver le listener on_message.')
    async def turn(self, ctx, value: str = None):
        if value is None:
            await ctx.send('La commande nécessite un argument "on" ou "off".')
            return

        if value == 'on':
            self.command_enabled = True
            await ctx.send('Le listener on_message a été activé.')
        elif value == 'off':
            self.command_enabled = False
            await ctx.send('Le listener on_message a été désactivé.')
        else:
            await ctx.send('La valeur doit être "on" ou "off".')






async def setup(bot):
    await bot.add_cog(MessageReaction(bot))
    print("Extension MessageReaction chargée avec succès.") 

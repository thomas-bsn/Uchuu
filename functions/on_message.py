import os
import random
import discord
import moviepy.editor as mp
from discord.ext import commands


file_path = 'include/target.txt'
user_id_to_check = {}
with open(file_path, 'r', encoding='utf-8') as file:
    for line in file:
        name, user_id = line.strip().split(':')
        user_id_to_check[name] = int(user_id)

# user_id_to_check = \
# {'zoubir': 290513038929428481, 
# 'sam': 342659019309056001, 
# 'thomas': 188407821300137984,
# 'inha': 992063376396132383,
# 'zepey': 1075218280291242057,
# 'kenza': 577182193248370737,
# 'nabil': 287316198465470464,
# 'yazid': 238702975713804288,
# 'yanis': 831117097668050968,
# 'leila': 352191522369699841,}

class MessageReaction(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def lgbt(self, message):
        await message.add_reaction("🏳️‍🌈")
    
    async def dispense(self, message):
        pass

    async def gif(self, message):
        folder = 'include/pictures'
        gif_path = os.path.join(folder, random.choice(os.listdir(folder)))
        await message.channel.send("PLEURE") 
        await message.channel.send(file=discord.File(gif_path))

    # async def gif(self, message):
    #     folder = 'include/pictures'
    #     gif_path = os.path.join(folder, random.choice(os.listdir(folder)))
    #     clip = mp.VideoFileClip(gif_path)
    #     clip_resized = clip.resize(height=480)
    #     resized_path = os.path.splitext(gif_path)[0] + "_resized.mp4"
    #     clip_resized.write_videofile(resized_path)
    #     await message.channel.send("PLEURE") 
    #     await message.channel.send(file=discord.File(resized_path))
    #     clip.close()
    #     clip_resized.close()
    #     os.remove(resized_path)

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
        user_index = list(user_id_to_check.keys())[list(user_id_to_check.values()).index(message.author.id)]
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
        # Vérifier que le message n'est pas une commande
        if not message.content.startswith(self.bot.command_prefix):
            # on regarde si l'id est dans la liste
            if message.author.id in user_id_to_check.values():
                # si c'est thomas on skip
                if message.author.id == user_id_to_check['thomas']:
                    print("Je m'attaque PAS")
                    pass
                    # await self.gif(message)
                    # await self.random_function(message)
                elif message.author.id == user_id_to_check['yazid']:
                    await message.channel.send(f"Arrete de flirter avec FEMME <@{message.author.id}>") 
                    await self.random_function(message)
                elif message.author.id == user_id_to_check['zoubir']:
                    await message.channel.send("Alexandre le grand est une grosse pute et GEN G est une equipe de merde, faut vraiment etre timbré mentalement pour idolatrer ces trucs")
                    await self.random_function(message)
                elif message.author.id == user_id_to_check['nabil']:
                    await message.channel.send("Mon petit cochon d'ARAP, tu veux que je te fasse un petit cadeau ?")
                    await self.random_function(message)
                elif message.author.id == user_id_to_check['leila']:
                    await message.channel.send("ARRETE DE FLEURTER AVEC FEMBOYS SUBMISSIVES")
                    await self.gif(message)
                    await self.random_function(message)
                else:
                    await self.random_function(message)
            # Permettre aux commandes de fonctionner normalement
            await self.bot.process_commands(message)

async def setup(bot):
    await bot.add_cog(MessageReaction(bot))
    print("Extension MessageReaction chargée avec succès.") 

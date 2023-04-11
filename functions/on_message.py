import os
import random
from discord.ext import commands

class MessageReaction(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def lgbt(self, message):
        await message.add_reaction("🏳️‍🌈")
    
    async def dispense(self, message):
        pass

    async def gif(self, message):
        await message.channel.send('https://media.discordapp.net/attachments/1011640076725395487/1079110434436681901/crack-1.gif?width=457&height=517')

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
        if random_function == self.lgbt:
            await random_function(message)
        else:
            await message.channel.send(f"<@{message.author.id}>")
            await random_function(message)

    @commands.Cog.listener()
    async def on_message(self, message):
        # Vérifier que le message n'est pas une commande
        if not message.content.startswith(self.bot.command_prefix):
            # ID de l'utilisateur à vérifier
            user_id_to_check = \
            {'zoubir': 290513038929428481, 
             'sam': 342659019309056001, 
             'thomas': 188407821300137984,
             'inha': 992063376396132383,
             'zepey': 1075218280291242057,
             'kenza': 577182193248370737,
             'nabil': 287316198465470464,
             'yazid': 238702975713804288,
             'yanis': 831117097668050968,}

            # on regarde si l'id est dans la liste
            if message.author.id in user_id_to_check.values():
                # si c'est thomas on skip
                if message.author.id == user_id_to_check['thomas']:
                    pass
                    # await self.insulte_walid(message)
                else:
                    await self.random_function(message)
            # Permettre aux commandes de fonctionner normalement
            await self.bot.process_commands(message)

async def setup(bot):
    await bot.add_cog(MessageReaction(bot))
    print("Extension MessageReaction chargée avec succès.") 

import discord
from discord.ext import commands

# Remplacez ceci par le jeton d'accès de votre bot
TOKEN = 'OTg5NTEzNTIzMzU5MDA2ODAw.GBxAHz.LuyFaEMiQounD4sPoUKW7LVpIArP1L2a516E98'

intents = discord.Intents.default()
intents.message_content = True  # Ajoutez cette ligne pour activer l'intent message_content
bot = commands.Bot(command_prefix='$', intents=intents)

@bot.event
async def on_ready():
    print(f'{bot.user.name} est prêt.')
    await bot.change_presence(activity=discord.Game("Je ferai l'inaceptable"))
    await bot.load_extension('functions.ping')  # Modifiez cette ligne pour charger l'extension ping
    await bot.load_extension('functions.on_message')  # Modifiez cette ligne pour charger l'extension on_message
    await bot.load_extension('functions.helps')  # Modifiez cette ligne pour charger l'extension commands
    await bot.load_extension('functions.daily')  # Modifiez cette ligne pour charger l'extension daily
    # await bot.load_extension('functions.kenza')  # Modifiez cette ligne pour charger l'extension kenza
    await bot.load_extension('functions.target')  

bot.run(TOKEN)

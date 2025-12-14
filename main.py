import discord
from discord.ext import commands

# Remplacez ceci par le jeton d'accès de votre bot
TOKEN = 'OTg5NTEzNTIzMzU5MDA2ODAw.GBxAHz.LuyFaEMiQounD4sPoUKW7LVpIArP1L2a516E98'

intents = discord.Intents.default()
intents.members = True
intents.message_content = True  # Ajoutez cette ligne pour activer l'intent message_content
bot = commands.Bot(command_prefix='$$', intents=intents)

@bot.event
async def on_ready():
    print(f'{bot.user.name} est prêt.')
    await bot.change_presence(activity=discord.Game("Je ferai l'inaceptable"))
    await bot.load_extension('commands.ping')  # Modifiez cette ligne pour charger l'extension ping
    await bot.load_extension('commands.on_message')  # Modifiez cette ligne pour charger l'extension on_message
    await bot.load_extension('commands.helps')  # Modifiez cette ligne pour charger l'extension commands
    # await bot.load_extension('commands.daily')  # Modifiez cette ligne pour charger l'extension daily
    # await bot.load_extension('commands.kenza')  # Modifiez cette ligne pour charger l'extension kenza
    # await bot.load_extension('commands.target')  
    # await bot.load_extension('commands.agresseur')
    # await bot.load_extension('commands.echo')
    await bot.load_extension('commands.clean')
    # await bot.load_extension('commands.citation')
    # await bot.load_extension('commands.samy')
    await bot.load_extension('commands.profile_pictures')
    await bot.load_extension("cogs.verification")
bot.run(TOKEN)

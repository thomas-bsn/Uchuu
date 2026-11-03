from discord.ext import commands

MAX_MESSAGE = 1900  # Discord limite un message à 2000 caractères


def split_message(text: str) -> list[str]:
    chunks, current = [], ""
    for line in text.split("\n"):
        if current and len(current) + len(line) + 1 > MAX_MESSAGE:
            chunks.append(current)
            current = ""
        current += ("\n" if current else "") + line
    return chunks + [current] if current else chunks


def signature(command) -> str:
    """Signature affichée ; pour un groupe : ses sous-commandes."""
    if isinstance(command, commands.Group) and command.commands:
        return "<" + "|".join(sub.name for sub in command.commands) + ">"
    return command.signature


def detail(command, prefix: str) -> str:
    lines = [
        f"Aide pour la commande `{command.qualified_name}` :",
        f"Description : {command.help}",
        f"Utilisation : `{prefix}{command.qualified_name} {signature(command)}`",
    ]
    if params := command.extras.get("params"):
        lines.append(f"Paramètres : {params}")
    if permission := command.extras.get("permission"):
        lines.append(f"Permission : {permission}")
    lines += [f"Exemple : `{prefix}{example}`" for example in command.extras.get("examples", [])]
    return "\n".join(lines)


class Help(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='helps', help='Affiche la liste des commandes disponibles')
    async def help_command(self, ctx, *args):
        if not args:
            # Si aucun argument n'est donné, afficher la liste des commandes disponibles
            response = "Liste des commandes disponibles :\n\n"
            commands_list = [f"{command.name:<20}{command.help:<20}{signature(command):<20}" for command in self.bot.commands]
            response += "\n".join(commands_list)
            for chunk in split_message(response):
                await ctx.send(chunk)
        else:
            # Sinon, afficher l'aide pour la commande donnée (et ses sous-commandes pour un groupe)
            name = " ".join(args)
            if command := self.bot.get_command(name):
                blocks = [detail(command, self.bot.command_prefix)]
                if isinstance(command, commands.Group):
                    blocks += [detail(sub, self.bot.command_prefix) for sub in command.commands]
                for chunk in split_message("\n\n".join(blocks)):
                    await ctx.send(chunk)
            else:
                await ctx.send(f"La commande `{name}` n'existe pas.")


async def setup(bot):
    await bot.add_cog(Help(bot))
    print("Extension Help chargée avec succès.")

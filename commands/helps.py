from discord.ext import commands

MAX_MESSAGE = 1900  # Discord limite un message à 2000 caractères


def slash_commands(bot):
    """Commandes slash (groupes dépliés en sous-commandes), dans l'ordre de l'arbre."""
    found = []
    for command in bot.tree.get_commands():
        found.extend(command.walk_commands() if hasattr(command, "walk_commands") else [command])
    return [c for c in found if hasattr(c, "callback")]


def slash_usage(command) -> str:
    params = " ".join(f"<{p.name}>" if p.required else f"[{p.name}]" for p in command.parameters)
    return f"/{command.qualified_name} {params}".strip()


def slash_detail(command) -> str:
    lines = [f"**`{slash_usage(command)}`** — {command.description}"]
    lines += [f"  • `{p.name}` ({'requis' if p.required else 'optionnel'}) : {p.description}" for p in command.parameters]
    if permission := command.extras.get("permission"):
        lines.append(f"  Permission : {permission}")
    lines += [f"  Exemple : `{example}`" for example in command.extras.get("examples", [])]
    return "\n".join(lines)


def split_message(text: str) -> list[str]:
    chunks, current = [], ""
    for line in text.split("\n"):
        if current and len(current) + len(line) + 1 > MAX_MESSAGE:
            chunks.append(current)
            current = ""
        current += ("\n" if current else "") + line
    return chunks + [current] if current else chunks


class Help(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='helps', help='Affiche la liste des commandes disponibles')
    async def help_command(self, ctx, *args):
        slash = slash_commands(self.bot)
        if not args:
            # Si aucun argument n'est donné, afficher la liste des commandes disponibles
            response = "Liste des commandes disponibles :\n\n"
            commands_list = [f"{command.name:<20}{command.help:<20}{command.signature:<20}" for command in self.bot.commands]
            response += "\n".join(commands_list)
            if slash:
                response += "\n\nCommandes slash (détails : `helps <groupe>`, ex. `helps secret-santa`) :\n"
                response += "\n".join(f"{slash_usage(c)} — {c.description}" for c in slash)
            for chunk in split_message(response):
                await ctx.send(chunk)
        else:
            # Sinon, afficher l'aide pour la commande donnée (préfixe, sinon slash / groupe slash)
            name = args[0].lstrip("/")
            if command := self.bot.get_command(name):
                response = f"Aide pour la commande `{command.name}` :\n"
                response += f"Description : {command.help}\n"
                response += f"Utilisation : `{self.bot.command_prefix}{command.name} {command.signature}`"
                await ctx.send(response)
            elif matches := [c for c in slash if c.qualified_name == name or c.qualified_name.startswith(name + " ")]:
                response = f"Aide pour `/{name}` :\n\n" + "\n\n".join(slash_detail(c) for c in matches)
                for chunk in split_message(response):
                    await ctx.send(chunk)
            else:
                await ctx.send(f"La commande `{name}` n'existe pas.")


async def setup(bot):
    await bot.add_cog(Help(bot))
    print("Extension Help chargée avec succès.")

"""Hygiène du démarrage : chaque extension déclarée s'importe avec les seules
dépendances déclarées (requirements.txt) et expose le point d'entrée discord.py."""
import importlib

import pytest

import discord_config as dc


@pytest.mark.parametrize("extension", dc.EXTENSIONS)
def test_declared_extension_imports_with_declared_dependencies(extension):
    module = importlib.import_module(extension)

    assert callable(getattr(module, "setup", None)), f"{extension} n'expose pas setup(bot)"

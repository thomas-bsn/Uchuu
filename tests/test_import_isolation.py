"""Importer un module du bot ne lit jamais l'environnement (ni .env) : tout passe par
BotSettings.from_env, appelé une seule fois au démarrage."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_every_bot_module_imports_with_an_empty_environment(tmp_path):
    script = (
        "import importlib, main\n"
        "for name in ['internal_api', 'bot_settings', *main.EXTENSIONS]:\n"
        "    importlib.import_module(name)\n"
    )
    # Environnement vide (hors PATH) et cwd hors dépôt : aucun .env trouvable
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(ROOT)}
    result = subprocess.run([sys.executable, "-c", script], cwd=tmp_path, env=env, capture_output=True, text=True)

    assert result.returncode == 0, result.stderr[-2000:]

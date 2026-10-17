"""Hygiène du dépôt : pas de secret ni de bytecode suivis par git."""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OPENAI_KEY = re.compile(r"sk-[A-Za-z0-9_-]{20,}")


def tracked_files():
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True).stdout
    return [ROOT / name for name in out.decode().split("\0") if name]


def test_no_api_key_in_tracked_files():
    leaking = [
        str(path.relative_to(ROOT))
        for path in tracked_files()
        if path.is_file() and OPENAI_KEY.search(path.read_text(encoding="utf-8", errors="ignore"))
    ]
    assert leaking == []  # n'affiche que les chemins, jamais la clé


def test_no_compiled_python_tracked():
    compiled = [str(p.relative_to(ROOT)) for p in tracked_files() if p.suffix in {".pyc", ".pyo"}]
    assert compiled == []


SNOWFLAKE = re.compile(r"(?<![\w.])\d{17,20}(?![\w.])")


def test_no_discord_id_committed_in_python_code():
    with_ids = [
        str(p.relative_to(ROOT))
        for p in tracked_files()
        if p.suffix == ".py" and p.is_file() and SNOWFLAKE.search(p.read_text(encoding="utf-8"))
    ]
    assert with_ids == []


def test_legacy_config_modules_are_gone():
    assert not (ROOT / "discord_config.py").exists()
    assert not (ROOT / "runtime_config.py").exists()

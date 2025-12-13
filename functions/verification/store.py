import json
import os
import tempfile
from typing import Any, Dict, Set, Optional


# Fichier de persistance (à côté du bot quand tu le lances)
STATE_FILE = "verification_state.json"


class Store:
    def __init__(self):
        # Charge l'état du fichier à l'initialisation
        self.state = self._read_json_file(STATE_FILE)

    def _read_json_file(self, path: str) -> dict:
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _atomic_write_json(self, path: str, data: dict) -> None:
        dir_name = os.path.dirname(path) or "."
        fd, tmp_path = tempfile.mkstemp(prefix="verification_", suffix=".tmp", dir=dir_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, path)  # atomic on most OS
        finally:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass

    def save_state(self) -> None:
        # Sauvegarde l'état actuel dans le fichier
        self._atomic_write_json(STATE_FILE, self.state)

    def persist_pending(
        self,
        guild_id: int,
        user_id: int,
        *,
        yes: Set[int],
        no: Set[int],
        message_id: Optional[int],
        channel_id: Optional[int],
        expires_at_ts: Optional[int],
    ) -> None:
        """
        Upsert l'entrée pending pour un user.
        Retourne le state mis à jour (et déjà écrit sur disque).
        """
        g = self.state.setdefault(str(guild_id), {})
        g[str(user_id)] = {
            "yes": sorted(list(yes)),
            "no": sorted(list(no)),
            "message_id": message_id,
            "channel_id": channel_id,
            "expires_at_ts": expires_at_ts,
        }
        self.save_state()

    def remove_pending(self, guild_id: int, user_id: int) -> None:
        """
        Supprime l'entrée pending d'un user.
        Retourne le state mis à jour (et déjà écrit sur disque).
        """
        g = self.state.get(str(guild_id), {})
        if str(user_id) in g:
            del g[str(user_id)]
            self.save_state()

    def get_guild_pending(self, guild_id: int) -> Dict[str, Any]:
        """
        Retourne le dict { "<user_id>": pending_state, ... } pour un guild.
        """
        g = self.state.get(str(guild_id), {})
        return g if isinstance(g, dict) else {}

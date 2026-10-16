"""Faux objets Discord pour les tests (aucune connexion réelle)."""


class FakeMember:
    def __init__(self, id, bot=False):
        self.id = id
        self.bot = bot


class FakeVoiceChannel:
    def __init__(self, id, members=(), position=0):
        self.id = id
        self.members = list(members)
        self.position = position


class FakeGuild:
    def __init__(self, id, voice_channels=()):
        self.id = id
        self.voice_channels = list(voice_channels)


class FakeBot:
    def __init__(self, guilds=(), runtime_loop=None):
        self._guilds = {g.id: g for g in guilds}
        self.runtime_loop = runtime_loop
        self.loop = runtime_loop

    def get_guild(self, guild_id):
        return self._guilds.get(guild_id)

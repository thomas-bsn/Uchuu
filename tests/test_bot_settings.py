"""BotSettings.from_env : une config figée construite depuis un simple dict d'environnement."""
import pytest

from bot_settings import BotSettings, SettingsError

# Uniquement ce que le code restant utilise : token Discord, clé de l'API interne,
# salon par défaut des images d'historique de match.
REQUIRED = {
    "DISCORD_TOKEN": "tok",
    "INTERNAL_API_KEY": "internal-key",
    "CHANNEL_MATCH_HISTORY_ID": "22",
}


def test_minimal_environment_gives_a_complete_config_with_defaults():
    settings = BotSettings.from_env(REQUIRED)

    assert settings.discord.token == "tok"
    assert settings.discord.prefix == "$$"
    assert settings.discord.status == "Online"

    assert settings.ids.channel_match_history_id == 22

    assert settings.internal_api.host == "127.0.0.1"
    assert settings.internal_api.port == 9000
    assert settings.internal_api.key == "internal-key"

    assert settings.shameless.guild_id is None
    assert settings.shameless.db_path == "data/shameless.sqlite3"


def test_legacy_logs_channel_still_works_as_the_match_history_channel():
    env = {**REQUIRED, "CHANNEL_LOGS_ID": "21"}
    del env["CHANNEL_MATCH_HISTORY_ID"]

    assert BotSettings.from_env(env).ids.channel_match_history_id == 21


def test_former_vote_variables_are_no_longer_part_of_the_config():
    settings = BotSettings.from_env(REQUIRED)

    assert not hasattr(settings, "votes")
    for field in ("guild_id", "role_invite_id", "role_membre_id", "role_confiance_id", "channel_validation_id"):
        assert not hasattr(settings.ids, field)


def test_every_setting_can_be_overridden_from_the_environment():
    settings = BotSettings.from_env({
        **REQUIRED,
        "BOT_PREFIX": "!",
        "BOT_STATUS": "Busy",
        "CHANNEL_LOGS_ID": "21",
        "INTERNAL_API_HOST": "0.0.0.0",
        "INTERNAL_API_PORT": "9100",
        "SHAMELESS_GUILD_ID": "1000",
        "SHAMELESS_BOT_API_KEY": "bot-key",
        "SHAMELESS_HANDLER_TIMEOUT_SECONDS": "2.5",
        "SHAMELESS_DB_PATH": "/data/shameless.sqlite3",
    })

    assert (settings.discord.prefix, settings.discord.status) == ("!", "Busy")
    assert settings.ids.channel_match_history_id == 22  # prioritaire sur CHANNEL_LOGS_ID
    assert (settings.internal_api.host, settings.internal_api.port) == ("0.0.0.0", 9100)
    assert settings.shameless.guild_id == 1000
    assert settings.shameless.bot_api_key == "bot-key"
    assert settings.shameless.handler_timeout_seconds == 2.5
    assert settings.shameless.db_path == "/data/shameless.sqlite3"


def test_all_missing_required_variables_are_listed_in_a_single_error():
    with pytest.raises(SettingsError) as error:
        BotSettings.from_env({"DISCORD_TOKEN": "tok", "CHANNEL_MATCH_HISTORY_ID": "", "BOT_PREFIX": "!"})

    assert set(error.value.missing) == {"INTERNAL_API_KEY", "CHANNEL_MATCH_HISTORY_ID"}
    for name in error.value.missing:
        assert name in str(error.value)


def test_values_of_the_wrong_type_are_reported_with_the_missing_ones():
    env = {
        **REQUIRED,
        "CHANNEL_MATCH_HISTORY_ID": "not-a-number",
        "INTERNAL_API_PORT": "90x",
        "SHAMELESS_CLAIM_LEASE_SECONDS": "soon",
    }
    del env["DISCORD_TOKEN"]

    with pytest.raises(SettingsError) as error:
        BotSettings.from_env(env)

    assert error.value.missing == ["DISCORD_TOKEN"]
    assert set(error.value.invalid) == {"CHANNEL_MATCH_HISTORY_ID", "INTERNAL_API_PORT", "SHAMELESS_CLAIM_LEASE_SECONDS"}


def test_settings_are_immutable():
    settings = BotSettings.from_env(REQUIRED)

    with pytest.raises(AttributeError):
        settings.internal_api.port = 1


def test_shameless_api_config_is_read_from_the_environment():
    # #14 : le bot appelle l'API Shameless (routes /bot) avec une clé dédiée
    settings = BotSettings.from_env({
        **REQUIRED,
        "SHAMELESS_API_URL": "https://shameless.example/api",
        "SHAMELESS_BOT_TO_API_KEY": "to-api-key",
    })

    assert settings.shameless.api_url == "https://shameless.example/api"
    assert settings.shameless.bot_to_api_key == "to-api-key"


def test_shameless_api_config_is_optional():
    # comme les autres secrets Shameless : absence != démarrage refusé (une transmission
    # tentée sans config échoue à l'exécution, pas au boot)
    settings = BotSettings.from_env(REQUIRED)

    assert settings.shameless.api_url is None
    assert settings.shameless.bot_to_api_key is None


def test_retired_shared_voice_setting_left_in_the_environment_is_ignored():
    # #18 : les présences couvrent tous les vocaux du serveur, il n'y a plus de vocal commun
    settings = BotSettings.from_env({**REQUIRED, "SHAMELESS_SHARED_VOICE_ID": "not-a-number"})

    assert not hasattr(settings.shameless, "shared_voice_id")


def test_shameless_pronostics_config_is_read_from_the_environment():
    # #16 : salon des bulletins de pronostics + intervalle de réconciliation des résultats
    settings = BotSettings.from_env({
        **REQUIRED,
        "SHAMELESS_PRONOSTICS_CHANNEL_ID": "3001",
        "SHAMELESS_PRONOSTICS_RECONCILE_SECONDS": "15",
    })

    assert settings.shameless.pronostics_channel_id == 3001
    assert settings.shameless.pronostics_reconcile_seconds == 15.0


def test_shameless_pronostics_config_is_optional():
    # salon absent -> fonctionnalité éteinte (pas de refus au démarrage)
    settings = BotSettings.from_env(REQUIRED)

    assert settings.shameless.pronostics_channel_id is None
    assert settings.shameless.pronostics_reconcile_seconds == 60.0

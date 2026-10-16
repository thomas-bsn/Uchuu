"""BotSettings.from_env : une config figée construite depuis un simple dict d'environnement."""
import pytest

from bot_settings import BotSettings, SettingsError

REQUIRED = {
    "DISCORD_TOKEN": "tok",
    "INTERNAL_API_KEY": "internal-key",
    "GUILD_ID": "10",
    "ROLE_INVITE_ID": "11",
    "ROLE_MEMBRE_ID": "12",
    "ROLE_CONFIANCE_ID": "13",
    "CHANNEL_VALIDATION_ID": "20",
    "CHANNEL_LOGS_ID": "21",
}


def test_minimal_environment_gives_a_complete_config_with_spec_defaults():
    settings = BotSettings.from_env(REQUIRED)

    assert settings.discord.token == "tok"
    assert settings.discord.prefix == "$$"
    assert settings.discord.status == "Online"

    assert settings.ids.guild_id == 10
    assert settings.ids.role_invite_id == 11
    assert settings.ids.role_membre_id == 12
    assert settings.ids.role_confiance_id == 13
    assert settings.ids.channel_validation_id == 20
    assert settings.ids.channel_logs_id == 21
    assert settings.ids.channel_match_history_id == 21  # défaut : salon de logs

    assert settings.internal_api.host == "127.0.0.1"
    assert settings.internal_api.port == 9000
    assert settings.internal_api.key == "internal-key"

    assert settings.votes.invite_window_seconds == 24 * 3600
    assert settings.votes.confiance_window_seconds == 24 * 3600
    assert settings.votes.approvals_required == 1
    assert settings.votes.confiance_eligibility_days == 30
    assert settings.votes.confiance_cooldown_days == 30
    assert settings.votes.confiance_scan_interval_hours == 24
    assert settings.votes.db_path == "/data/votes.sqlite3"

    assert settings.shameless.guild_id is None
    assert settings.shameless.db_path == "data/shameless.sqlite3"


def test_every_setting_can_be_overridden_from_the_environment():
    settings = BotSettings.from_env({
        **REQUIRED,
        "BOT_PREFIX": "!",
        "BOT_STATUS": "Busy",
        "CHANNEL_MATCH_HISTORY_ID": "22",
        "INTERNAL_API_HOST": "0.0.0.0",
        "INTERNAL_API_PORT": "9100",
        "INVITE_VOTE_WINDOW_SECONDS": "60",
        "CONFIANCE_VOTE_WINDOW_SECONDS": "120",
        "VOTE_APPROVALS_REQUIRED": "3",
        "CONFIANCE_ELIGIBILITY_DAYS": "0",
        "CONFIANCE_COOLDOWN_DAYS": "7",
        "CONFIANCE_SCAN_INTERVAL_HOURS": "6",
        "VOTES_DB_PATH": "/tmp/v.sqlite3",
        "SHAMELESS_GUILD_ID": "1000",
        "SHAMELESS_BOT_API_KEY": "bot-key",
        "SHAMELESS_HANDLER_TIMEOUT_SECONDS": "2.5",
        "SHAMELESS_DB_PATH": "/data/shameless.sqlite3",
    })

    assert (settings.discord.prefix, settings.discord.status) == ("!", "Busy")
    assert settings.ids.channel_match_history_id == 22
    assert (settings.internal_api.host, settings.internal_api.port) == ("0.0.0.0", 9100)
    assert settings.votes.invite_window_seconds == 60
    assert settings.votes.confiance_window_seconds == 120
    assert settings.votes.approvals_required == 3
    assert settings.votes.confiance_eligibility_days == 0
    assert settings.votes.confiance_cooldown_days == 7
    assert settings.votes.confiance_scan_interval_hours == 6
    assert settings.votes.db_path == "/tmp/v.sqlite3"
    assert settings.shameless.guild_id == 1000
    assert settings.shameless.bot_api_key == "bot-key"
    assert settings.shameless.handler_timeout_seconds == 2.5
    assert settings.shameless.db_path == "/data/shameless.sqlite3"


def test_all_missing_required_variables_are_listed_in_a_single_error():
    with pytest.raises(SettingsError) as error:
        BotSettings.from_env({"DISCORD_TOKEN": "tok", "GUILD_ID": "", "BOT_PREFIX": "!"})

    assert set(error.value.missing) == {
        "INTERNAL_API_KEY",
        "GUILD_ID",
        "ROLE_INVITE_ID",
        "ROLE_MEMBRE_ID",
        "ROLE_CONFIANCE_ID",
        "CHANNEL_VALIDATION_ID",
        "CHANNEL_LOGS_ID",
    }
    for name in error.value.missing:
        assert name in str(error.value)


def test_values_of_the_wrong_type_are_reported_with_the_missing_ones():
    env = {**REQUIRED, "GUILD_ID": "not-a-number", "INTERNAL_API_PORT": "90x", "SHAMELESS_CLAIM_LEASE_SECONDS": "soon"}
    del env["DISCORD_TOKEN"]

    with pytest.raises(SettingsError) as error:
        BotSettings.from_env(env)

    assert error.value.missing == ["DISCORD_TOKEN"]
    assert set(error.value.invalid) == {"GUILD_ID", "INTERNAL_API_PORT", "SHAMELESS_CLAIM_LEASE_SECONDS"}


def test_settings_are_immutable():
    settings = BotSettings.from_env(REQUIRED)

    with pytest.raises(AttributeError):
        settings.votes.approvals_required = 5

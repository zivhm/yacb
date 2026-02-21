from core.channels.commands import (
    get_commands_text,
    is_commands_request,
    is_reset_request,
    is_toggle_verbose_request,
)


def test_is_commands_request_aliases() -> None:
    assert is_commands_request("/commands")
    assert is_commands_request(" /help ")
    assert is_commands_request("!commands")
    assert is_commands_request("!help")
    assert not is_commands_request("commands")
    assert not is_commands_request("/unknown")


def test_is_reset_request_aliases() -> None:
    assert is_reset_request("/reset")
    assert is_reset_request(" !reset ")
    assert not is_reset_request("/commands")


def test_is_toggle_verbose_request_aliases() -> None:
    assert is_toggle_verbose_request("/toggle_verbose_logs")
    assert is_toggle_verbose_request("!toggle-verbose-logs")
    assert not is_toggle_verbose_request("/debug")


def test_get_commands_text_contains_channel_specific_entries() -> None:
    telegram = get_commands_text("telegram")
    assert "/debug" in telegram
    assert "/toggle_verbose_logs" in telegram
    assert "/reset" in telegram
    assert "!<shell command>" in telegram
    assert "!restart now" in telegram
    assert "!update now" in telegram

    discord = get_commands_text("discord")
    assert "/toggle_verbose_logs" in discord
    assert "/reset" in discord
    assert "!restart now" in discord
    assert "!update now" in discord

    whatsapp = get_commands_text("whatsapp")
    assert "WhatsApp notes:" in whatsapp
    assert "/commands, /help, /reset, /toggle_verbose_logs" in whatsapp
    assert "!restart now" in whatsapp
    assert "!update now" in whatsapp

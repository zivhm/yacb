from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from core.main import _parse_setup_args, _service_paths
from core.setup import (
    CORE_DEFAULT_SKILLS,
    _build_probe_models,
    _can_prepare_workspace,
    _can_write_config_path,
    _choose_router_candidate,
    _ensure_first_run_bootstrap,
    _extract_model_ids,
    _extract_model_tools_support,
    _merge_with_core_skills,
    _opencode_endpoint_family,
    _parse_allow_from,
    _parse_multi_select,
    _probe_model_chat_support,
    _probe_model_tools_support,
    _render_first_run_bootstrap,
    _resolve_model_tools_support,
    _resolve_setup_config_output,
    _resolve_setup_workspace,
    _slugify_workspace_name,
    _sync_runtime_settings_from_setup,
    _test_api_key,
    _validate_hhmm,
)


def test_parse_multi_select_accepts_single_and_multiple() -> None:
    assert _parse_multi_select("1", 3) == [0]
    assert _parse_multi_select("1,3", 3) == [0, 2]
    assert _parse_multi_select("all", 3) == [0, 1, 2]


def test_parse_multi_select_ignores_invalid_tokens() -> None:
    assert _parse_multi_select("0,4,x,2", 3) == [1]


def test_validate_hhmm_checks_24_hour_format() -> None:
    assert _validate_hhmm("00:00") is True
    assert _validate_hhmm("23:59") is True
    assert _validate_hhmm("24:00") is False
    assert _validate_hhmm("9:00") is False


def test_parse_allow_from_telegram_discord_requires_numeric_ids() -> None:
    valid_tg, invalid_tg = _parse_allow_from("telegram", "12345,-42,abc")
    assert valid_tg == ["12345", "-42"]
    assert invalid_tg == ["abc"]

    valid_dc, invalid_dc = _parse_allow_from("discord", "123456789012345678,foo")
    assert valid_dc == ["123456789012345678"]
    assert invalid_dc == ["foo"]


def test_parse_allow_from_whatsapp_normalizes_and_validates_numbers() -> None:
    valid, invalid = _parse_allow_from("whatsapp", "+1 (555) 123-4567,abc,+12")
    assert valid == ["+15551234567"]
    assert invalid == ["abc", "+12"]


def test_parse_setup_args_supports_tui_flags() -> None:
    default_cfg = "config.local.yaml"

    path, tui = _parse_setup_args([], default_cfg)
    assert path == default_cfg
    assert tui is False

    path, tui = _parse_setup_args(["--tui"], default_cfg)
    assert path == default_cfg
    assert tui is True

    path, tui = _parse_setup_args(["custom.yaml", "--app"], default_cfg)
    assert path == "custom.yaml"
    assert tui is True


def test_service_paths_use_project_dir_when_writable(tmp_path) -> None:
    pid, log = _service_paths(tmp_path)
    assert pid.parent == (tmp_path / ".yacb").resolve()
    assert log.parent == (tmp_path / ".yacb").resolve()


def test_service_paths_fall_back_to_home_when_project_dir_not_writable(tmp_path, monkeypatch) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir(parents=True, exist_ok=True)
    fake_home = tmp_path / "fake-home"
    fake_home.mkdir(parents=True, exist_ok=True)

    primary = (project_root / ".yacb").resolve()
    fallback = (fake_home / ".yacb" / "service").resolve()

    monkeypatch.setattr("core.main.Path.home", lambda: fake_home)

    def fake_can_prepare(path):
        resolved = Path(path).expanduser().resolve()
        if resolved == primary:
            return False
        if resolved == fallback:
            return True
        return False

    monkeypatch.setattr("core.main._can_prepare_runtime_dir", fake_can_prepare)

    pid, log = _service_paths(project_root)
    assert pid.parent == fallback
    assert log.parent == fallback


def test_merge_with_core_skills_enforces_defaults_when_available() -> None:
    available = ["foo", "alive-pulse", "coding-agent", "session-logs"]
    merged = _merge_with_core_skills(["foo"], available)
    assert merged[0] == "foo"
    assert "alive-pulse" in merged
    assert "coding-agent" in merged
    assert "session-logs" in merged


def test_merge_with_core_skills_skips_missing_defaults() -> None:
    available = ["foo", "bar"]
    merged = _merge_with_core_skills([], available)
    assert merged == []
    assert all(name not in merged for name in CORE_DEFAULT_SKILLS)


def test_test_api_key_retries_when_first_probe_model_is_missing(monkeypatch) -> None:
    calls: list[str] = []

    def fake_completion(**kwargs):
        calls.append(kwargs["model"])
        if len(calls) == 1:
            raise Exception("404 model not found")
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]
        )

    fake_litellm = SimpleNamespace(completion=fake_completion)
    monkeypatch.setitem(sys.modules, "litellm", fake_litellm)

    ok, msg = _test_api_key(
        provider_name="openrouter",
        api_key="sk-or-test",
        model="openrouter/anthropic/claude-sonnet-4-5-20250929",
        api_base="https://openrouter.ai/api/v1",
        probe_models=["openrouter/openai/gpt-4o"],
    )

    assert ok is True
    assert msg == "ok"
    assert calls == [
        "openrouter/anthropic/claude-sonnet-4-5-20250929",
        "openrouter/openai/gpt-4o",
    ]


def test_test_api_key_accepts_valid_key_when_only_models_are_missing(monkeypatch) -> None:
    def fake_completion(**kwargs):
        raise Exception("404 model not found")

    fake_litellm = SimpleNamespace(completion=fake_completion)
    monkeypatch.setitem(sys.modules, "litellm", fake_litellm)

    ok, msg = _test_api_key(
        provider_name="opencode",
        api_key="oc-test",
        model="opencode/qwen3-coder",
        api_base="https://opencode.ai/zen/v1",
        probe_models=["opencode/minimax-m2.5"],
    )

    assert ok is True
    assert "appears valid" in msg.lower()


def test_test_api_key_translates_opencode_model_to_openai_format(monkeypatch) -> None:
    seen: dict[str, str] = {}

    def fake_completion(**kwargs):
        seen["model"] = kwargs["model"]
        seen["api_base"] = kwargs.get("api_base", "")
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]
        )

    fake_litellm = SimpleNamespace(completion=fake_completion)
    monkeypatch.setitem(sys.modules, "litellm", fake_litellm)

    ok, msg = _test_api_key(
        provider_name="opencode",
        api_key="oc-test",
        model="opencode/qwen3-coder",
        api_base="https://opencode.ai/zen/v1",
    )

    assert ok is True
    assert msg == "ok"
    assert seen["model"] == "openai/qwen3-coder"
    assert seen["api_base"] == "https://opencode.ai/zen/v1"


def test_extract_model_tools_support_from_supported_parameters() -> None:
    payload = {
        "data": [
            {"id": "arcee-ai/trinity-large-preview:free", "supported_parameters": ["tools", "temperature"]},
            {"id": "legacy/model", "supported_parameters": ["temperature"]},
        ]
    }
    support = _extract_model_tools_support(payload)
    assert support["arcee-ai/trinity-large-preview:free"] is True
    assert "legacy/model" not in support


def test_resolve_model_tools_support_handles_openrouter_prefix() -> None:
    support_map = {"arcee-ai/trinity-large-preview:free": True}
    resolved = _resolve_model_tools_support(
        provider_name="openrouter",
        model_id="openrouter/arcee-ai/trinity-large-preview:free",
        tools_support_map=support_map,
    )
    assert resolved is True


def test_extract_model_ids_handles_common_payload_shapes() -> None:
    payload = {
        "data": [
            {"id": "qwen3-coder"},
            {"name": "qwen3-30b-a3b-instruct"},
            {"model": "minimax-m2.5"},
        ]
    }
    assert _extract_model_ids(payload) == [
        "qwen3-coder",
        "qwen3-30b-a3b-instruct",
        "minimax-m2.5",
    ]


def test_build_probe_models_prefers_hinted_provider_models() -> None:
    probes = _build_probe_models(
        provider_name="opencode",
        recommended_models=["opencode/qwen3-coder"],
        api_models=[
            "qwen3-coder",
            "qwen3-30b-a3b-instruct",
            "minimax-m2.5",
            "glm-4.6",
        ],
    )
    assert probes[0] == "opencode/qwen3-coder"
    assert any("minimax" in model for model in probes)


def test_build_probe_models_prioritizes_free_models_for_opencode() -> None:
    probes = _build_probe_models(
        provider_name="opencode",
        recommended_models=["opencode/qwen3-coder"],
        api_models=[
            "qwen3-coder",
            "minimax-m2.5-free",
            "qwen3-30b-a3b-instruct",
        ],
    )
    assert probes[0] == "minimax-m2.5-free"


def test_test_api_key_continues_after_quota_probe_error(monkeypatch) -> None:
    calls: list[str] = []

    def fake_completion(**kwargs):
        calls.append(kwargs["model"])
        if len(calls) == 1:
            raise Exception("No payment method. Add a payment method here: https://example.com")
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]
        )

    fake_litellm = SimpleNamespace(completion=fake_completion)
    monkeypatch.setitem(sys.modules, "litellm", fake_litellm)

    ok, msg = _test_api_key(
        provider_name="opencode",
        api_key="oc-test",
        model="opencode/qwen3-coder",
        api_base="https://opencode.ai/zen/v1",
        probe_models=["opencode/minimax-m2.5-free"],
    )

    assert ok is True
    assert msg == "ok"
    assert calls == ["openai/qwen3-coder", "openai/minimax-m2.5-free"]


def test_opencode_endpoint_family_maps_known_families() -> None:
    assert _opencode_endpoint_family("opencode/gpt-5-mini") == "responses"
    assert _opencode_endpoint_family("opencode/claude-sonnet-4.5") == "messages"
    assert _opencode_endpoint_family("opencode/minimax-m2.5-free") == "chat_completions"


def test_probe_model_tools_support_translates_opencode_model(monkeypatch) -> None:
    seen: dict[str, object] = {}

    def fake_completion(**kwargs):
        seen["model"] = kwargs["model"]
        seen["tools"] = kwargs.get("tools")
        seen["tool_choice"] = kwargs.get("tool_choice")
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]
        )

    fake_litellm = SimpleNamespace(completion=fake_completion)
    monkeypatch.setitem(sys.modules, "litellm", fake_litellm)

    ok, reason = _probe_model_tools_support(
        provider_name="opencode",
        api_key="oc-test",
        model_id="opencode/minimax-m2.5-free",
        api_base="https://opencode.ai/zen/v1",
    )

    assert ok is True
    assert reason == ""
    assert seen["model"] == "openai/minimax-m2.5-free"
    assert isinstance(seen["tools"], list)
    assert seen["tool_choice"] == "auto"


def test_probe_model_tools_support_flags_opencode_messages_family() -> None:
    ok, reason = _probe_model_tools_support(
        provider_name="opencode",
        api_key="oc-test",
        model_id="opencode/claude-sonnet-4.5",
        api_base="https://opencode.ai/zen/v1",
    )
    assert ok is False
    assert "/messages" in reason


def test_probe_model_tools_support_detects_explicit_unsupported_error(monkeypatch) -> None:
    def fake_completion(**kwargs):
        raise Exception("Unsupported parameter: tools")

    fake_litellm = SimpleNamespace(completion=fake_completion)
    monkeypatch.setitem(sys.modules, "litellm", fake_litellm)

    ok, reason = _probe_model_tools_support(
        provider_name="openrouter",
        api_key="sk-or-test",
        model_id="openrouter/arcee-ai/trinity-large-preview:free",
        api_base="https://openrouter.ai/api/v1",
    )
    assert ok is False
    assert "Unsupported parameter: tools" in reason


def test_probe_model_chat_support_translates_opencode_model(monkeypatch) -> None:
    seen: dict[str, str] = {}

    def fake_completion(**kwargs):
        seen["model"] = kwargs["model"]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]
        )

    fake_litellm = SimpleNamespace(completion=fake_completion)
    monkeypatch.setitem(sys.modules, "litellm", fake_litellm)

    ok, reason = _probe_model_chat_support(
        provider_name="opencode",
        api_key="oc-test",
        model_id="opencode/kimi-k2.5-free",
        api_base="https://opencode.ai/zen/v1",
    )

    assert ok is True
    assert reason == ""
    assert seen["model"] == "openai/kimi-k2.5-free"


def test_choose_router_candidate_prefers_hinted_provider_models() -> None:
    model = _choose_router_candidate(
        provider_name="opencode",
        model_id="opencode/kimi-k2.5-free",
        api_models=["qwen3-coder", "minimax-m2.5-free", "glm-4.7-free"],
        fallback="opencode/qwen3-coder",
        hints=("minimax", "glm"),
    )
    assert model == "opencode/minimax-m2.5-free"


def test_sync_runtime_settings_from_setup_overwrites_model_and_router(tmp_path) -> None:
    workspace = tmp_path / "agent-workspace" / "yacb"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "settings.json").write_text(
        '{"model":"anthropic/claude-sonnet-4-20250514","llm_router":{"enabled":true,'
        '"classifier_model":"anthropic/claude-haiku-4-20250514","light_model":"anthropic/claude-haiku-4-20250514",'
        '"heavy_model":"anthropic/claude-sonnet-4-20250514"},"verbose_logs":{"enabled":true}}',
        encoding="utf-8",
    )

    settings_path = _sync_runtime_settings_from_setup(
        workspace=workspace,
        provider_name="opencode",
        medium_model="opencode/qwen3-coder",
        router_cfg={"enabled": False},
    )
    assert settings_path == workspace / "settings.json"
    saved = settings_path.read_text(encoding="utf-8")
    assert '"model": "opencode/qwen3-coder"' in saved
    assert '"enabled": false' in saved
    assert '"verbose_logs"' in saved


def test_sync_runtime_settings_from_setup_normalizes_router_models(tmp_path) -> None:
    workspace = tmp_path / "agent-workspace" / "yacb"
    workspace.mkdir(parents=True, exist_ok=True)

    settings_path = _sync_runtime_settings_from_setup(
        workspace=workspace,
        provider_name="opencode",
        medium_model="qwen3-coder",
        router_cfg={
            "enabled": True,
            "classifier_model": "anthropic/claude-haiku-4-20250514",
            "light_model": "minimax-m2.5-free",
            "heavy_model": "anthropic/claude-sonnet-4-20250514",
        },
    )
    saved = settings_path.read_text(encoding="utf-8")
    assert '"model": "opencode/qwen3-coder"' in saved
    assert '"classifier_model": "opencode/minimax-m2.5-free"' in saved
    assert '"light_model": "opencode/minimax-m2.5-free"' in saved
    assert '"heavy_model": "opencode/qwen3-coder"' in saved


def test_render_first_run_bootstrap_contains_focused_questions() -> None:
    content = _render_first_run_bootstrap()
    lowered = content.lower()
    assert "first-run identity onboarding" in lowered
    assert "respond in a neutral" in lowered
    assert "identity.md" in lowered
    assert "user.md" in lowered
    assert "what should i call you?" in lowered


def test_ensure_first_run_bootstrap_creates_once(tmp_path) -> None:
    workspace = tmp_path / "agent-workspace" / "yacb"
    path, created = _ensure_first_run_bootstrap(workspace)
    assert created is True
    assert path.exists()
    first = path.read_text(encoding="utf-8")
    assert "first-run identity onboarding" in first.lower()

    path_again, created_again = _ensure_first_run_bootstrap(workspace)
    assert path_again == path
    assert created_again is False


def test_slugify_workspace_name_normalizes_display_name() -> None:
    assert _slugify_workspace_name("Jake") == "jake"
    assert _slugify_workspace_name("Jake The Bot") == "jake-the-bot"
    assert _slugify_workspace_name("  !!!  ") == "yacb"


def test_can_prepare_workspace_returns_true_for_writable_path(tmp_path) -> None:
    target = tmp_path / "agent-workspace" / "jake"
    assert _can_prepare_workspace(target) is True


def test_resolve_setup_workspace_uses_primary_when_writable(tmp_path) -> None:
    workspace, note = _resolve_setup_workspace(tmp_path, "jake")
    assert workspace.endswith("agent-workspace/jake")
    assert note is None


def test_resolve_setup_workspace_uses_fallback_when_primary_not_writable(tmp_path, monkeypatch) -> None:
    config_dir = tmp_path / "config-dir"
    config_dir.mkdir(parents=True, exist_ok=True)
    fake_home = tmp_path / "fake-home"
    fake_home.mkdir(parents=True, exist_ok=True)

    primary = (config_dir / "agent-workspace" / "ink").resolve()
    fallback = (fake_home / ".yacb" / "agent-workspace" / "ink").resolve()

    monkeypatch.setattr("core.setup.Path.home", lambda: fake_home)

    def fake_can_prepare(path):
        resolved = Path(path).expanduser().resolve()
        if resolved == primary:
            return False
        if resolved == fallback:
            return True
        return False

    monkeypatch.setattr("core.setup._can_prepare_workspace", fake_can_prepare)

    workspace, note = _resolve_setup_workspace(config_dir, "ink")
    assert workspace == str(fallback)
    assert note is not None
    assert "not writable" in note.lower()


def test_can_write_config_path_returns_true_for_writable_target(tmp_path) -> None:
    target = tmp_path / "config.local.yaml"
    assert _can_write_config_path(target) is True


def test_resolve_setup_config_output_uses_primary_when_writable(tmp_path) -> None:
    primary = tmp_path / "config.local.yaml"
    resolved, note = _resolve_setup_config_output(str(primary))
    assert resolved == primary.resolve()
    assert note is None


def test_resolve_setup_config_output_uses_fallback_when_primary_not_writable(tmp_path, monkeypatch) -> None:
    fake_home = tmp_path / "fake-home"
    fake_home.mkdir(parents=True, exist_ok=True)

    primary = (tmp_path / "locked" / "config.local.yaml").resolve()
    fallback = (fake_home / ".yacb" / "config.local.yaml").resolve()

    monkeypatch.setattr("core.setup.Path.home", lambda: fake_home)

    def fake_can_write(path):
        resolved = Path(path).expanduser().resolve()
        if resolved == primary:
            return False
        if resolved == fallback:
            return True
        return False

    monkeypatch.setattr("core.setup._can_write_config_path", fake_can_write)

    resolved, note = _resolve_setup_config_output(str(primary))
    assert resolved == fallback
    assert note is not None
    assert "not writable" in note.lower()

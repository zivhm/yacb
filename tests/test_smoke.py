from pathlib import Path

import yaml


def test_package_imports() -> None:
    import core  # noqa: F401


def test_default_config_has_agent() -> None:
    from core.config import Config

    cfg = Config()
    assert "default" in cfg.agents


def test_readme_exists() -> None:
    assert Path("README.md").exists()


def test_load_config_missing_file_returns_defaults(tmp_path: Path) -> None:
    from core.config import load_config

    cfg = load_config(tmp_path / "missing.yaml")
    assert "default" in cfg.agents
    assert cfg.channels.telegram.enabled is False
    assert cfg.tools.exec.timeout == 60
    assert cfg.tools.security_audit.enabled is False
    assert cfg.tools.security_audit.interval_minutes == 360


def test_load_config_migrates_root_heartbeat(tmp_path: Path) -> None:
    from core.config import load_config

    config_path = tmp_path / "config.yaml"
    data = {
        "agents": {"default": {"heartbeat": {"enabled": False}}},
        "heartbeat": {
            "enabled": True,
            "interval_minutes": 5,
            "deliver_to": "telegram:123",
            "active_hours_start": "09:00",
            "active_hours_end": "10:00",
            "suppress_empty": False,
        },
    }
    config_path.write_text(yaml.safe_dump(data))

    cfg = load_config(config_path)
    assert cfg.agents["default"].heartbeat.enabled is True
    assert cfg.agents["default"].heartbeat.interval_minutes == 5


def test_load_config_reads_security_audit_settings(tmp_path: Path) -> None:
    from core.config import load_config

    config_path = tmp_path / "config.yaml"
    data = {
        "tools": {
            "security_audit": {
                "enabled": True,
                "interval_minutes": 30,
            }
        }
    }
    config_path.write_text(yaml.safe_dump(data))

    cfg = load_config(config_path)
    assert cfg.tools.security_audit.enabled is True
    assert cfg.tools.security_audit.interval_minutes == 30


def test_workspace_path_resolves_relative_to_config_file_dir(tmp_path: Path) -> None:
    from core.config import load_config

    config_dir = tmp_path / "configs"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "yacb.yaml"
    data = {"agents": {"default": {"workspace": "agent-workspace/ink"}}}
    config_path.write_text(yaml.safe_dump(data), encoding="utf-8")

    cfg = load_config(config_path)
    assert cfg.workspace_path() == (config_dir / "agent-workspace" / "ink").resolve()


def test_workspace_path_for_missing_config_uses_missing_file_parent(tmp_path: Path) -> None:
    from core.config import load_config

    missing_config = tmp_path / "alt" / "missing.yaml"
    cfg = load_config(missing_config)
    assert cfg.workspace_path() == (tmp_path / "alt" / "agent-workspace" / "yacb").resolve()

from __future__ import annotations

from core.agent.context import ContextBuilder


def test_bootstrap_context_includes_bootstrap_file_when_present(tmp_path) -> None:
    workspace = tmp_path / "agent-workspace" / "yacb"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "BOOTSTRAP.md").write_text("run once", encoding="utf-8")

    ctx = ContextBuilder(workspace=workspace)
    content = ctx._get_bootstrap_context()

    assert "### BOOTSTRAP.md" in content
    assert "run once" in content
    assert "### IDENTITY.md" in content


def test_build_messages_caps_history_window(tmp_path) -> None:
    workspace = tmp_path / "agent-workspace" / "yacb"
    workspace.mkdir(parents=True, exist_ok=True)
    ctx = ContextBuilder(workspace=workspace)

    history = [{"role": "user", "content": f"m{i}"} for i in range(60)]
    messages = ctx.build_messages(history=history, current_message="now")

    # 1 system + last 40 history + 1 current user
    assert len(messages) == 42
    assert messages[1]["content"] == "m20"
    assert messages[-2]["content"] == "m59"
    assert messages[-1]["content"] == "now"

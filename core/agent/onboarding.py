"""Deterministic first-run onboarding for workspace identity customization."""

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from core.onboarding_spec import ONBOARDING_QUESTIONS
from core.prompts.loader import read_bootstrap

_LEGACY_STATE_FILE = ".onboarding_state.json"
_STATE_DIR = ".onboarding"


class FirstRunOnboarding:
    """Stateful onboarding flow gated by BOOTSTRAP.md presence."""

    def __init__(self, workspace: Path):
        self.workspace = workspace.expanduser().resolve()
        self.bootstrap_path = self.workspace / "BOOTSTRAP.md"
        self.legacy_state_path = self.workspace / _LEGACY_STATE_FILE
        self.state_dir = self.workspace / _STATE_DIR

    def handle_message(
        self,
        channel: str,
        chat_id: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> str | None:
        """Return deterministic onboarding reply, or None when normal routing should continue."""
        metadata = metadata or {}
        if not self.bootstrap_path.exists():
            return None
        if channel == "system":
            return None
        if metadata.get("is_group") is True:
            return None
        if "is_dm" in metadata and metadata.get("is_dm") is False:
            return None

        state = self._load_state(channel, chat_id)
        text = content.strip()
        lower = text.lower()

        if self._is_skip_request(lower):
            self._disable_onboarding()
            return (
                "Onboarding skipped. I removed BOOTSTRAP.md.\n"
                "You can still customize me anytime by editing IDENTITY.md and USER.md."
            )

        if self._is_status_request(lower):
            return self._status_text(state)

        if state["status"] == "paused":
            if self._is_resume_request(lower):
                state["status"] = "in_progress"
                idx = self._normalize_question_index(state.get("question_index", 0))
                self._save_state(channel, chat_id, state)
                return f"Resuming onboarding.\n\n{self._question_text(idx)}"
            if self._is_pause_request(lower):
                return "Onboarding is already paused. Say 'resume onboarding' when you're ready."
            return None

        if state["status"] == "pending":
            if self._is_pause_request(lower):
                state["status"] = "paused"
                self._save_state(channel, chat_id, state)
                return "No problem. I paused onboarding. Say 'resume onboarding' whenever you want to continue."
            state["status"] = "in_progress"
            state["question_index"] = 0
            self._save_state(channel, chat_id, state)
            return (
                "Hey - I'm online and ready to help.\n\n"
                "Before we customize my behavior, quick onboarding:\n"
                f"{self._question_text(0)}"
            )

        if state["status"] != "in_progress":
            return None

        if self._is_pause_request(lower):
            state["status"] = "paused"
            self._save_state(channel, chat_id, state)
            return "No problem. I paused onboarding. Say 'resume onboarding' whenever you want to continue."
        if self._is_resume_request(lower):
            idx = self._normalize_question_index(state.get("question_index", 0))
            return f"Onboarding is already active.\n\n{self._question_text(idx)}"

        idx = self._normalize_question_index(state.get("question_index", 0))
        answers = dict(state.get("answers", {}))
        key, _question = ONBOARDING_QUESTIONS[idx]
        answers[key] = self._normalize_answer(key, text)

        next_idx = idx + 1
        if next_idx < len(ONBOARDING_QUESTIONS):
            state["answers"] = answers
            state["question_index"] = next_idx
            self._save_state(channel, chat_id, state)
            return f"Noted.\n\n{self._question_text(next_idx)}"

        state["answers"] = answers
        state["status"] = "complete"
        self._save_state(channel, chat_id, state)
        return self._finalize(answers)

    def _load_state(self, channel: str, chat_id: str) -> dict[str, Any]:
        state_path = self._state_path(channel, chat_id)
        if state_path.exists():
            try:
                data = json.loads(state_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return {
                        "status": str(data.get("status", "pending")),
                        "question_index": int(data.get("question_index", 0)),
                        "answers": dict(data.get("answers", {})),
                    }
            except Exception:
                pass

        # Best-effort migration from legacy single-state storage.
        if self.legacy_state_path.exists():
            try:
                data = json.loads(self.legacy_state_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    migrated = {
                        "status": str(data.get("status", "pending")),
                        "question_index": int(data.get("question_index", 0)),
                        "answers": dict(data.get("answers", {})),
                    }
                    self._save_state(channel, chat_id, migrated)
                    self.legacy_state_path.unlink(missing_ok=True)
                    return migrated
            except Exception:
                pass

        return {"status": "pending", "question_index": 0, "answers": {}}

    def _save_state(self, channel: str, chat_id: str, state: dict[str, Any]) -> None:
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        state_path = self._state_path(channel, chat_id)
        state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")

    def _state_path(self, channel: str, chat_id: str) -> Path:
        raw = f"{channel}:{chat_id}"
        safe = re.sub(r"[^a-z0-9_-]+", "-", raw.lower())
        safe = re.sub(r"-{2,}", "-", safe).strip("-")[:36] or "session"
        digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
        return self.state_dir / f"{safe}-{digest}.json"

    @staticmethod
    def _normalize_question_index(idx: int) -> int:
        if not isinstance(idx, int):
            idx = 0
        return max(0, min(idx, len(ONBOARDING_QUESTIONS) - 1))

    @staticmethod
    def _question_text(idx: int) -> str:
        _key, question = ONBOARDING_QUESTIONS[idx]
        return f"Q{idx + 1}/{len(ONBOARDING_QUESTIONS)}: {question}"

    @staticmethod
    def _is_pause_request(lower: str) -> bool:
        return lower in {
            "later",
            "do later",
            "finish later",
            "pause",
            "pause onboarding",
            "skip for now",
        }

    @staticmethod
    def _is_resume_request(lower: str) -> bool:
        return lower in {"resume", "resume onboarding", "continue onboarding", "continue"}

    @staticmethod
    def _is_skip_request(lower: str) -> bool:
        return lower in {"skip onboarding", "skip", "cancel onboarding"}

    @staticmethod
    def _is_status_request(lower: str) -> bool:
        return lower in {"status onboarding", "onboarding status"}

    def _status_text(self, state: dict[str, Any]) -> str:
        status = str(state.get("status", "pending"))
        idx = self._normalize_question_index(state.get("question_index", 0))
        next_question = self._question_text(idx)
        return (
            f"Onboarding status: {status}\n"
            f"Next: {next_question}\n"
            "Commands: pause onboarding | resume onboarding | skip onboarding | status onboarding"
        )

    def _normalize_answer(self, key: str, raw: str) -> str:
        text = raw.strip()
        lower = text.lower()
        if key == "assistant_name":
            return text or "yacb"
        if key == "user_name":
            return text or "User"
        if key == "response_style":
            if any(word in lower for word in ("very brief", "brief", "short", "concise", "minimal")):
                return "very brief"
            if any(word in lower for word in ("detailed", "detail", "thorough", "long")):
                return "detailed"
            return "balanced"
        if key == "directness":
            if "very direct" in lower or any(word in lower for word in ("blunt", "brutal")):
                return "very direct"
            if any(word in lower for word in ("soft", "gentle", "diplomatic", "polite")):
                return "soft"
            return "direct"
        if key == "decision_style":
            if any(word in lower for word in ("options", "tradeoff", "trade-offs", "alternatives")):
                return "options with tradeoffs"
            return "one recommendation first"
        if key == "proactivity":
            if any(word in lower for word in ("quiet", "low", "minimal")):
                return "quiet"
            if any(word in lower for word in ("high", "proactive", "high-touch")):
                return "high-touch"
            return "moderate"
        return text or "none"

    def _finalize(self, answers: dict[str, str]) -> str:
        self._ensure_workspace_files()
        self._update_identity(answers)
        self._update_user(answers)
        assistant_name = answers.get("assistant_name", "yacb")
        try:
            from core.config import save_agent_settings

            save_agent_settings(self.workspace, "bot_name", assistant_name)
        except Exception:
            pass

        self._disable_onboarding()

        return (
            f"Onboarding complete. I updated IDENTITY.md and USER.md for {assistant_name}.\n"
            "If you want adjustments, tell me and I'll refine them."
        )

    def _disable_onboarding(self) -> None:
        try:
            self.bootstrap_path.unlink(missing_ok=True)
        except Exception:
            pass
        self._clear_state_files()

    def _clear_state_files(self) -> None:
        try:
            self.legacy_state_path.unlink(missing_ok=True)
        except Exception:
            pass
        if self.state_dir.exists():
            for path in self.state_dir.glob("*.json"):
                try:
                    path.unlink(missing_ok=True)
                except Exception:
                    pass
            try:
                self.state_dir.rmdir()
            except Exception:
                pass

    def _ensure_workspace_files(self) -> None:
        self.workspace.mkdir(parents=True, exist_ok=True)
        for name in ["IDENTITY.md", "USER.md"]:
            path = self.workspace / name
            if path.exists():
                continue
            content = read_bootstrap(name)
            if content:
                path.write_text(content, encoding="utf-8")

    def _update_identity(self, answers: dict[str, str]) -> None:
        path = self.workspace / "IDENTITY.md"
        content = path.read_text(encoding="utf-8") if path.exists() else read_bootstrap("IDENTITY.md")

        directness = answers.get("directness", "direct")
        tone_constraints = answers.get("tone_constraints", "none")
        if directness == "soft":
            voice = "calm, diplomatic, supportive"
            challenge_style = "Challenge gently with clear evidence."
        elif directness == "very direct":
            voice = "direct, concise, blunt"
            challenge_style = "Challenge immediately and explicitly when assumptions are weak."
        else:
            voice = "clear, pragmatic, direct"
            challenge_style = "Challenge directly with reasons and alternatives."
        if tone_constraints and tone_constraints.lower() != "none":
            voice = f"{voice}; constraints: {tone_constraints}"

        response_style = answers.get("response_style", "balanced")
        decision_style = answers.get("decision_style", "one recommendation first")
        proactivity = answers.get("proactivity", "moderate")

        content = _upsert_bullet(content, "Name", answers.get("assistant_name", "yacb"))
        content = _upsert_bullet(content, "Role or creature (personal helper / operator default)", "personal assistant")
        content = _upsert_bullet(content, "Voice (3-5 adjectives: tone/personality of responses, e.g. calm, direct, witty)", voice)
        content = _upsert_bullet(content, "Signature emoji", "")
        content = _upsert_bullet(content, "Default verbosity", response_style)
        content = _upsert_bullet(content, "How to challenge user assumptions", challenge_style)
        content = _upsert_bullet(content, "What defines success criteria", decision_style)
        content = _upsert_bullet(content, "Proactive style (quiet / moderate / high-touch)", proactivity)

        today = datetime.now().strftime("%Y-%m-%d")
        content = _replace_or_append_change_log(content, f"- {today}: Initial identity onboarding completed")
        path.write_text(content, encoding="utf-8")

    def _update_user(self, answers: dict[str, str]) -> None:
        path = self.workspace / "USER.md"
        content = path.read_text(encoding="utf-8") if path.exists() else read_bootstrap("USER.md")

        content = _upsert_bullet(content, "Name", answers.get("user_name", "User"))
        content = _upsert_bullet(content, "Message length", answers.get("response_style", "balanced"))
        content = _upsert_bullet(content, "Decision style (single recommendation vs options)", answers.get("decision_style", "one recommendation first"))
        content = _upsert_bullet(content, "Feedback style", answers.get("directness", "direct"))
        content = _upsert_bullet(content, "Things to avoid", answers.get("tone_constraints", "none"))

        today = datetime.now().strftime("%Y-%m-%d")
        if re.search(r"(?m)^Last updated:\s*$", content):
            content = re.sub(r"(?m)^Last updated:\s*$", f"Last updated: {today}", content)
        elif re.search(r"(?m)^Last updated:\s*.+$", content):
            content = re.sub(r"(?m)^Last updated:\s*.+$", f"Last updated: {today}", content)
        else:
            content = content.rstrip() + f"\n\nLast updated: {today}\n"

        path.write_text(content, encoding="utf-8")


def _upsert_bullet(content: str, label: str, value: str) -> str:
    value_text = value.strip()
    line = f"- {label}: {value_text}"
    pattern = rf"(?m)^- {re.escape(label)}:.*$"
    if re.search(pattern, content):
        return re.sub(pattern, line, content, count=1)
    return content.rstrip() + f"\n{line}\n"


def _replace_or_append_change_log(content: str, entry: str) -> str:
    placeholder = r"(?m)^- YYYY-MM-DD: Initial identity\s*$"
    if re.search(placeholder, content):
        return re.sub(placeholder, entry, content, count=1)

    if re.search(r"(?m)^## Change Log\s*$", content):
        return re.sub(r"(?m)^## Change Log\s*$", f"## Change Log\n\n{entry}", content, count=1)

    return content.rstrip() + f"\n\n## Change Log\n\n{entry}\n"

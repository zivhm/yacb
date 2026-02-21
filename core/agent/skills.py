"""Skills loader for agent capabilities.

Two skill layers:
- **General skills** (`project/skills/`): Ship with the project, shared across all agents.
- **Agent skills** (`agent-workspace/<name>/skills/`): Per-agent, highest priority.
  Agent skills override general skills with the same name.

Supports multiple skill metadata formats for cross-ecosystem compatibility:
- **OpenClaw**: metadata nested under `openclaw` key with `requires`, `emoji`, `install`
- **yacb native**: metadata with top-level `requires`
- **JSON string**: metadata as a JSON string (legacy)
"""

import json
import os
import re
import shutil
from pathlib import Path

import yaml

# General skills that ship with the project (shared across all agents)
GENERAL_SKILLS_DIR = Path(__file__).parent.parent.parent / "skills"
_MAX_SKILL_DESC_CHARS = 90


class SkillsLoader:
    """Loader for agent skills (SKILL.md format)."""

    def __init__(self, workspace: Path, general_skills_dir: Path | None = None):
        self.workspace = workspace
        self.agent_skills = workspace / "skills"
        self.general_skills = general_skills_dir or GENERAL_SKILLS_DIR

    def list_skills(self, filter_unavailable: bool = True) -> list[dict[str, str]]:
        skills = []

        # Agent skills (per-agent, highest priority — overrides general)
        if self.agent_skills.exists():
            for skill_dir in self.agent_skills.iterdir():
                if skill_dir.is_dir():
                    skill_file = skill_dir / "SKILL.md"
                    if skill_file.exists():
                        skills.append({"name": skill_dir.name, "path": str(skill_file), "source": "agent"})

        # General skills (shared across all agents)
        if self.general_skills and self.general_skills.exists():
            for skill_dir in self.general_skills.iterdir():
                if skill_dir.is_dir():
                    skill_file = skill_dir / "SKILL.md"
                    if skill_file.exists() and not any(s["name"] == skill_dir.name for s in skills):
                        skills.append({"name": skill_dir.name, "path": str(skill_file), "source": "general"})

        if filter_unavailable:
            return [s for s in skills if self._check_requirements(self._get_skill_meta(s["name"]))]
        return skills

    def load_skill(self, name: str) -> str | None:
        agent_skill = self.agent_skills / name / "SKILL.md"
        if agent_skill.exists():
            return agent_skill.read_text(encoding="utf-8")
        if self.general_skills:
            general_skill = self.general_skills / name / "SKILL.md"
            if general_skill.exists():
                return general_skill.read_text(encoding="utf-8")
        return None

    def load_skills_for_context(self, skill_names: list[str]) -> str:
        parts = []
        for name in skill_names:
            content = self.load_skill(name)
            if content:
                content = self._strip_frontmatter(content)
                parts.append(f"### Skill: {name}\n\n{content}")
        return "\n\n---\n\n".join(parts) if parts else ""

    def build_skills_summary(self) -> str:
        all_skills = self.list_skills(filter_unavailable=False)
        if not all_skills:
            return ""

        def esc(s: str) -> str:
            return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        lines = ["<skills>"]
        for s in all_skills:
            name = esc(s["name"])
            desc = esc(self._shorten(self._get_skill_description(s["name"]), _MAX_SKILL_DESC_CHARS))
            meta = self._get_skill_meta(s["name"])
            available = self._check_requirements(meta)
            source = s.get("source", "general")
            location = esc(self._display_skill_location(s))

            lines.append(f'  <skill available="{str(available).lower()}" source="{source}">')
            lines.append(f"    <name>{name}</name>")
            lines.append(f"    <description>{desc}</description>")
            lines.append(f"    <location>{location}</location>")

            if not available:
                missing = self._get_missing_requirements(meta)
                if missing:
                    lines.append(f"    <requires>{esc(missing)}</requires>")
            lines.append("  </skill>")
        lines.append("</skills>")
        return "\n".join(lines)

    def _display_skill_location(self, skill: dict[str, str]) -> str:
        name = skill["name"]
        source = skill.get("source", "general")
        if source == "agent":
            return f"skills/{name}/SKILL.md"
        return f"project/skills/{name}/SKILL.md"

    @staticmethod
    def _shorten(text: str, max_chars: int) -> str:
        compact = " ".join(text.split())
        if len(compact) <= max_chars:
            return compact
        return compact[: max_chars - 3].rstrip() + "..."

    def get_always_skills(self) -> list[str]:
        result = []
        for s in self.list_skills(filter_unavailable=True):
            meta = self.get_skill_metadata(s["name"]) or {}
            if meta.get("always"):
                result.append(s["name"])
        return result

    def get_skill_metadata(self, name: str) -> dict | None:
        """Parse YAML frontmatter from a skill file.

        Handles full YAML (OpenClaw multi-line metadata blocks, Claude Code,
        Codex) and simple key: value frontmatter. Falls back to line-by-line
        parsing if strict YAML fails (e.g. unquoted colons in descriptions).
        """
        content = self.load_skill(name)
        if not content or not content.startswith("---"):
            return None
        match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
        if not match:
            return None
        raw = match.group(1)

        # Try strict YAML first (handles multi-line metadata, flow mappings, etc.)
        try:
            metadata = yaml.safe_load(raw)
            if isinstance(metadata, dict):
                return metadata
        except yaml.YAMLError:
            pass

        # Fallback: fix common YAML issues and retry
        # Quote unquoted description values that contain colons
        fixed_lines = []
        for line in raw.split("\n"):
            if line.startswith("description:") and not line.startswith("description: \""):
                desc = line.split(":", 1)[1].strip()
                if ":" in desc:
                    fixed_lines.append(f'description: "{desc}"')
                    continue
            fixed_lines.append(line)
        try:
            metadata = yaml.safe_load("\n".join(fixed_lines))
            if isinstance(metadata, dict):
                return metadata
        except yaml.YAMLError:
            pass

        # Last resort: line-by-line key: value parsing (ignores multi-line blocks)
        metadata = {}
        for line in raw.split("\n"):
            if ":" in line and not line.startswith(" ") and not line.startswith("\t"):
                key, value = line.split(":", 1)
                value = value.strip().strip("\"'")
                if value:
                    metadata[key.strip()] = value
        return metadata if metadata else None

    def _strip_frontmatter(self, content: str) -> str:
        if content.startswith("---"):
            match = re.match(r"^---\n.*?\n---\n", content, re.DOTALL)
            if match:
                return content[match.end():].strip()
        return content

    def _get_skill_description(self, name: str) -> str:
        meta = self.get_skill_metadata(name)
        if meta and meta.get("description"):
            return meta["description"]
        return name

    def _get_skill_meta(self, name: str) -> dict:
        """Extract skill meta (requires, etc.) from frontmatter metadata field.

        Supports multiple formats:
        - OpenClaw: metadata.openclaw.requires
        - yacb native: metadata.requires
        - JSON string: metadata: '{"requires": {...}}'
        - Top-level requires (no metadata wrapper)
        """
        meta = self.get_skill_metadata(name) or {}
        raw = meta.get("metadata", {})

        # If metadata is a string, try parsing as JSON (legacy yacb format)
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                raw = {}

        if not isinstance(raw, dict):
            raw = {}

        # OpenClaw format: metadata.openclaw.requires
        if "openclaw" in raw and isinstance(raw["openclaw"], dict):
            return raw["openclaw"]

        # Direct format: metadata.requires
        if "requires" in raw:
            return raw

        # Fallback: check if requires is at the top level of frontmatter
        if "requires" in meta and isinstance(meta["requires"], dict):
            return meta

        return raw

    def _check_requirements(self, skill_meta: dict) -> bool:
        requires = skill_meta.get("requires", {})
        if not isinstance(requires, dict):
            return True

        # bins: ALL must be present
        for b in requires.get("bins", []):
            if not shutil.which(b):
                return False

        # anyBins: at least ONE must be present (OpenClaw format)
        any_bins = requires.get("anyBins", [])
        if any_bins and not any(shutil.which(b) for b in any_bins):
            return False

        # env: ALL must be set
        for env in requires.get("env", []):
            if not os.environ.get(env):
                return False

        # config: skip — these reference host app config, not something we can check
        return True

    def _get_missing_requirements(self, skill_meta: dict) -> str:
        missing = []
        requires = skill_meta.get("requires", {})
        if not isinstance(requires, dict):
            return ""

        for b in requires.get("bins", []):
            if not shutil.which(b):
                missing.append(f"CLI: {b}")

        any_bins = requires.get("anyBins", [])
        if any_bins and not any(shutil.which(b) for b in any_bins):
            missing.append(f"CLI (any): {', '.join(any_bins)}")

        for env in requires.get("env", []):
            if not os.environ.get(env):
                missing.append(f"ENV: {env}")

        return ", ".join(missing)

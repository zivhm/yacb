"""Prompt loading helpers."""

from pathlib import Path
from typing import Any

import yaml

PROMPTS_DIR = Path(__file__).parent
BOOTSTRAP_DIR = PROMPTS_DIR / "bootstrap"


def read_text(name: str, default: str = "") -> str:
    path = PROMPTS_DIR / name
    try:
        content = path.read_text(encoding="utf-8")
        if content.startswith("<!--"):
            end = content.find("-->")
            if end != -1:
                header = content[: end + 3]
                if "DOC:" in header:
                    content = content[end + 3 :]
                    content = content.lstrip("\n")
        return content
    except FileNotFoundError:
        return default
    except Exception:
        return default


def read_yaml(name: str, default: Any) -> Any:
    content = read_text(name, "")
    if not content:
        return default
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError:
        return default
    return default if data is None else data


def read_bootstrap(name: str, default: str = "") -> str:
    path = BOOTSTRAP_DIR / name
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return default
    except Exception:
        return default

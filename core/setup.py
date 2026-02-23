"""Interactive setup wizard for yacb."""

import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import httpx
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from core.onboarding_spec import ONBOARDING_QUESTIONS
from core.prompts.loader import read_yaml

console = Console()

TOTAL_STEPS = 11
_SETUP_UI_TUI = False
_SETUP_UI_SUMMARY: dict[str, str] | None = None

# Skills that should always be installed into each agent workspace during setup.
CORE_DEFAULT_SKILLS = [
    "alive-pulse",
    "coding-agent",
    "mcporter",
    "session-logs",
    "model-usage",
    "memory-pulse",
    "skill-creator",
]

# ─── Provider definitions ───────────────────────────────────────────

PROVIDERS = [
    {
        "name": "openai",
        "label": "OpenAI (ChatGPT)",
        "description": "Makes ChatGPT, GPT-4, DALL-E. Most popular AI provider.",
        "key_url": "https://platform.openai.com/api-keys",
        "model_list_url": "https://platform.openai.com/docs/models",
        "default_model": "openai/gpt-4o",
        "models": [
            ("openai/gpt-4o", "GPT-4o - fast and smart (recommended)"),
            ("openai/gpt-4o-mini", "GPT-4o Mini - cheaper, still good"),
            ("openai/o3-mini", "o3-mini - best at reasoning"),
        ],
        "signup_url": "https://platform.openai.com/signup",
        "key_help": [
            "1. Go to https://platform.openai.com/api-keys",
            "2. Click '+ Create new secret key'",
            "3. Give it a name (e.g. 'yacb') and click 'Create'",
            "4. Copy the key (starts with sk-)",
            "",
            "You need to add a payment method first ($5 minimum).",
            "Go to https://platform.openai.com/settings/organization/billing",
        ],
    },
    {
        "name": "anthropic",
        "label": "Anthropic (Claude)",
        "description": "Makes Claude. Great at writing, coding, and following instructions.",
        "key_url": "https://console.anthropic.com/settings/keys",
        "model_list_url": "https://docs.anthropic.com/en/docs/about-claude/models",
        "default_model": "anthropic/claude-sonnet-4-20250514",
        "models": [
            ("anthropic/claude-sonnet-4-20250514", "Claude Sonnet 4 - fast and capable (recommended)"),
            ("anthropic/claude-3-5-haiku-20241022", "Claude Haiku 3.5 - cheapest"),
        ],
        "signup_url": "https://console.anthropic.com/",
        "key_help": [
            "1. Go to https://console.anthropic.com/settings/keys",
            "2. Click 'Create Key'",
            "3. Give it a name (e.g. 'yacb') and click 'Create Key'",
            "4. Copy the key (starts with sk-ant-)",
            "",
            "You need to add credits first ($5 minimum).",
            "Go to https://console.anthropic.com/settings/billing",
        ],
    },
    {
        "name": "openrouter",
        "label": "OpenRouter (many models)",
        "description": "Access to 100+ models from all providers through one API key. Pay per use.",
        "key_url": "https://openrouter.ai/keys",
        "model_list_url": "https://openrouter.ai/models",
        "models_api_url": "https://openrouter.ai/api/v1/models",
        "api_base": "https://openrouter.ai/api/v1",
        "default_model": "openrouter/anthropic/claude-sonnet-4-5-20250929",
        "models": [
            ("openrouter/anthropic/claude-sonnet-4-5-20250929", "Claude Sonnet 4.5 via OpenRouter"),
            ("openrouter/openai/gpt-4o", "GPT-4o via OpenRouter"),
            ("openrouter/google/gemini-2.0-flash-001", "Gemini 2.0 Flash via OpenRouter"),
            ("openrouter/deepseek/deepseek-chat", "DeepSeek V3 via OpenRouter (cheapest)"),
        ],
        "signup_url": "https://openrouter.ai/",
        "key_help": [
            "1. Go to https://openrouter.ai/keys",
            "2. Click 'Create Key'",
            "3. Copy the key (starts with sk-or-)",
            "",
            "Add credits at https://openrouter.ai/credits",
            "Some models have free tiers (marked as free on openrouter.ai).",
        ],
    },
    {
        "name": "opencode",
        "label": "OpenCode Zen",
        "description": "Unified endpoint for many models behind one API key (OpenAI-compatible API).",
        "key_url": "https://opencode.ai/docs/providers#opencode-zen",
        "model_list_url": "https://opencode.ai/zen/v1/models",
        "models_api_url": "https://opencode.ai/zen/v1/models",
        "default_model": "opencode/qwen3-coder",
        "api_base": "https://opencode.ai/zen/v1",
        "models": [
            ("opencode/qwen3-coder", "Qwen3 Coder - strong coding model (recommended)"),
            ("opencode/qwen3-30b-a3b-instruct", "Qwen3 30B - cheaper general chat"),
            ("opencode/claude-sonnet-4.5", "Claude Sonnet 4.5 via OpenCode Zen"),
        ],
        "signup_url": "https://opencode.ai/",
        "key_help": [
            "1. Go to https://opencode.ai/docs/providers#opencode-zen",
            "2. Create or copy your OpenCode Zen API key",
            "3. Paste it here",
            "",
            "API base used by yacb: https://opencode.ai/zen/v1",
            "Tip: prefer chat/completions-compatible models (like qwen3-coder).",
        ],
    },
    {
        "name": "deepseek",
        "label": "DeepSeek",
        "description": "Chinese AI lab. Very cheap, good at coding. Best value for money.",
        "key_url": "https://platform.deepseek.com/api_keys",
        "model_list_url": "https://api-docs.deepseek.com/quick_start/pricing",
        "default_model": "deepseek/deepseek-chat",
        "models": [
            ("deepseek/deepseek-chat", "DeepSeek V3 - great value (recommended)"),
            ("deepseek/deepseek-reasoner", "DeepSeek R1 - slower but better at reasoning"),
        ],
        "signup_url": "https://platform.deepseek.com/",
        "key_help": [
            "1. Go to https://platform.deepseek.com/api_keys",
            "2. Click 'Create new API key'",
            "3. Copy the key",
            "",
            "DeepSeek gives free credits on signup.",
            "Add more at https://platform.deepseek.com/top_up",
        ],
    },
    {
        "name": "gemini",
        "label": "Google Gemini",
        "description": "Google's AI. Has a generous free tier.",
        "key_url": "https://aistudio.google.com/apikey",
        "model_list_url": "https://ai.google.dev/gemini-api/docs/models",
        "default_model": "gemini/gemini-2.0-flash",
        "models": [
            ("gemini/gemini-2.0-flash", "Gemini 2.0 Flash - fast, free tier available"),
            ("gemini/gemini-2.5-pro-preview-05-06", "Gemini 2.5 Pro - most capable"),
        ],
        "signup_url": "https://aistudio.google.com/",
        "key_help": [
            "1. Go to https://aistudio.google.com/apikey",
            "2. Click 'Create API key'",
            "3. Select or create a Google Cloud project",
            "4. Copy the key",
            "",
            "Gemini has a FREE tier with generous limits.",
            "No payment method needed to start.",
        ],
    },
]

# ─── Channel definitions ────────────────────────────────────────────

CHANNELS = [
    {
        "name": "telegram",
        "label": "Telegram",
        "description": "Best for getting started. Works on phone and desktop.",
        "needs_token": True,
        "token_label": "bot token",
        "setup_steps": [
            "1. Open Telegram on your phone or computer",
            "2. Search for @BotFather and open a chat with it",
            "   (or tap this link: https://t.me/BotFather)",
            "3. Send the message: /newbot",
            "4. BotFather will ask you for a name - type anything (e.g. 'My Assistant')",
            "5. BotFather will ask for a username - must end in 'bot' (e.g. 'my_yacb_bot')",
            "6. BotFather will give you a token that looks like:",
            "   123456789:ABCdefGHIjklMNOpqrsTUVwxyz",
            "7. Copy that token",
        ],
        "user_id_help": [
            "To find your Telegram user ID (so only YOU can talk to the bot):",
            "1. Search for @userinfobot on Telegram",
            "2. Send it any message",
            "3. It replies with your user ID (a number like 123456789)",
        ],
        "test_help": "Open Telegram, find your bot by its username, and send it 'Hello'",
    },
    {
        "name": "discord",
        "label": "Discord",
        "description": "Great if you already use Discord. Can work in servers or DMs.",
        "needs_token": True,
        "token_label": "bot token",
        "setup_steps": [
            "1. Go to https://discord.com/developers/applications",
            "2. Click 'New Application' and give it a name",
            "3. Go to the 'Bot' section on the left",
            "4. Click 'Reset Token' and copy the token",
            "5. Scroll down and enable these under 'Privileged Gateway Intents':",
            "   - Message Content Intent (REQUIRED)",
            "   - Server Members Intent (optional)",
            "6. Go to 'OAuth2' > 'URL Generator' on the left",
            "7. Check 'bot' under Scopes",
            "8. Check these Bot Permissions: Send Messages, Read Message History",
            "9. Copy the generated URL at the bottom and open it",
            "10. Select your server and click 'Authorize'",
        ],
        "user_id_help": [
            "To find your Discord user ID:",
            "1. Open Discord Settings > Advanced > turn on Developer Mode",
            "2. Right-click your own name anywhere > Copy User ID",
        ],
        "test_help": "Go to your Discord server and mention your bot or DM it",
    },
    {
        "name": "whatsapp",
        "label": "WhatsApp",
        "description": "Uses your real WhatsApp number. Pure Python, no Node.js needed.",
        "needs_token": False,
        "setup_steps": [
            "WhatsApp connects directly using neonize (no bridge needed).",
            "",
            "1. Start yacb with WhatsApp enabled",
            "2. A QR code will appear in the terminal",
            "3. On your phone: WhatsApp > Settings > Linked Devices > Link a Device",
            "4. Scan the QR code",
            "",
            "Auth state is saved so you only need to scan once.",
        ],
        "test_help": "Send a WhatsApp message to your own number from another phone, or create a group with yourself",
    },
]

# ─── Personality presets ─────────────────────────────────────────────

DEFAULT_PERSONALITY_PRESETS = [
    {"key": "friendly", "label": "Friendly helper", "prompt": "You are a warm, friendly personal assistant. You're enthusiastic and supportive, using a conversational tone."},
    {"key": "professional", "label": "Professional assistant", "prompt": "You are a professional, efficient assistant. You're precise, well-organized, and business-appropriate."},
    {"key": "sarcastic", "label": "Sarcastic buddy", "prompt": "You are a witty, sarcastic assistant with a sharp sense of humor. You're helpful but never miss a chance for clever banter."},
    {"key": "creative", "label": "Creative partner", "prompt": "You are a creative, imaginative assistant. You think outside the box, suggest novel ideas, and bring an artistic flair to everything."},
    {"key": "minimal", "label": "Concise & minimal", "prompt": "You are a concise assistant. You give short, direct answers without filler. You value brevity above all."},
]

DEFAULT_INTERACTION_STYLES = [
    {"key": "casual", "label": "Casual", "description": "Relaxed, conversational, like texting a friend", "prompt": "Use a casual, conversational tone."},
    {"key": "professional", "label": "Professional", "description": "Formal, business-appropriate, structured", "prompt": "Use a professional, structured tone."},
    {"key": "brief", "label": "Brief", "description": "Short answers, bullet points, no fluff", "prompt": "Keep your responses brief and to the point."},
    {"key": "detailed", "label": "Detailed", "description": "Thorough explanations, examples, context", "prompt": "Give thorough, detailed responses with examples when helpful."},
]


def _normalize_presets(data: list) -> list[tuple[str, str, str]]:
    presets: list[tuple[str, str, str]] = []
    for item in data:
        if isinstance(item, (list, tuple)) and len(item) >= 3:
            key, label, prompt = item[:3]
        elif isinstance(item, dict):
            key, label, prompt = item.get("key"), item.get("label"), item.get("prompt")
        else:
            continue
        if key and label and prompt:
            presets.append((str(key), str(label), str(prompt)))
    return presets


def _normalize_styles(data: list) -> list[tuple[str, str, str, str]]:
    styles: list[tuple[str, str, str, str]] = []
    for item in data:
        if isinstance(item, (list, tuple)) and len(item) >= 4:
            key, label, desc, prompt = item[:4]
        elif isinstance(item, dict):
            key = item.get("key")
            label = item.get("label")
            desc = item.get("description")
            prompt = item.get("prompt")
        else:
            continue
        if key and label and desc and prompt:
            styles.append((str(key), str(label), str(desc), str(prompt)))
    return styles


_presets_raw = read_yaml("personality_presets.yaml", DEFAULT_PERSONALITY_PRESETS)
_styles_raw = read_yaml("interaction_styles.yaml", DEFAULT_INTERACTION_STYLES)
PERSONALITY_PRESETS = _normalize_presets(_presets_raw if isinstance(_presets_raw, list) else DEFAULT_PERSONALITY_PRESETS)
INTERACTION_STYLES = _normalize_styles(_styles_raw if isinstance(_styles_raw, list) else DEFAULT_INTERACTION_STYLES)


def _open_browser(url: str) -> bool:
    """Open URL in default browser."""
    try:
        import webbrowser
        return webbrowser.open(url)
    except Exception:
        return False


def _extract_model_ids(payload: object) -> list[str]:
    """Extract model IDs from common provider responses."""
    ids: list[str] = []
    rows: list[object] = []

    if isinstance(payload, dict):
        for key in ("data", "models", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                rows = value
                break
    elif isinstance(payload, list):
        rows = payload

    for item in rows:
        if isinstance(item, str):
            ids.append(item)
            continue
        if isinstance(item, dict):
            candidate = item.get("id") or item.get("name") or item.get("model")
            if isinstance(candidate, str):
                ids.append(candidate)

    # Keep stable order while deduping.
    return list(dict.fromkeys(ids))


def _extract_model_tools_support(payload: object) -> dict[str, bool]:
    """Extract per-model tool/function-calling support when provided."""
    support: dict[str, bool] = {}
    rows: list[object] = []

    if isinstance(payload, dict):
        for key in ("data", "models", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                rows = value
                break
    elif isinstance(payload, list):
        rows = payload

    for item in rows:
        if not isinstance(item, dict):
            continue
        model_id = item.get("id") or item.get("name") or item.get("model")
        if not isinstance(model_id, str):
            continue

        value: bool | None = None
        for direct_key in (
            "supports_tools",
            "supportsTools",
            "supports_function_calling",
            "supportsFunctionCalling",
        ):
            direct = item.get(direct_key)
            if isinstance(direct, bool):
                value = direct
                break

        if value is None:
            supported_params = item.get("supported_parameters")
            if isinstance(supported_params, list):
                params = {str(p).lower() for p in supported_params}
                if {"tools", "tool_choice", "functions", "function_calling"} & params:
                    value = True

        if value is None:
            features = item.get("features")
            if isinstance(features, dict):
                for feature_key in (
                    "supports_tools",
                    "supportsTools",
                    "tools",
                    "supports_function_calling",
                    "supportsFunctionCalling",
                ):
                    fv = features.get(feature_key)
                    if isinstance(fv, bool):
                        value = fv
                        break

        if value is not None:
            support[model_id] = value

    return support


def _fetch_provider_models(
    provider_name: str,
    api_key: str,
    api_base: str | None = None,
    models_api_url: str | None = None,
) -> tuple[list[str], dict[str, bool], str | None]:
    """Best-effort model list fetch from provider API."""
    url = models_api_url
    if not url:
        if provider_name == "openai":
            url = "https://api.openai.com/v1/models"
        elif provider_name == "deepseek":
            url = "https://api.deepseek.com/models"
        elif provider_name == "anthropic":
            url = "https://api.anthropic.com/v1/models"
        elif api_base:
            url = f"{api_base.rstrip('/')}/models"

    if not url:
        return [], {}, None

    headers: dict[str, str]
    if provider_name == "anthropic":
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }
    else:
        headers = {"Authorization": f"Bearer {api_key}"}

    try:
        resp = httpx.get(url, headers=headers, timeout=20)
        if resp.status_code >= 400:
            return [], {}, f"Could not fetch provider model list (HTTP {resp.status_code})."
        payload = resp.json()
        model_ids = _extract_model_ids(payload)
        tool_support = _extract_model_tools_support(payload)
        if not model_ids:
            return [], tool_support, "Provider model list endpoint returned no model IDs."
        return model_ids, tool_support, None
    except Exception as e:
        return [], {}, f"Could not fetch provider model list ({e})."


def _resolve_model_tools_support(
    provider_name: str,
    model_id: str,
    tools_support_map: dict[str, bool],
) -> bool | None:
    """Resolve tools support for a selected model from provider metadata."""
    if not tools_support_map:
        return None

    candidates = [model_id]
    prefix = f"{provider_name}/"
    if model_id.startswith(prefix):
        candidates.append(model_id.split("/", 1)[1])
    if provider_name == "opencode" and model_id.startswith("opencode/"):
        candidates.append(f"openai/{model_id.split('/', 1)[1]}")
    if provider_name == "openrouter" and not model_id.startswith("openrouter/"):
        candidates.append(f"openrouter/{model_id}")

    lowered_map = {k.lower(): v for k, v in tools_support_map.items()}
    for candidate in candidates:
        val = lowered_map.get(candidate.lower())
        if isinstance(val, bool):
            return val
    return None


def _opencode_endpoint_family(model_id: str) -> str:
    """Best-effort endpoint family for OpenCode Zen model IDs."""
    mid = model_id.strip().lower()
    if mid.startswith("opencode/"):
        mid = mid.split("/", 1)[1]

    # From OpenCode Zen docs: GPT* on /responses, Claude* on /messages,
    # and current openai-compatible families on /chat/completions.
    if mid.startswith("gpt-"):
        return "responses"
    if mid.startswith("claude-"):
        return "messages"
    if mid.startswith(
        (
            "qwen",
            "glm",
            "kimi",
            "minimax",
            "trinity",
            "big-pickle",
            "alpha-",
        )
    ):
        return "chat_completions"
    return "unknown"


def _build_probe_models(
    provider_name: str,
    recommended_models: list[str],
    api_models: list[str],
) -> list[str]:
    """Choose a small probe set to validate key/model access."""
    provider_hints: dict[str, tuple[str, ...]] = {
        "openrouter": (
            "openai/gpt-4o-mini",
            "anthropic/claude",
            "deepseek/deepseek-chat",
            "google/gemini",
        ),
        "opencode": (
            "qwen3-coder",
            "qwen3-30b",
            "minimax",
            "glm",
            "kimi",
        ),
        "openai": ("gpt-4o-mini", "gpt-4.1-mini", "o4-mini"),
        "anthropic": ("claude-haiku", "claude-sonnet"),
        "deepseek": ("deepseek-chat", "deepseek-reasoner"),
        "gemini": ("gemini-2.5-flash", "gemini-2.5-pro"),
    }

    candidates: list[str] = []

    # Prefer free-tier model IDs first when providers expose them in /models.
    free_api_models = [m for m in api_models if "free" in m.lower()]
    if provider_name in {"opencode", "openrouter"} and free_api_models:
        candidates.extend(free_api_models[:4])

    candidates.extend(recommended_models)

    hints = provider_hints.get(provider_name, ())
    lowered = [(m, m.lower()) for m in api_models]
    for hint in hints:
        for original, low in lowered:
            if hint in low:
                candidates.append(original)
                break

    # If hints missed, still try a few API models.
    candidates.extend(api_models[:4])

    deduped = list(dict.fromkeys(candidates))
    return deduped[:6]


def _test_api_key(
    provider_name: str,
    api_key: str,
    model: str,
    api_base: str | None = None,
    probe_models: list[str] | None = None,
) -> tuple[bool, str]:
    """Test if an API key works by making a tiny request."""
    def _classify_error(err: str) -> str:
        err_lower = err.lower()
        # Authentication failures (hard fail)
        auth_markers = (
            "invalid api key",
            "incorrect api key",
            "unauthorized",
            "authentication failed",
            "authentication error",
            "401",
        )
        if any(marker in err_lower for marker in auth_markers):
            return "auth"

        # Billing/rate-limit failures (hard fail with guidance)
        quota_markers = (
            "quota",
            "rate limit",
            "too many requests",
            "insufficient credits",
            "payment required",
            "no payment method",
            "add a payment method",
            "billing required",
            "402",
            "429",
        )
        if any(marker in err_lower for marker in quota_markers):
            return "quota"

        # Model/addressing failures (soft fail for probe, keep testing)
        model_markers = (
            "model",
            "404",
            "not found",
        )
        if any(marker in err_lower for marker in model_markers):
            return "model"

        # Permission/access scope failures (soft fail for probe, keep testing)
        access_markers = (
            "forbidden",
            "403",
            "permission",
            "access denied",
            "not allowed",
            "model access",
        )
        if any(marker in err_lower for marker in access_markers):
            return "access"

        return "other"

    def _to_probe_model(candidate: str) -> str:
        test_model = candidate
        if provider_name == "opencode":
            # OpenCode Zen is OpenAI-compatible; send provider/model as openai/<model>.
            if "/" in test_model:
                test_model = test_model.split("/", 1)[1]
            test_model = f"openai/{test_model}"
        return test_model

    candidates = [model]
    if probe_models:
        candidates.extend(probe_models)
    deduped_candidates = list(dict.fromkeys(candidates))

    try:
        import litellm
        os.environ[f"{provider_name.upper()}_API_KEY"] = api_key

        model_not_found_errors: list[str] = []
        access_errors: list[str] = []
        quota_errors: list[str] = []
        for candidate in deduped_candidates:
            test_model = _to_probe_model(candidate)
            kwargs = {
                "model": test_model,
                "messages": [{"role": "user", "content": 'Say "ok" and nothing else.'}],
                "max_tokens": 5,
                "timeout": 15,
                "api_key": api_key,
            }
            if api_base:
                kwargs["api_base"] = api_base

            try:
                response = litellm.completion(**kwargs)
                text = response.choices[0].message.content.strip()
                return True, text
            except Exception as e:
                err = str(e)
                error_kind = _classify_error(err)
                if error_kind == "auth":
                    return False, "Invalid API key. Please check and try again."
                if error_kind == "quota":
                    quota_errors.append(err)
                    continue
                if error_kind == "model":
                    model_not_found_errors.append(err)
                    continue
                if error_kind == "access":
                    access_errors.append(err)
                    continue
                return False, f"Connection error: {err[:150]}"

        if model_not_found_errors or access_errors:
            return (
                True,
                "API key appears valid, but probe models were unavailable or restricted. "
                "Continue and pick an available model in Step 3.",
            )
        if quota_errors:
            return (
                False,
                "API key is valid, but probed models require billing/credits or hit rate limits. "
                "If your provider has free-tier models, pick one explicitly in Step 3.",
            )
        return False, "Connection error: API probe failed for unknown reasons."
    except Exception as e:
        err = str(e)
        error_kind = _classify_error(err)
        if error_kind == "auth":
            return False, "Invalid API key. Please check and try again."
        if error_kind == "quota":
            return False, "API key works but you've hit a rate limit or have no credits. Add billing/credits to your account."
        if error_kind in {"model", "access"}:
            return (
                True,
                "API key appears valid, but probe models were unavailable or restricted. "
                "Continue and pick an available model in Step 3.",
            )
        return False, f"Connection error: {err[:150]}"


def _probe_model_tools_support(
    provider_name: str,
    api_key: str,
    model_id: str,
    api_base: str | None = None,
) -> tuple[bool | None, str]:
    """Probe tools/function-calling support for a specific model.

    Returns:
      - (True, "") when tools appear supported.
      - (False, reason) when tools are explicitly unsupported/incompatible.
      - (None, reason) when the probe is inconclusive (quota/network/access/etc).
    """
    # OpenCode Zen currently routes families to different endpoints.
    # yacb uses chat/completions via LiteLLM, so mark known incompatible families.
    if provider_name == "opencode":
        family = _opencode_endpoint_family(model_id)
        if family == "responses":
            return (
                False,
                "This OpenCode model family uses /responses, while yacb currently uses /chat/completions.",
            )
        if family == "messages":
            return (
                False,
                "This OpenCode model family uses /messages, while yacb currently uses /chat/completions.",
            )

    probe_model = model_id
    if provider_name == "opencode":
        if "/" in probe_model:
            probe_model = probe_model.split("/", 1)[1]
        probe_model = f"openai/{probe_model}"

    try:
        import litellm

        kwargs = {
            "model": probe_model,
            "messages": [{"role": "user", "content": 'Say "ok" and nothing else.'}],
            "max_tokens": 8,
            "timeout": 15,
            "api_key": api_key,
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "ping",
                        "description": "Ping probe.",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ],
            "tool_choice": "auto",
        }
        if api_base:
            kwargs["api_base"] = api_base

        litellm.completion(**kwargs)
        return True, ""
    except Exception as e:
        err = str(e)
        err_lower = err.lower()

        unsupported_markers = (
            "doesn't support",
            "does not support",
            "not supported",
            "unsupported",
            "unknown parameter",
            "invalid parameter",
        )
        tools_markers = ("tools", "tool", "function", "tool_choice")
        if any(marker in err_lower for marker in unsupported_markers) and any(
            marker in err_lower for marker in tools_markers
        ):
            return False, err[:180]

        return None, err[:180]


def _probe_model_chat_support(
    provider_name: str,
    api_key: str,
    model_id: str,
    api_base: str | None = None,
) -> tuple[bool, str]:
    """Check whether a model accepts a basic chat/completions request."""
    probe_model = model_id
    if provider_name == "opencode":
        if "/" in probe_model:
            probe_model = probe_model.split("/", 1)[1]
        probe_model = f"openai/{probe_model}"

    try:
        import litellm

        kwargs = {
            "model": probe_model,
            "messages": [{"role": "user", "content": 'Say "ok" and nothing else.'}],
            "max_tokens": 5,
            "timeout": 15,
            "api_key": api_key,
        }
        if api_base:
            kwargs["api_base"] = api_base

        litellm.completion(**kwargs)
        return True, ""
    except Exception as e:
        return False, str(e)[:180]


def _choose_router_candidate(
    provider_name: str,
    model_id: str,
    api_models: list[str],
    fallback: str,
    hints: tuple[str, ...],
) -> str:
    """Pick a provider/model candidate from available model IDs with hint matching."""
    prefix = f"{provider_name}/"
    candidates: list[str] = [model_id]

    for hint in hints:
        for raw in api_models:
            if hint in raw.lower():
                if raw.startswith(prefix):
                    candidates.append(raw)
                else:
                    candidates.append(f"{prefix}{raw}")

    deduped = list(dict.fromkeys(candidates))
    for candidate in deduped:
        if candidate != model_id:
            return candidate
    return fallback


def _sync_runtime_settings_from_setup(
    workspace: Path,
    provider_name: str,
    medium_model: str,
    tier_cfg: dict | None,
) -> Path:
    """Update settings.json so runtime matches onboarding selections."""
    from core.config import load_agent_settings

    workspace = workspace.expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)

    prefix = "openrouter/" if provider_name == "openrouter" else f"{provider_name}/"

    def normalize_model(model_id: str, fallback: str) -> str:
        model = (model_id or "").strip()
        if not model:
            return fallback
        if model.startswith(prefix):
            return model
        if provider_name == "openrouter":
            return f"{prefix}{model}"
        if "/" not in model:
            return f"{prefix}{model}"
        return fallback

    settings = load_agent_settings(workspace)
    settings["model"] = normalize_model(medium_model, medium_model)

    tier_enabled = bool(tier_cfg and tier_cfg.get("enabled"))
    tiers_cfg = (tier_cfg or {}).get("tiers") if isinstance(tier_cfg, dict) else None
    light_raw = ""
    heavy_raw = ""
    if isinstance(tiers_cfg, dict):
        light_raw = str(((tiers_cfg.get("light") or {}).get("model", "")))
        heavy_raw = str(((tiers_cfg.get("heavy") or {}).get("model", "")))
    else:
        # Backward compatibility with legacy setup shape.
        light_raw = str((tier_cfg or {}).get("light_model", ""))
        heavy_raw = str((tier_cfg or {}).get("heavy_model", ""))

    light = normalize_model(light_raw, settings["model"])
    heavy = normalize_model(heavy_raw, settings["model"])
    settings["tier_router"] = {
        "enabled": tier_enabled,
        "tiers": {
            "light": {"model": light if tier_enabled else ""},
            "medium": {"model": settings["model"]},
            "heavy": {"model": heavy if tier_enabled else ""},
        },
    }
    settings.pop("llm_router", None)

    settings_path = workspace / "settings.json"
    settings_path.write_text(
        json.dumps(settings, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return settings_path


def _test_telegram_token(token: str) -> tuple[bool, str, str]:
    """Test if a Telegram bot token works. Returns (ok, bot_name, error)."""
    try:
        import httpx
        r = httpx.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10)
        if r.status_code == 200:
            data = r.json()
            if data.get("ok"):
                bot = data["result"]
                name = bot.get("first_name", "")
                username = bot.get("username", "")
                return True, f"{name} (@{username})", ""
        if r.status_code == 401:
            return False, "", "Invalid token. Please check and try again."
        return False, "", f"Telegram API error (status {r.status_code})"
    except Exception as e:
        return False, "", f"Could not reach Telegram: {e}"


def _test_discord_token(token: str) -> tuple[bool, str, str]:
    """Test if a Discord bot token works. Returns (ok, bot_name, error)."""
    try:
        import httpx
        r = httpx.get(
            "https://discord.com/api/v10/users/@me",
            headers={"Authorization": f"Bot {token}"},
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            name = data.get("username", "")
            return True, name, ""
        if r.status_code == 401:
            return False, "", "Invalid token. Please check and try again."
        return False, "", f"Discord API error (status {r.status_code})"
    except Exception as e:
        return False, "", f"Could not reach Discord: {e}"


def _step_header(num: int, title: str, subtitle: str = "") -> None:
    """Print a nice step header with progress indicator."""
    if _SETUP_UI_TUI:
        console.clear()
        console.print(Panel(
            "[bold cyan]yacb setup[/bold cyan]\n"
            "[dim]App mode enabled - guided setup[/dim]",
            border_style="blue",
            width=70,
        ))
        if _SETUP_UI_SUMMARY:
            summary_table = Table(show_header=False, width=70, padding=(0, 1))
            summary_table.add_column("Setting", style="bold", width=18)
            summary_table.add_column("Value", width=48)
            for key, value in list(_SETUP_UI_SUMMARY.items())[-8:]:
                summary_table.add_row(key, value)
            console.print(Panel(
                summary_table,
                title="Current choices",
                border_style="cyan",
                width=70,
            ))

    progress = f"[dim]({num}/{TOTAL_STEPS})[/dim]"
    bar_filled = num
    bar_empty = TOTAL_STEPS - num
    bar = f"[green]{'*' * bar_filled}[/green][dim]{'.' * bar_empty}[/dim]"
    text = f"{bar}  [bold cyan]Step {num}[/bold cyan] {progress}  [bold]{title}[/bold]"
    if subtitle:
        text += f"\n{'  ' * 4}[dim]{subtitle}[/dim]"
    console.print(f"\n{text}\n")


def _set_setup_ui(tui: bool, summary: dict[str, str] | None) -> None:
    """Configure setup UI mode for shared render helpers."""
    global _SETUP_UI_TUI, _SETUP_UI_SUMMARY
    _SETUP_UI_TUI = tui
    _SETUP_UI_SUMMARY = summary


def _parse_multi_select(raw: str, max_index: int) -> list[int]:
    """Parse multi-select input like '1,3' or 'all' into 0-based indices."""
    text = raw.strip().lower()
    if not text:
        return []
    if text == "all":
        return list(range(max_index))

    picked: list[int] = []
    seen: set[int] = set()
    for part in text.split(","):
        p = part.strip()
        if not p.isdigit():
            continue
        idx = int(p) - 1
        if 0 <= idx < max_index and idx not in seen:
            picked.append(idx)
            seen.add(idx)
    return picked


def _core_skills_for_workspace(available_skill_names: list[str]) -> list[str]:
    """Return core default skills that are present in the general skills set."""
    available = set(available_skill_names)
    return [name for name in CORE_DEFAULT_SKILLS if name in available]


def _merge_with_core_skills(selected_names: list[str], available_skill_names: list[str]) -> list[str]:
    """Ensure selected skills always include required core defaults."""
    available = set(available_skill_names)
    merged: list[str] = []
    seen: set[str] = set()
    ordered = selected_names + _core_skills_for_workspace(available_skill_names)
    for name in ordered:
        if name in available and name not in seen:
            merged.append(name)
            seen.add(name)
    return merged


def _install_workspace_skills(workspace_path: Path, skills_dir: Path, selected_names: list[str]) -> list[str]:
    """Copy selected skills from general skills dir into workspace if missing."""
    if not selected_names:
        return []
    agent_skills_dir = workspace_path / "skills"
    try:
        agent_skills_dir.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        console.print(
            f"[yellow]Skipping skill install: no write permission for {agent_skills_dir}.[/yellow]"
        )
        return []
    installed: list[str] = []
    for name in selected_names:
        src = skills_dir / name
        dst = agent_skills_dir / name
        if src.exists() and not dst.exists():
            try:
                shutil.copytree(src, dst)
                installed.append(name)
            except PermissionError:
                console.print(
                    f"[yellow]Skipping skill '{name}': no write permission for {dst}.[/yellow]"
                )
        elif dst.exists():
            installed.append(name)  # Already present
    return installed


def _validate_hhmm(value: str) -> bool:
    """Validate 24h HH:MM values."""
    if not re.match(r"^\d{2}:\d{2}$", value):
        return False
    hh, mm = value.split(":")
    h = int(hh)
    m = int(mm)
    return 0 <= h <= 23 and 0 <= m <= 59


def _prompt_hhmm(label: str, default: str) -> str:
    """Prompt until a valid HH:MM time is entered."""
    while True:
        value = Prompt.ask(label, default=default).strip()
        if _validate_hhmm(value):
            return value
        console.print("[red]Invalid format. Use HH:MM in 24-hour format (example: 08:30).[/red]")


def _parse_allow_from(channel_name: str, raw: str) -> tuple[list[str], list[str]]:
    """Return (valid, invalid) access IDs for a channel."""
    values = [v.strip() for v in raw.split(",") if v.strip()]
    if not values:
        return [], []

    valid: list[str] = []
    invalid: list[str] = []

    for value in values:
        if channel_name in {"telegram", "discord"}:
            if value.lstrip("-").isdigit():
                valid.append(value)
            else:
                invalid.append(value)
            continue

        if channel_name == "whatsapp":
            compact = re.sub(r"[\s\-\(\)]", "", value)
            digits = compact[1:] if compact.startswith("+") else compact
            if digits.isdigit() and 7 <= len(digits) <= 15:
                valid.append(compact)
            else:
                invalid.append(value)
            continue

        valid.append(value)

    return valid, invalid


def _prompt_allow_from(
    channel_name: str,
    label: str,
    default_values: list[str] | None = None,
) -> list[str]:
    """Prompt for allow_from values with channel-specific validation."""
    default_raw = ",".join(default_values or [])
    while True:
        raw = Prompt.ask(label, default=default_raw).strip()
        valid, invalid = _parse_allow_from(channel_name, raw)
        if invalid:
            console.print(
                f"[red]Invalid value(s): {', '.join(invalid)}[/red] "
                "[dim](check format and try again)[/dim]"
            )
            continue
        return valid


def _build_personality_prompt(bot_name: str, preset_prompt: str, style: str, emoji: str, spirit_animal: str) -> str:
    """Compose a system prompt from personality builder choices."""
    parts = []

    if bot_name and bot_name.lower() != "yacb":
        parts.append(f"Your name is {bot_name}.")

    parts.append(preset_prompt)

    style_prompt = None
    for key, _label, _desc, prompt in INTERACTION_STYLES:
        if key == style:
            style_prompt = prompt
            break
    if style_prompt:
        parts.append(style_prompt)

    if spirit_animal:
        parts.append(f"Your spirit animal is a {spirit_animal}.")

    if emoji:
        parts.append(f"You occasionally use the {emoji} emoji.")

    return " ".join(parts)


def _render_first_run_bootstrap() -> str:
    """Build first-run onboarding instructions for workspace bootstrap."""
    questions_block = "\n".join(
        f'{idx}. "{question}"'
        for idx, (_key, question) in enumerate(ONBOARDING_QUESTIONS, start=1)
    )
    return f"""# BOOTSTRAP.md - First-Run Identity Onboarding

Run this workflow once, then delete this file.

## Goal

Move bot customization to live chat. Start neutral, then personalize with focused questions.

## Required Flow (strict)

1. On the first user message after setup:
   - Respond in a neutral, helpful tone first.
   - In the same reply, start onboarding with a short transition and Question 1.
2. Ask onboarding questions one at a time (or max two at once if user asks for speed).
3. After answers are complete:
   - Update `IDENTITY.md` with concrete values.
   - Update `USER.md` communication and working preferences.
   - If helpful, add channel/delivery notes in `TOOLS.md`.
4. Add a dated line in `IDENTITY.md` Change Log for this initialization.
5. Delete `BOOTSTRAP.md` when finished.

Control commands during onboarding:

- `pause onboarding` (or `later`)
- `resume onboarding`
- `status onboarding`
- `skip onboarding`

## Better Identity Questions (focused)

Ask these in order:

{questions_block}

## Mapping Rules

- `IDENTITY.md`
  - Name -> assistant display name from Q2
  - Role or creature -> "personal assistant"
  - Voice -> tone constraints + directness
  - Signature emoji -> only if user explicitly wants one
  - Default verbosity -> Q3
  - How to challenge user assumptions -> Q4
  - What defines success criteria -> user's stated preference
  - Proactive style -> Q6

- `USER.md`
  - Name -> Q1
  - Message length -> Q3
  - Decision style -> Q5
  - Feedback style -> Q4
  - Things to avoid -> Q7

Keep entries short, specific, and practical.
"""


def _ensure_first_run_bootstrap(workspace: Path) -> tuple[Path, bool]:
    """Create BOOTSTRAP.md for first-run identity onboarding if missing."""
    workspace = workspace.expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    bootstrap_path = workspace / "BOOTSTRAP.md"
    if bootstrap_path.exists():
        return bootstrap_path, False
    bootstrap_path.write_text(_render_first_run_bootstrap(), encoding="utf-8")
    return bootstrap_path, True


def _slugify_workspace_name(name: str) -> str:
    """Convert a display name into a safe workspace folder slug."""
    text = (name or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text or "yacb"


def _can_prepare_workspace(path: Path) -> bool:
    """Return whether setup can create/write inside workspace path."""
    try:
        path = path.expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def _resolve_setup_workspace(config_dir: Path, workspace_slug: str) -> tuple[str, str | None]:
    """Resolve a writable workspace path, with fallback to ~/.yacb if needed."""
    primary = (config_dir / "agent-workspace" / workspace_slug).expanduser().resolve()
    if _can_prepare_workspace(primary):
        return str(primary), None

    fallback = (Path.home() / ".yacb" / "agent-workspace" / workspace_slug).expanduser().resolve()
    if _can_prepare_workspace(fallback):
        reason = (
            f"Workspace path '{primary}' is not writable; using fallback '{fallback}'."
        )
        return str(fallback), reason

    raise PermissionError(
        f"Could not prepare writable workspace at '{primary}' or fallback '{fallback}'. "
        "Check filesystem permissions and try again."
    )


def _can_write_config_path(path: Path) -> bool:
    """Return whether setup can write the target config file path."""
    try:
        path = path.expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            with path.open("a", encoding="utf-8"):
                pass
        else:
            probe = path.parent / ".config-write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def _resolve_setup_config_output(config_path: str) -> tuple[Path, str | None]:
    """Resolve a writable config output path, with fallback to ~/.yacb when needed."""
    primary = Path(config_path).expanduser().resolve()
    if _can_write_config_path(primary):
        return primary, None

    fallback = (Path.home() / ".yacb" / primary.name).expanduser().resolve()
    if _can_write_config_path(fallback):
        reason = f"Config path '{primary}' is not writable; saving to fallback '{fallback}'."
        return fallback, reason

    raise PermissionError(
        f"Could not write config to '{primary}' or fallback '{fallback}'. "
        "Check filesystem permissions and try again."
    )


def run_setup(config_path: str = "config.local.yaml", tui: bool = False) -> None:
    """Interactive setup wizard."""
    summary: dict[str, str] = {}
    _set_setup_ui(tui, summary)

    console.print()
    console.print(Panel(
        "[bold]Welcome to yacb setup[/bold]\n\n"
        "yacb is your personal AI assistant. It connects to messaging apps\n"
        "(Telegram, Discord, WhatsApp) so you can chat with an AI that\n"
        "remembers things, searches the web, reads/writes files, and more.\n\n"
        "This wizard will walk you through everything step by step.\n"
        "It takes about 5 minutes.",
        title="yacb",
        border_style="blue",
        width=70,
    ))

    # Workspace lives next to the config file
    config_dir = Path(config_path).resolve().parent
    assistant_name = Prompt.ask("Assistant name (used for workspace folder)", default="yacb").strip()
    workspace_slug = _slugify_workspace_name(assistant_name)
    try:
        default_workspace, workspace_note = _resolve_setup_workspace(config_dir, workspace_slug)
    except PermissionError as e:
        console.print(f"[red]{e}[/red]")
        _set_setup_ui(False, None)
        return

    config: dict = {
        "agents": {"default": {
            "model": "",
            "system_prompt": "You are a helpful personal assistant.",
            "workspace": default_workspace,
            "tools": ["filesystem", "shell", "web", "message", "cron", "memory"],
            "max_iterations": 20,
            "temperature": 0.7,
            "bot_name": assistant_name or "yacb",
            "interaction_style": "casual",
            "chat_mode": "personal",
        }},
        "routes": {},
        "channels": {
            "telegram": {"enabled": False, "token": "", "allow_from": []},
            "whatsapp": {"enabled": False, "auth_dir": "", "allow_from": []},
            "discord": {"enabled": False, "token": "", "allow_from": []},
        },
        "providers": {},
        "tools": {"exec": {"timeout": 60}, "restrict_to_workspace": False},
        "heartbeat": {"enabled": False, "interval_minutes": 240},
    }
    summary["Assistant"] = config["agents"]["default"]["bot_name"]
    summary["Workspace"] = default_workspace
    if workspace_note:
        console.print(f"[yellow]{workspace_note}[/yellow]")

    # ╔══════════════════════════════════════════════════════════════╗
    # ║  STEP 1: Choose an AI Provider                              ║
    # ╚══════════════════════════════════════════════════════════════╝

    _step_header(1, "Choose an AI Provider",
                 "This is the 'brain' behind your bot. You need an account with one of these services.")

    table = Table(show_header=True, show_lines=True, width=70)
    table.add_column("#", style="bold", width=3)
    table.add_column("Provider", width=22)
    table.add_column("What is it?", width=42)
    for i, p in enumerate(PROVIDERS, 1):
        table.add_row(str(i), p["label"], p["description"])
    console.print(table)

    console.print(
        "\n[dim]Not sure? Pick [bold]1 (OpenAI)[/bold], [bold]4 (OpenCode Zen)[/bold], "
        "or [bold]6 (Gemini)[/bold] for easy onboarding.[/dim]"
    )

    choice = Prompt.ask(
        "\nEnter a number",
        choices=[str(i) for i in range(1, len(PROVIDERS) + 1)],
        default="1",
    )
    provider = PROVIDERS[int(choice) - 1]
    provider_name = provider["name"]
    provider_prefix = "openrouter/" if provider_name == "openrouter" else f"{provider_name}/"

    def normalize_selected_model(model_id: str, fallback: str) -> str:
        model = (model_id or "").strip()
        if not model:
            return fallback
        if model.startswith(provider_prefix):
            return model
        if provider_name == "openrouter":
            return f"{provider_prefix}{model}"
        if "/" not in model:
            return f"{provider_prefix}{model}"
        return fallback

    provider_api_models: list[str] = []
    provider_tools_support: dict[str, bool] = {}

    console.print(f"\n[green]v[/green] {provider['label']}")
    summary["Provider"] = provider["label"]

    # ╔══════════════════════════════════════════════════════════════╗
    # ║  STEP 2: Get an API key                                     ║
    # ╚══════════════════════════════════════════════════════════════╝

    _step_header(2, "Get your API key",
                 "An API key is like a password that lets yacb talk to the AI service.")

    console.print(Panel(
        "\n".join(provider["key_help"]),
        title=f"How to get a {provider['label']} API key",
        border_style="yellow",
        width=70,
    ))

    if Confirm.ask("\nOpen the API key page in your browser?", default=True):
        opened = _open_browser(provider["key_url"])
        if opened:
            console.print("[dim]Browser opened. Follow the steps above, then come back here.[/dim]")
        else:
            console.print(f"[dim]Couldn't open browser. Go to: {provider['key_url']}[/dim]")

    while True:
        api_key = Prompt.ask(
            f"\nPaste your {provider['label']} API key here "
            "[dim](type 'back' to restart setup menu)[/dim]"
        ).strip()
        if api_key.lower() in {"back", "b"}:
            console.print("[yellow]Returning to setup menu...[/yellow]")
            _set_setup_ui(False, None)
            run_setup(config_path, tui=tui)
            return
        if not api_key:
            console.print("[red]Key cannot be empty. Try again.[/red]")
            continue

        recommended_ids = [m for m, _ in provider.get("models", [])]
        provider_api_models, provider_tools_support, model_fetch_note = _fetch_provider_models(
            provider_name=provider["name"],
            api_key=api_key,
            api_base=provider.get("api_base"),
            models_api_url=provider.get("models_api_url"),
        )
        probe_models = _build_probe_models(
            provider_name=provider["name"],
            recommended_models=recommended_ids,
            api_models=provider_api_models,
        )

        if provider_api_models:
            console.print(
                f"[dim]Found {len(provider_api_models)} models from provider API; using a sampled set for key validation.[/dim]"
            )
        elif model_fetch_note:
            console.print(f"[dim]{model_fetch_note} Falling back to built-in probe models.[/dim]")

        console.print("[dim]Testing your API key...[/dim]", end=" ")
        ok, msg = _test_api_key(
            provider["name"],
            api_key,
            provider["default_model"],
            provider.get("api_base"),
            probe_models=probe_models,
        )
        if ok:
            console.print(f"[green bold]It works![/green bold] (AI said: '{msg}')")
            break
        else:
            console.print(f"\n[red]{msg}[/red]")
            if not Confirm.ask("Try a different key?", default=True):
                console.print("[yellow]Continuing with this key anyway...[/yellow]")
                break

    provider_cfg: dict[str, str] = {"api_key": api_key}
    if provider.get("api_base"):
        provider_cfg["api_base"] = provider["api_base"]
    config["providers"][provider["name"]] = provider_cfg
    summary["API key"] = f"{api_key[:8]}...{api_key[-4:]}" if len(api_key) > 12 else "(set)"

    # ╔══════════════════════════════════════════════════════════════╗
    # ║  STEP 3: Choose a model                                     ║
    # ╚══════════════════════════════════════════════════════════════╝

    _step_header(3, "Choose a model",
                 "Different models have different strengths and prices.")

    # Fetch all available models from litellm for this provider
    _non_chat = (
        "image", "audio", "tts", "realtime", "vision", "embed",
        "moderation", "dall", "whisper", "sora", "veo", "imagen",
        "live-", "transcribe", "search", "preview-image",
        "learnlm", "codex", "ft:", "fast/", "us/",
    )
    all_models: list[str] = []
    try:
        import litellm
        provider_key = provider["name"]
        # OpenRouter models are under a different key in litellm
        if provider_key == "openrouter":
            raw = litellm.models_by_provider.get("openrouter", [])
        else:
            raw = litellm.models_by_provider.get(provider_key, [])
        all_models = sorted([
            m for m in raw
            if not any(x in m.lower() for x in _non_chat)
        ])
    except Exception:
        all_models = []

    # Recommended picks shown first
    recommended = provider.get("models", [])
    model_list_url = provider.get("model_list_url", "")

    if model_list_url:
        console.print(f"[dim]Model list: {model_list_url}[/dim]\n")

    if recommended:
        console.print("[bold]Recommended models:[/bold]\n")
        table = Table(show_header=True, width=70)
        table.add_column("#", style="bold", width=3)
        table.add_column("Model", width=28)
        table.add_column("Description", width=36)
        for i, (model_id_r, desc) in enumerate(recommended, 1):
            table.add_row(str(i), model_id_r.split("/")[-1], desc)
        console.print(table)

    if all_models:
        if provider_api_models:
            all_models = sorted(list(dict.fromkeys(all_models + provider_api_models)))
        console.print(f"\n[dim]{len(all_models)} models available from {provider['label']}.[/dim]")
        console.print("[dim]Enter a number from above, type to filter (e.g. 'mini', 'opus', 'flash'), or enter a full model ID.[/dim]\n")
    else:
        if provider_api_models:
            all_models = sorted(provider_api_models)
            console.print(f"\n[dim]{len(all_models)} models available from provider API.[/dim]")
            console.print("[dim]Enter a number from above, type to filter (e.g. 'mini', 'opus', 'flash'), or enter a full model ID.[/dim]\n")
        else:
            console.print("\n[dim]Enter a number from above, or type a full model ID.[/dim]\n")

    prefix = provider_prefix

    while True:
        choice = Prompt.ask("Model [dim](or 'back' to restart setup menu)[/dim]", default="1").strip()
        if choice.lower() in {"back", "b"}:
            console.print("[yellow]Returning to setup menu...[/yellow]")
            _set_setup_ui(False, None)
            run_setup(config_path, tui=tui)
            return

        # Numeric pick from recommended list
        if choice.isdigit() and recommended:
            idx = int(choice) - 1
            if 0 <= idx < len(recommended):
                model_id = recommended[idx][0]
                break
            console.print(f"[red]Pick 1-{len(recommended)}, or type to filter.[/red]")
            continue

        # Direct full model ID (contains a slash)
        if "/" in choice:
            model_id = choice
            break

        # Filter: search all_models by the typed text
        if all_models:
            query = choice.lower()
            matches = [m for m in all_models if query in m.lower()]
            if not matches and query in {"free", "cheap", "cheapest"}:
                # LiteLLM provider lists often omit price tags like ':free'.
                # Fallback to low-cost family hints so this query remains useful.
                cheap_hints = ("mini", "nano", "flash", "haiku", "deepseek")
                matches = [m for m in all_models if any(h in m.lower() for h in cheap_hints)]
                if matches:
                    console.print(
                        "[yellow]No explicit 'free' tags were returned by LiteLLM for this provider. "
                        "Showing budget-friendly model families instead.[/yellow]"
                    )
            if not matches:
                console.print(f"[yellow]No models matching '{choice}'. Try again.[/yellow]")
                continue
            if len(matches) == 1:
                model_id = prefix + matches[0] if not matches[0].startswith(prefix) else matches[0]
                console.print(f"[green]v[/green] Matched: {model_id}")
                break

            # Show filtered results (cap at 20)
            console.print(f"\n[bold]{len(matches)} models matching '{choice}':[/bold]")
            display = matches[:20]
            table = Table(show_header=True, width=70)
            table.add_column("#", style="bold", width=4)
            table.add_column("Model", width=62)
            for i, m in enumerate(display, 1):
                table.add_row(str(i), m)
            console.print(table)
            if len(matches) > 20:
                console.print(f"[dim]...and {len(matches) - 20} more. Try a more specific filter.[/dim]")

            sub = Prompt.ask("\nPick a number, filter more, or enter a model ID", default="1").strip()
            if sub.isdigit():
                si = int(sub) - 1
                if 0 <= si < len(display):
                    m = display[si]
                    model_id = prefix + m if not m.startswith(prefix) else m
                    break
            elif "/" in sub:
                model_id = sub
                break
            else:
                # Treat as further filter
                query2 = sub.lower()
                matches2 = [m for m in matches if query2 in m.lower()]
                if len(matches2) == 1:
                    m = matches2[0]
                    model_id = prefix + m if not m.startswith(prefix) else m
                    console.print(f"[green]v[/green] Matched: {model_id}")
                    break
                elif matches2:
                    console.print(f"[yellow]Still {len(matches2)} matches. Pick from the list or be more specific.[/yellow]")
                else:
                    console.print(f"[yellow]No matches for '{sub}'. Try again.[/yellow]")
                continue
        else:
            # No litellm models available, treat as raw model ID
            model_id = prefix + choice
            break

    model_id = normalize_selected_model(model_id, provider["default_model"])
    config["agents"]["default"]["model"] = model_id
    console.print(f"[green]v[/green] {model_id}")
    summary["Model"] = model_id

    # Warn if the model doesn't support function calling (tools won't work)
    try:
        provider_tools_ok = _resolve_model_tools_support(
            provider_name=provider["name"],
            model_id=model_id,
            tools_support_map=provider_tools_support,
        )
        if provider_tools_ok is False:
            console.print(
                "\n[yellow bold]Warning:[/yellow bold] [yellow]Provider metadata says this model doesn't support tools/function calling. "
                "Your bot will only be able to chat — tools (web search, files, shell, etc.) won't work. "
                "Pick a different model or enable tier routing (Step 8) to auto-promote when tools are needed.[/yellow]\n"
            )
        elif provider_tools_ok is None:
            runtime_tools_ok, runtime_reason = _probe_model_tools_support(
                provider_name=provider["name"],
                api_key=api_key,
                model_id=model_id,
                api_base=provider.get("api_base"),
            )
            if runtime_tools_ok is False:
                console.print(
                    "\n[yellow bold]Warning:[/yellow bold] [yellow]This model doesn't support tool/function calls for yacb's current API path. "
                    "Your bot will only be able to chat — tools (web search, files, shell, etc.) won't work. "
                    "Pick a different model or enable tier routing (Step 8) to auto-promote when tools are needed.[/yellow]\n"
                )
                if runtime_reason:
                    console.print(f"[dim]Details: {runtime_reason}[/dim]\n")
            elif runtime_tools_ok is None:
                # Dynamic provider catalogs are often newer than LiteLLM static capability maps.
                # Avoid false negatives from static checks for OpenRouter/OpenCode when probe is inconclusive.
                if provider["name"] not in {"openrouter", "opencode"}:
                    from litellm import supports_function_calling as _sfc
                    if not _sfc(model_id):
                        console.print(
                            "\n[yellow bold]Warning:[/yellow bold] [yellow]This model doesn't support function calling. "
                            "Your bot will only be able to chat — tools (web search, files, shell, etc.) won't work. "
                            "Pick a different model or enable tier routing (Step 8) to auto-promote when tools are needed.[/yellow]\n"
                        )
                elif runtime_reason:
                    console.print(
                        "[dim]Could not auto-verify tool support for this model. "
                        "If tool calls fail at runtime, pick another model or enable tier routing.[/dim]"
                    )
    except Exception:
        pass

    # ╔══════════════════════════════════════════════════════════════╗
    # ║  STEP 4: Choose messaging apps                              ║
    # ╚══════════════════════════════════════════════════════════════╝

    _step_header(4, "Choose messaging apps",
                 "Pick one or more apps where you'll talk to your bot.")

    table = Table(show_header=True, show_lines=True, width=70)
    table.add_column("#", style="bold", width=3)
    table.add_column("App", width=14)
    table.add_column("What to know", width=50)
    for i, ch in enumerate(CHANNELS, 1):
        table.add_row(str(i), ch["label"], ch["description"])
    console.print(table)

    console.print("\n[dim]Examples: [bold]1[/bold], [bold]1,2[/bold], [bold]all[/bold][/dim]")
    console.print("[dim]Not sure? Start with [bold]1 (Telegram)[/bold].[/dim]")

    selected_channels: list[dict] = []
    while not selected_channels:
        raw = Prompt.ask("\nEnter number(s)", default="1")
        picked = _parse_multi_select(raw, len(CHANNELS))
        if not picked:
            console.print("[red]Pick at least one valid number (example: 1 or 1,3).[/red]")
            continue
        selected_channels = [CHANNELS[i] for i in picked]

    console.print(f"\n[green]v[/green] {', '.join(ch['label'] for ch in selected_channels)}")
    summary["Channels"] = ", ".join(ch["label"] for ch in selected_channels)
    primary_channel = selected_channels[0]

    # ╔══════════════════════════════════════════════════════════════╗
    # ║  STEP 5: Set up messaging apps                              ║
    # ╚══════════════════════════════════════════════════════════════╝

    _step_header(5, "Set up messaging apps",
                 "Follow the guided setup for each app you selected.")

    for idx, channel in enumerate(selected_channels, 1):
        console.print(Panel(
            "\n".join(channel["setup_steps"]),
            title=f"{idx}/{len(selected_channels)} · Set up {channel['label']}",
            border_style="yellow",
            width=70,
        ))

        config["channels"][channel["name"]]["enabled"] = True

        if channel["needs_token"]:
            while True:
                token = Prompt.ask(
                    f"\nPaste your {channel['label']} {channel['token_label']}"
                ).strip()
                if not token:
                    console.print("[red]Token cannot be empty. Try again.[/red]")
                    continue

                console.print(f"[dim]Testing {channel['label']} connection...[/dim]", end=" ")
                if channel["name"] == "telegram":
                    ok, bot_name, err = _test_telegram_token(token)
                    if ok:
                        console.print(f"[green bold]Connected![/green bold] Your bot: {bot_name}")
                        break
                    console.print(f"\n[red]{err}[/red]")
                elif channel["name"] == "discord":
                    ok, bot_name, err = _test_discord_token(token)
                    if ok:
                        console.print(f"[green bold]Connected![/green bold] Your bot: {bot_name}")
                        break
                    console.print(f"\n[red]{err}[/red]")
                else:
                    console.print("[green]Saved.[/green]")
                    break

                if not Confirm.ask("Try a different token?", default=True):
                    console.print("[yellow]Continuing with this token anyway...[/yellow]")
                    break

            config["channels"][channel["name"]]["token"] = token

            console.print()
            console.print(Panel(
                "By default, ANYONE can message your bot.\n"
                "You can restrict it so only you (or specific people) can use it.\n\n"
                "This is recommended - you probably don't want strangers using your AI credits.",
                title=f"Security ({channel['label']})",
                border_style="yellow",
                width=70,
            ))

            if Confirm.ask("Restrict access?", default=True):
                if "user_id_help" in channel:
                    console.print()
                    for line in channel["user_id_help"]:
                        console.print(f"  [dim]{line}[/dim]")
                    console.print()
                user_ids = _prompt_allow_from(
                    channel["name"], "Your user ID(s) (comma-separated if multiple)"
                )
                if user_ids:
                    config["channels"][channel["name"]]["allow_from"] = user_ids
                    console.print(f"[green]v[/green] Access restricted to: {', '.join(user_ids)}")
                    summary[f"Access ({channel['label']})"] = f"Restricted to {', '.join(user_ids)}"
                else:
                    console.print("[yellow]No IDs entered - bot will be open to everyone.[/yellow]")
                    summary[f"Access ({channel['label']})"] = "Open to everyone"
            else:
                summary[f"Access ({channel['label']})"] = "Open to everyone"
        else:
            console.print(
                "\n[dim]WhatsApp will show a QR code on first run. Scan it to connect.[/dim]"
            )
            if Confirm.ask("Set WhatsApp access restrictions now?", default=False):
                phone_ids = _prompt_allow_from(
                    "whatsapp",
                    "Phone number(s) (comma-separated, include country code, e.g. +15551234567)",
                )
                if phone_ids:
                    config["channels"][channel["name"]]["allow_from"] = phone_ids
                    console.print(f"[green]v[/green] Access restricted to: {', '.join(phone_ids)}")
                    summary[f"Access ({channel['label']})"] = f"Restricted to {', '.join(phone_ids)}"
                else:
                    summary[f"Access ({channel['label']})"] = "Open to everyone"
            else:
                summary[f"Access ({channel['label']})"] = "Open to everyone"

    # ╔══════════════════════════════════════════════════════════════╗
    # ║  STEP 6: Group vs Personal mode                             ║
    # ╚══════════════════════════════════════════════════════════════╝

    _step_header(6, "Personal or group chat?",
                 "This affects how your bot behaves by default.")

    console.print("[bold]1.[/bold] [cyan]Personal[/cyan] (default)")
    console.print("   Bot is proactive, uses memory freely, manages files without asking")
    console.print()
    console.print("[bold]2.[/bold] [cyan]Group[/cyan]")
    console.print("   Bot only responds when mentioned/replied to, careful with memory,")
    console.print("   announces actions before taking them")
    console.print()

    choice = Prompt.ask("Choose mode", choices=["1", "2"], default="1")
    chat_mode = "personal" if choice == "1" else "group"
    config["agents"]["default"]["chat_mode"] = chat_mode
    console.print(f"[green]v[/green] {chat_mode.title()} mode")
    summary["Chat mode"] = chat_mode.title()

    # ╔══════════════════════════════════════════════════════════════╗
    # ║  STEP 7: First-run customization                            ║
    # ╚══════════════════════════════════════════════════════════════╝

    _step_header(7, "Defer customization to first live chat",
                 "Setup now handles infrastructure. Identity onboarding happens after first message.")

    config["agents"]["default"]["system_prompt"] = "You are a helpful personal assistant."
    config["agents"]["default"]["interaction_style"] = "casual"

    console.print(Panel(
        "Personality and identity are now configured after the bot is live.\n\n"
        "Flow after startup:\n"
        "1. User sends first message (for example: 'hey')\n"
        "2. Bot responds neutrally\n"
        "3. Bot starts focused onboarding questions\n"
        "4. Bot updates IDENTITY.md/USER.md and finalizes bootstrap\n",
        title="Post-live onboarding",
        border_style="cyan",
        width=70,
    ))
    summary["Customization"] = "First live chat onboarding"

    # ╔══════════════════════════════════════════════════════════════╗
    # ║  STEP 8: Tier routing (optional)                            ║
    # ╚══════════════════════════════════════════════════════════════╝

    _step_header(8, "Tier routing (optional)",
                 "Route simple prompts to lighter models and complex prompts to heavier models.")

    console.print(
        "[bold]Tier routing[/bold] uses deterministic rules (no classifier call):\n"
        "  [cyan]light[/cyan]  - short/simple prompts  -> cheaper model\n"
        "  [cyan]medium[/cyan] - default workload       -> your chosen model\n"
        "  [cyan]heavy[/cyan]  - complex/coding prompts -> stronger model\n\n"
        "[dim]You can force a tier per message: !tier <light|medium|heavy> <message>[/dim]\n"
    )

    if Confirm.ask("Enable tier routing?", default=False):
        # Auto-configure based on provider
        _router_defaults = {
            "anthropic": {
                "light": "anthropic/claude-haiku-4-20250414",
                "heavy": "anthropic/claude-sonnet-4-5-20250929",
            },
            "openai": {
                "light": "openai/gpt-4.1-mini",
                "heavy": "openai/o4-mini",
            },
            "gemini": {
                "light": "gemini/gemini-2.5-flash",
                "heavy": "gemini/gemini-2.5-pro",
            },
            "deepseek": {
                "light": "deepseek/deepseek-chat",
                "heavy": "deepseek/deepseek-reasoner",
            },
            "openrouter": {
                "light": "openrouter/anthropic/claude-haiku-4-20250414",
                "heavy": "openrouter/anthropic/claude-sonnet-4-5-20250929",
            },
            "opencode": {
                "light": "opencode/qwen3-30b-a3b-instruct",
                "heavy": "opencode/qwen3-coder",
            },
        }
        defaults = _router_defaults.get(provider["name"], {})
        light = defaults.get("light", model_id)
        heavy = defaults.get("heavy", model_id)

        # Prefer provider-exposed models for gateway providers, then validate.
        if provider["name"] == "opencode":
            light = _choose_router_candidate(
                provider_name="opencode",
                model_id=model_id,
                api_models=provider_api_models,
                fallback=light,
                hints=("kimi", "minimax", "glm", "qwen3-30b", "qwen3"),
            )
            heavy = _choose_router_candidate(
                provider_name="opencode",
                model_id=model_id,
                api_models=provider_api_models,
                fallback=heavy,
                hints=("qwen3-coder", "minimax-m2.5", "kimi-k2.5", "glm-4.7", "qwen3"),
            )
        elif provider["name"] == "openrouter":
            light = _choose_router_candidate(
                provider_name="openrouter",
                model_id=model_id,
                api_models=provider_api_models,
                fallback=light,
                hints=("haiku", "mini", "flash", "deepseek-chat", ":free"),
            )
            heavy = _choose_router_candidate(
                provider_name="openrouter",
                model_id=model_id,
                api_models=provider_api_models,
                fallback=heavy,
                hints=("sonnet", "opus", "gpt-4o", "o3", "qwen3-coder"),
            )

        # Ensure tier models are actually callable with this key; fallback to medium when not.
        checked_light, light_reason = _probe_model_chat_support(
            provider_name=provider["name"],
            api_key=api_key,
            model_id=light,
            api_base=provider.get("api_base"),
        )
        if not checked_light:
            console.print(
                f"[yellow]Tier routing: light model '{light}' is unavailable; using '{model_id}' instead.[/yellow]"
            )
            if light_reason:
                console.print(f"[dim]Reason: {light_reason}[/dim]")
            light = model_id

        checked_heavy, heavy_reason = _probe_model_chat_support(
            provider_name=provider["name"],
            api_key=api_key,
            model_id=heavy,
            api_base=provider.get("api_base"),
        )
        if not checked_heavy:
            console.print(
                f"[yellow]Tier routing: heavy model '{heavy}' is unavailable; using '{model_id}' instead.[/yellow]"
            )
            if heavy_reason:
                console.print(f"[dim]Reason: {heavy_reason}[/dim]")
            heavy = model_id

        tier_cfg = {
            "enabled": True,
            "light_model": light,
            "heavy_model": heavy,
        }
        light = normalize_selected_model(tier_cfg.get("light_model", ""), model_id)
        heavy = normalize_selected_model(tier_cfg.get("heavy_model", ""), model_id)
        config["agents"]["default"]["tier_router"] = {
            "enabled": True,
            "tiers": {
                "light": {"model": light},
                "medium": {"model": model_id},
                "heavy": {"model": heavy},
            },
        }
        console.print("[green]v[/green] Tier routing enabled")
        console.print(f"  light: {light}")
        console.print(f"  medium: {model_id}")
        console.print(f"  heavy: {heavy}")
        summary["Tier routing"] = f"light={light.split('/')[-1]}, heavy={heavy.split('/')[-1]}"
    else:
        config["agents"]["default"]["tier_router"] = {
            "enabled": False,
            "tiers": {
                "light": {"model": ""},
                "medium": {"model": model_id},
                "heavy": {"model": ""},
            },
        }
        console.print("[dim]Skipped - all messages will use your chosen model.[/dim]")
        summary["Tier routing"] = "Disabled"

    # ╔══════════════════════════════════════════════════════════════╗
    # ║  STEP 9: Proactive updates (heartbeat)                      ║
    # ╚══════════════════════════════════════════════════════════════╝

    _step_header(9, "Proactive updates (optional)",
                 "Let your bot send you interesting updates based on your interests.")

    console.print(
        "[bold]Alive Pulse[/bold] makes your bot feel alive — it periodically checks\n"
        "for things you care about (stocks, news, weather, etc.) and sends\n"
        "you updates on your messaging app.\n\n"
        "[dim]It reads your interests from MEMORY.md, searches the web, and\n"
        "only messages you when something interesting is found.[/dim]\n"
    )

    if Confirm.ask("Enable proactive updates?", default=False):
        config["heartbeat"]["enabled"] = True
        config["heartbeat"]["interval_minutes"] = 240

        # Auto-detect delivery target from configured channels
        deliver_to = ""
        default_target = ""
        for selected in selected_channels:
            ch_name = selected["name"]
            allow_from = config["channels"].get(ch_name, {}).get("allow_from", [])
            if allow_from:
                default_target = f"{ch_name}:{allow_from[0]}"
                break

        if default_target:
            deliver_to = Prompt.ask(
                "Deliver updates to (channel:chat_id)",
                default=default_target,
            ).strip()
        else:
            deliver_to = Prompt.ask(
                f"Deliver updates to (e.g. {primary_channel['name']}:YOUR_ID)",
                default="",
            ).strip()

        if deliver_to:
            config["heartbeat"]["deliver_to"] = deliver_to

        # Active hours
        console.print("\n[dim]Active hours control when updates can be sent (default 08:00-22:00).[/dim]")
        if Confirm.ask("Customize active hours?", default=False):
            start = _prompt_hhmm("Start time (HH:MM)", default="08:00")
            end = _prompt_hhmm("End time (HH:MM)", default="22:00")
            config["heartbeat"]["active_hours_start"] = start
            config["heartbeat"]["active_hours_end"] = end
        else:
            config["heartbeat"]["active_hours_start"] = "08:00"
            config["heartbeat"]["active_hours_end"] = "22:00"

        config["heartbeat"]["suppress_empty"] = True
        console.print("[green]v[/green] Proactive updates enabled (every 4 hours)")
        if deliver_to:
            console.print(f"  Delivering to: {deliver_to}")
        summary["Proactive updates"] = f"Every 4h -> {deliver_to or 'log only'}"
    else:
        console.print("[dim]Skipped - your bot will only respond when you message it.[/dim]")
        summary["Proactive updates"] = "Disabled"

    # ╔══════════════════════════════════════════════════════════════╗
    # ║  STEP 10: Skills                                            ║
    # ╚══════════════════════════════════════════════════════════════╝

    _step_header(10, "Choose skills (optional)",
                 "Skills give your bot extra abilities. You can change these later.")

    from core.agent.skills import GENERAL_SKILLS_DIR, SkillsLoader

    workspace_path = Path(config["agents"]["default"]["workspace"])
    loader = SkillsLoader(workspace=workspace_path, general_skills_dir=GENERAL_SKILLS_DIR)
    general_skills = []
    if GENERAL_SKILLS_DIR.exists():
        for skill_dir in sorted(GENERAL_SKILLS_DIR.iterdir()):
            if skill_dir.is_dir() and (skill_dir / "SKILL.md").exists():
                meta = loader.get_skill_metadata(skill_dir.name)
                desc = meta.get("description", skill_dir.name) if meta else skill_dir.name
                # Truncate long descriptions for display
                if len(desc) > 65:
                    desc = desc[:62] + "..."
                general_skills.append((skill_dir.name, desc))

    if general_skills:
        available_skill_names = [name for name, _ in general_skills]
        core_defaults = _core_skills_for_workspace(available_skill_names)

        console.print(
            f"Found [bold]{len(general_skills)}[/bold] available skills.\n"
            "Skills are loaded from [dim]project/skills/[/dim] (general) "
            "and can be overridden per-agent.\n"
        )
        if core_defaults:
            console.print(
                f"[dim]Core defaults (always installed): {', '.join(core_defaults)}[/dim]\n"
            )

        if Confirm.ask("Would you like to choose skills to install?", default=True):
            table = Table(show_header=True, width=70)
            table.add_column("#", style="bold", width=4)
            table.add_column("Skill", width=18)
            table.add_column("Description", width=45)
            for i, (name, desc) in enumerate(general_skills, 1):
                table.add_row(str(i), name, desc)
            console.print(table)

            console.print()
            console.print("[dim]Enter skill numbers separated by commas, 'all' for everything, or 'none' to skip.[/dim]")
            default_selection = "all"
            if core_defaults:
                core_indices = [
                    str(i)
                    for i, (name, _) in enumerate(general_skills, 1)
                    if name in core_defaults
                ]
                if core_indices:
                    default_selection = ",".join(core_indices)

            selection = Prompt.ask("Skills to install", default=default_selection).strip().lower()

            selected_names = []
            if selection == "none":
                selected_names = []
            elif selection == "all":
                selected_names = [name for name, _ in general_skills]
            else:
                for part in selection.split(","):
                    part = part.strip()
                    if part.isdigit():
                        idx = int(part) - 1
                        if 0 <= idx < len(general_skills):
                            selected_names.append(general_skills[idx][0])

            explicit_selected = list(selected_names)
            selected_names = _merge_with_core_skills(selected_names, available_skill_names)
            auto_added = [name for name in selected_names if name not in explicit_selected]
            if auto_added:
                console.print(f"[dim]Added core defaults: {', '.join(auto_added)}[/dim]")

            if selected_names:
                installed = _install_workspace_skills(workspace_path, GENERAL_SKILLS_DIR, selected_names)
                console.print(f"\n[green]v[/green] Installed {len(installed)} skills: {', '.join(installed[:5])}", end="")
                if len(installed) > 5:
                    console.print(f" (+{len(installed) - 5} more)")
                else:
                    console.print()
                summary["Skills"] = f"{len(installed)} installed"
            else:
                console.print("[dim]No skills selected.[/dim]")
                summary["Skills"] = "None"
        else:
            forced = _merge_with_core_skills([], available_skill_names)
            installed = _install_workspace_skills(workspace_path, GENERAL_SKILLS_DIR, forced)
            if installed:
                console.print(
                    "[dim]Selection skipped - installed core defaults into "
                    "agent-workspace/<name>/skills/.[/dim]"
                )
                summary["Skills"] = f"{len(installed)} core defaults"
            else:
                console.print("[dim]Skipped - you can add skills later in agent-workspace/<name>/skills/[/dim]")
                summary["Skills"] = "Skipped"
    else:
        console.print("[dim]No general skills found. You can add them later.[/dim]")
        summary["Skills"] = "None available"

    # ╔══════════════════════════════════════════════════════════════╗
    # ║  STEP 11: Summary & Save                                    ║
    # ╚══════════════════════════════════════════════════════════════╝

    _step_header(11, "Review & save",
                 "Here's everything you chose.")

    summary_table = Table(show_header=False, width=70, show_lines=False, padding=(0, 2))
    summary_table.add_column("Setting", style="bold", width=18)
    summary_table.add_column("Value", width=48)
    for key, value in summary.items():
        summary_table.add_row(f"[green]v[/green] {key}", value)
    console.print(Panel(summary_table, title="Your configuration", border_style="blue", width=70))

    # Safety checks before save
    warnings: list[str] = []
    for ch in selected_channels:
        ch_name = ch["name"]
        ch_cfg = config["channels"].get(ch_name, {})
        if ch["needs_token"] and not ch_cfg.get("allow_from"):
            warnings.append(
                f"{ch['label']}: access is open to everyone (`allow_from` is empty)."
            )
        if ch["needs_token"] and not ch_cfg.get("token"):
            warnings.append(f"{ch['label']}: token is empty.")

    if warnings:
        console.print()
        console.print(Panel(
            "\n".join(f"- {w}" for w in warnings),
            title="Before you save",
            border_style="yellow",
            width=70,
        ))
        if not Confirm.ask("Save anyway?", default=False):
            console.print("[yellow]Cancelled. Re-run setup when you're ready.[/yellow]")
            _set_setup_ui(False, None)
            return

    try:
        out_path, config_note = _resolve_setup_config_output(config_path)
    except PermissionError as e:
        console.print(f"[red]{e}[/red]")
        _set_setup_ui(False, None)
        return
    if config_note:
        console.print(f"[yellow]{config_note}[/yellow]")
    config_path = str(out_path)
    if out_path.exists():
        if not Confirm.ask(f"\n[yellow]{config_path} already exists. Overwrite?[/yellow]", default=True):
            alt = "config.local.2.yaml"
            try:
                alt_path, alt_note = _resolve_setup_config_output(alt)
            except PermissionError as e:
                console.print(f"[red]{e}[/red]")
                _set_setup_ui(False, None)
                return
            out_path = alt_path
            config_path = str(out_path)
            if alt_note:
                console.print(f"[yellow]{alt_note}[/yellow]")
        else:
            backup_name = f"{out_path.name}.bak.{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            backup_path = out_path.with_name(backup_name)
            try:
                shutil.copy2(out_path, backup_path)
                console.print(f"[dim]Backup created: {backup_path}[/dim]")
            except Exception as e:
                console.print(f"[yellow]Could not create backup: {e}[/yellow]")

    out_path.write_text(yaml.dump(config, default_flow_style=False, sort_keys=False), encoding="utf-8")

    # Keep runtime settings.json aligned with onboarding choices.
    agent_cfg = config["agents"]["default"]
    settings_path = _sync_runtime_settings_from_setup(
        workspace=Path(agent_cfg["workspace"]),
        provider_name=provider["name"],
        medium_model=agent_cfg["model"],
        tier_cfg=agent_cfg.get("tier_router"),
    )
    console.print(f"[dim]Synced runtime settings: {settings_path}[/dim]")
    bootstrap_path, bootstrap_created = _ensure_first_run_bootstrap(Path(agent_cfg["workspace"]))
    if bootstrap_created:
        console.print(f"[dim]Created first-run onboarding file: {bootstrap_path}[/dim]")
    else:
        console.print(f"[dim]First-run onboarding file already exists: {bootstrap_path}[/dim]")

    # ╔══════════════════════════════════════════════════════════════╗
    # ║  Done!                                                      ║
    # ╚══════════════════════════════════════════════════════════════╝

    saved_config_path = str(out_path.resolve())
    display_config_path = saved_config_path
    if " " in display_config_path:
        display_config_path = f"\"{display_config_path}\""
    run_cmd = f"uv run yacb {display_config_path}"
    test_lines = "\n".join(
        f"  - {ch['label']}: {ch['test_help']}" for ch in selected_channels
    )

    console.print()
    console.print(Panel(
        f"[bold green]Setup complete![/bold green]\n\n"
        f"Config saved to: [bold]{saved_config_path}[/bold]\n\n"
        f"[bold]To start your bot, run:[/bold]\n\n"
        f"  {run_cmd}\n\n"
        f"[bold]Then test each channel:[/bold]\n"
        f"{test_lines}\n\n"
        f"[dim]Press Ctrl+C to stop the bot.[/dim]\n\n"
        f"[dim]To change settings later, edit {saved_config_path} or run setup again.[/dim]",
        title="All done!",
        border_style="green",
        width=70,
    ))

    _set_setup_ui(False, None)

    # Offer to start right now (default yes).
    if Confirm.ask("\nStart the bot now?", default=True):
        with console.status("[bold cyan]Starting yacb...[/bold cyan]", spinner="dots"):
            import time
            time.sleep(1)  # Brief visual feedback
        console.print("\n[bold]Launching yacb...[/bold]\n")
        try:
            subprocess.run(["uv", "run", "yacb", saved_config_path], check=False)
        except FileNotFoundError:
            # Fallback path if uv isn't available in this shell.
            os.execvp(sys.executable, [sys.executable, "-m", "core.main", saved_config_path])


def run_channel_config(channel_name: str, config_path: str = "config.local.yaml") -> None:
    """Interactive channel configuration wizard."""
    _set_setup_ui(False, None)
    channel_name = channel_name.lower().strip()
    valid_channels = {"telegram", "whatsapp", "discord"}

    if channel_name not in valid_channels:
        console.print(f"[red]Unknown channel: {channel_name}[/red]")
        console.print(f"Valid channels: {', '.join(sorted(valid_channels))}")
        return

    console.print()
    console.print(Panel(
        f"[bold]Configure {channel_name.title()} channel[/bold]\n\n"
        f"This wizard will update your {channel_name.title()} settings\n"
        f"and save them to {config_path}.",
        title="yacb channel config",
        border_style="blue",
        width=70,
    ))

    # Load existing config
    out_path = Path(config_path)
    if out_path.exists():
        existing = yaml.safe_load(out_path.read_text(encoding="utf-8")) or {}
    else:
        existing = {}

    channels = existing.setdefault("channels", {})
    ch_config = channels.setdefault(channel_name, {})

    if channel_name == "telegram":
        _config_telegram(ch_config)
    elif channel_name == "whatsapp":
        _config_whatsapp(ch_config)
    elif channel_name == "discord":
        _config_discord(ch_config)

    # Save
    out_path.write_text(yaml.dump(existing, default_flow_style=False, sort_keys=False), encoding="utf-8")
    console.print(f"\n[green]Saved to {config_path}[/green]")


def _config_telegram(ch_config: dict) -> None:
    """Interactive Telegram channel configuration."""
    ch_config["enabled"] = True

    current_token = ch_config.get("token", "")
    if current_token:
        console.print(f"[dim]Current token: {current_token[:8]}...{current_token[-4:]}[/dim]")
        if not Confirm.ask("Change token?", default=False):
            token = current_token
        else:
            token = Prompt.ask("Telegram bot token").strip()
    else:
        token = Prompt.ask("Telegram bot token").strip()

    if token:
        console.print("[dim]Testing token...[/dim]", end=" ")
        ok, bot_name, err = _test_telegram_token(token)
        if ok:
            console.print(f"[green bold]Connected![/green bold] Bot: {bot_name}")
        else:
            console.print(f"[red]{err}[/red]")
        ch_config["token"] = token

    # Access control
    current_allow = ch_config.get("allow_from", [])
    if current_allow:
        console.print(f"[dim]Current allow_from: {', '.join(current_allow)}[/dim]")
    if Confirm.ask("Set access restrictions?", default=bool(not current_allow)):
        ch_config["allow_from"] = _prompt_allow_from(
            "telegram",
            "User ID(s) (comma-separated)",
            default_values=current_allow,
        )
    console.print("[green]v[/green] Telegram configured")

    # Proxy (optional)
    if Confirm.ask("Configure proxy?", default=False):
        proxy = Prompt.ask("Proxy URL (e.g. socks5://host:port)", default="").strip()
        if proxy:
            ch_config["proxy"] = proxy


def _config_whatsapp(ch_config: dict) -> None:
    """Interactive WhatsApp channel configuration."""
    ch_config["enabled"] = True

    current_auth = ch_config.get("auth_dir", "")
    if current_auth:
        console.print(f"[dim]Current auth_dir: {current_auth}[/dim]")
    auth_dir = Prompt.ask(
        "Auth directory (leave empty for default)",
        default=current_auth,
    ).strip()
    ch_config["auth_dir"] = auth_dir

    # Access control
    current_allow = ch_config.get("allow_from", [])
    if current_allow:
        console.print(f"[dim]Current allow_from: {', '.join(current_allow)}[/dim]")
    if Confirm.ask("Set access restrictions?", default=bool(not current_allow)):
        ch_config["allow_from"] = _prompt_allow_from(
            "whatsapp",
            "Phone number(s) (comma-separated, include country code)",
            default_values=current_allow,
        )
    console.print("[green]v[/green] WhatsApp configured")


def _config_discord(ch_config: dict) -> None:
    """Interactive Discord channel configuration."""
    ch_config["enabled"] = True

    current_token = ch_config.get("token", "")
    if current_token:
        console.print(f"[dim]Current token: {current_token[:8]}...{current_token[-4:]}[/dim]")
        if not Confirm.ask("Change token?", default=False):
            token = current_token
        else:
            token = Prompt.ask("Discord bot token").strip()
    else:
        token = Prompt.ask("Discord bot token").strip()

    if token:
        console.print("[dim]Testing token...[/dim]", end=" ")
        ok, bot_name, err = _test_discord_token(token)
        if ok:
            console.print(f"[green bold]Connected![/green bold] Bot: {bot_name}")
        else:
            console.print(f"[red]{err}[/red]")
        ch_config["token"] = token

    # Access control
    current_allow = ch_config.get("allow_from", [])
    if current_allow:
        console.print(f"[dim]Current allow_from: {', '.join(current_allow)}[/dim]")
    if Confirm.ask("Set access restrictions?", default=bool(not current_allow)):
        ch_config["allow_from"] = _prompt_allow_from(
            "discord",
            "User ID(s) (comma-separated)",
            default_values=current_allow,
        )
    console.print("[green]v[/green] Discord configured")

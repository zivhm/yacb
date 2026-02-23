# yacb Setup Guide

This guide gets you from zero to first message fast.

`yacb` is a personal AI assistant daemon that runs locally and connects to Telegram, Discord, and WhatsApp.

## 1. Requirements

You need:

- Python `3.11+`
- `uv`
- or Docker + Docker Compose
- At least one LLM provider API key (OpenAI, Anthropic, Gemini, DeepSeek, OpenRouter, or OpenCode Zen)
- At least one channel account (Telegram is usually the easiest first run)

Status note:

- Scope 1 (Lean Reliability Plan) is completed as of 2026-02-23.
- Tier routing command surface uses `!tier <light|medium|heavy> <message>`.
- Legacy `!light`, `!heavy`, and `!think` commands are deprecated.

## 2. Install

```bash
cd yacb
uv sync
```

Optional dev/test dependencies:

```bash
uv sync --extra dev
```

Docker install path (optional):

```bash
cd yacb
cp config.yaml config.docker.yaml
docker compose build
```

`config.docker.yaml` is reserved for Docker Compose.
Keep using `config.local.yaml` for local `uv run yacb` commands.

## 3. Run Guided Setup

```bash
uv run yacb init
```

The setup wizard handles:

- assistant naming + workspace folder (`agent-workspace/<assistant-slug>`)
- provider + API key validation
- model selection
- one or more channels in one run (`1`, `1,2`, or `all`)
- channel token checks (Telegram/Discord)
- channel access validation (`allow_from`)
- chat mode
- first-run identity onboarding bootstrap (`BOOTSTRAP.md`)
- optional tier router
- optional proactive heartbeat
- optional skill install
- pre-save warnings + config backup on overwrite

## 4. Start the Bot

After setup, run:

```bash
uv run yacb
```

Or run with an explicit config file:

```bash
uv run yacb config.local.yaml
```

Press `Ctrl+C` to stop.

For background mode:

```bash
uv run yacb start
uv run yacb status
uv run yacb logs -f
uv run yacb stop
```

Foreground mode (optional):

```bash
uv run yacb run
```

Docker runtime:

```bash
docker compose run --rm yacb init config.docker.yaml
docker compose up -d
docker compose logs -f yacb
docker compose down
```

## 5. Verify First Message

Send a simple message from your configured channel:

- `hello`
- `what's 2+2?`
- `remind me in 2 minutes to stand up`

On the first live chat, yacb now starts neutral and then asks focused onboarding
questions to customize identity files in the workspace.

If this works, runtime wiring is good (provider + channel + cron loop).

## 6. Channel-Only Reconfiguration

You can reconfigure channels without running full setup:

```bash
uv run yacb config telegram
uv run yacb config discord
uv run yacb config whatsapp
```

## 7. Recommended First-Time Choices

- Restrict channel access (`allow_from`) so strangers cannot use your credits.
- Keep `chat_mode: personal` unless you mainly run in busy groups.
- Enable tier routing if you want better cost/performance balance.
- Add fallback models for resilience on provider hiccups.
- Enable heartbeat only after your base chat flow is stable.

## 8. Important Config Knobs

| Setting | Path | Purpose |
|---|---|---|
| Base model | `agents.default.model` | Default model (`provider/model`) |
| Tier routing | `agents.default.tier_router.enabled` | Deterministic `light/medium/heavy` routing |
| Fallback models | `agents.default.fallback_models` | Ordered transient-failure fallback list |
| Max attempts | `agents.default.fallback_max_attempts` | Total model tries (1-5) |
| Chat mode | `agents.default.chat_mode` | `personal` or `group` |
| Access control | `channels.<name>.allow_from` | Allowed user IDs/phone IDs |
| Workspace lock | `tools.restrict_to_workspace` | Restrict file/shell tools to workspace |
| Web search key | `tools.tavily_api_key` | Enables `web_search` |
| Periodic audit | `tools.security_audit.enabled` | Periodic safety checks in service logs |
| Audit interval | `tools.security_audit.interval_minutes` | Minutes between periodic audits |
| Heartbeat toggle | `agents.default.heartbeat.enabled` | Enable proactive checks |
| Heartbeat target | `agents.default.heartbeat.deliver_to` | e.g. `telegram:123456` |
| Heartbeat window | `agents.default.heartbeat.active_hours_start/end` | Active delivery window |

Notes:

- Runtime behavior/state is persisted in `agent-workspace/<agent>/settings.json`.
- Relative `agents.<name>.workspace` paths are resolved from the config file directory.
- Recent chat history is persisted in SQLite and rehydrated on restart.
- Long-term conversation lookup is available through the `conversation_history` tool.
- Daily notes now store concise per-turn topics in `memory/daily/YYYY-MM-DD.md`.
- Prompt context is bounded (history + memory/skills sections) to control token usage in long sessions.
- `web_fetch` returns `security_warnings` when prompt-injection patterns are detected in fetched content.
- Periodic audits (if enabled) write summary/warnings into the runtime service log.
- `config.local.yaml` remains the default infra/secrets source for local CLI runs.
- `config.docker.yaml` is used by the Docker Compose workflow.

## 9. Tier Routing and Fallback (Quick Reference)

In-chat tier overrides:

- `!tier light ...`
- `!tier medium ...`
- `!tier heavy ...`

Tier intent (default deterministic behavior):

- `light`: simple questions, greetings, skill-use prompts, dates/definitions, short yes/no tasks
- `medium`: conversation, explanations, file tasks, web searches, and tool-using requests
- `heavy`: coding, debugging, complex reasoning, multi-step analysis, creative writing

Default setup picks provider-aware light/heavy models and keeps `medium` on your selected base model.

| Provider | Light preference | Heavy preference |
|---|---|---|
| Anthropic | Haiku 4.5 family | Sonnet 4.6/4.5, then Opus 4.6 |
| OpenAI | GPT-5 Nano/Mini, then GPT-4o Mini | GPT-5.3 Codex family, then GPT-5.3 |
| Gemini | Gemini 2.5 Flash Lite/Flash | Gemini 2.5 Pro |
| DeepSeek | `deepseek-chat` / `deepseek-v3` | `deepseek-reasoner` / `deepseek-r1` |
| OpenRouter | Anthropic pattern via `openrouter/*` | Anthropic pattern via `openrouter/*` |
| OpenCode Zen | Kimi/Minimax/GLM/Qwen3 light models | Qwen3-Coder/Minimax-M2.5/Kimi-K2.5/GLM-4.7 |

Alias examples:

- `haiku` -> `anthropic/claude-haiku-4-20250514`
- `gpt-4o-mini` -> `openai/gpt-4o-mini`
- `gemini-flash` -> `gemini/gemini-2.5-flash`
- `qwen3-coder` -> `opencode/qwen3-coder`

OpenCode Zen compatibility:

- `opencode/*` currently routes through an OpenAI-compatible adapter path.
- Prefer models listed under OpenCode Zen `/chat/completions`.
- `/responses` and `/messages` families are not guaranteed with this mapping.

Fallback policy:

- retries transient errors only (timeouts, `429`, `5xx`)
- stops on non-retryable errors (auth/invalid request)
- bounded by `fallback_max_attempts`

## 10. Troubleshooting

### `uv sync` fails with invalid `.venv`

Symptom:

- "Project virtual environment directory ... cannot be used because it is not a valid Python environment"

Fix:

```bash
rm -rf .venv
uv sync
```

### `pytest` not found

Fix:

```bash
uv sync --extra dev
uv run python -m pytest -q
```

### `docker compose` says `config.docker.yaml` is missing

Fix:

```bash
cp config.yaml config.docker.yaml
docker compose run --rm yacb init config.docker.yaml
```

### Bot does not respond

Check:

- process is running (`uv run yacb status`)
- provider key is valid and funded
- channel token is valid
- your user is included in `allow_from` (if enabled)

### Reminders do not fire

Check:

- bot stayed running long enough
- `agent-workspace/<agent>/settings.json` has `cron_jobs`
- no channel delivery mismatch (`deliver_to`, chat ID, channel ID)

## 11. Development Commands

```bash
uv sync --extra dev
uv run ruff check core tests
uv run pytest -q
```

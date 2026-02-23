# yacb Command Quick Reference

Use this as a fast command lookup.
For channel-specific notes, see below.

## Runtime CLI

- `uv run yacb` -> start background service (default config)
- `uv run yacb start [config_path]` -> start background service
- `uv run yacb status` -> show service status
- `uv run yacb logs [-f|--follow]` -> show logs (follow optional)
- `uv run yacb stop` -> stop background service
- `uv run yacb run [config_path]` -> run in foreground
- `uv run yacb init` -> guided setup (preferred)
- `uv run yacb config <telegram|discord|whatsapp>` -> channel-only setup

Legacy compatibility:

- `uv run yacb service <start|stop|status|logs> ...` still works.

## Docker Runtime

- `cp config.yaml config.docker.yaml` -> create editable local Docker config (first run)
- `docker compose build` -> build image
- `docker compose run --rm yacb init config.docker.yaml` -> run guided setup in container
- `docker compose up -d` -> start runtime container
- `docker compose logs -f yacb` -> follow runtime logs
- `docker compose down` -> stop container
- `docker compose run --rm yacb run config.docker.yaml` -> foreground run in one-off container

Docker note:
- Compose commands use `config.docker.yaml`.
- Local CLI commands keep using `config.local.yaml` by default.

## Works Across Channels

- `/commands` or `/help` -> show available commands
- `!<shell command>` -> run shell directly (example: `!ls -la`)
- `!model` -> show current model + tier routing status
- `!model <provider/model>` -> set default model
- `!tier <light|medium|heavy> <message>` -> force routing tier for one message
- Legacy tier commands `!light`, `!heavy`, `!think` are deprecated -> use `!tier ...`
- `!restart` -> restart confirmation prompt
- `!restart now` -> restart yacb process
- `!update` -> update confirmation prompt
- `!update now` -> run `git pull --ff-only` then restart

Natural language also works for most tasks:

- `remind me in 20 minutes to ...`
- `what's on my calendar tomorrow?`
- `summarize today's priorities`
- `what did we discuss about <topic> last week?`

## Telegram

- `/start` -> bot intro
- `/debug` -> toggle model debug footer
- `/toggle_verbose_logs` -> toggle verbose logging
- `/commands` or `/help` -> command list

## Discord

- `/commands` -> native slash command (auto-synced on startup)
- `!toggle-verbose-logs` -> toggle verbose logging
- `!commands`, `/commands`, `!help`, `/help` -> command list

## WhatsApp

- `/commands` or `/help` -> command list
- `!model ...` commands are supported

## Notes

- Runtime behavior/state is per agent in `agent-workspace/<agent>/settings.json`.
- Conversation logs are persisted in SQLite and can be queried by the `conversation_history` tool.
- Reserved bang prefixes `!model`, `!tier`, `!restart`, `!update` are not executed as shell commands.
- Default router intent: `light` for simple/skill prompts, `medium` for tool/search/file tasks, `heavy` for coding/debugging.
- Optional periodic audits (`tools.security_audit.*`) write summary lines to service logs.
- Command behavior may differ by chat mode (`personal` vs `group`) and channel policies.

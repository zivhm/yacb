# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog.

## [Unreleased]

### Added

- Docker runtime support artifacts:
  - `Dockerfile`
  - `docker-compose.yml`
  - `.dockerignore`
- Compose workflow now documents a dedicated `config.docker.yaml` file.
- New `conversation_history` tool for long-term chat log access:
  - `recent` (latest rows)
  - `search` (FTS/LIKE query)
  - chat-scoped by default (`chat_only: true`)

### Changed

- Documentation updated for Docker vs local config separation across:
  - `README.md`
  - `SETUP.md`
  - `COMMANDS.md`
- Prompt context now has explicit bounds to reduce token growth in long sessions:
  - history window capped in prompt input
  - workspace/bootstrap, active-skills, and skills-index sections capped
  - memory context (long-term, today notes, knowledge overview) capped
- Daily notes now append concise topic entries per turn (instead of assistant transcript snippets).
- Relative workspace paths are now resolved from the config file directory (not process CWD).
- Contributing guide now uses `uv sync --extra dev` for development setup.
- LLM router tier auto-resolution patterns were updated across providers:
  - Anthropic/OpenRouter now prefer Haiku 4.5 for `light` and Sonnet 4.6/4.5 (then Opus 4.6) for `heavy`
  - OpenAI now prefers GPT-5 Nano/Mini for `light` and GPT-5.3 Codex family for `heavy`
  - Gemini and OpenCode Zen tier preference lists were refreshed
- Router classification guidance was updated so skill-use prompts bias to `light`, while web-search/tool tasks stay `medium`.

### Fixed

- Local runtime data under `.yacb/` is no longer tracked in git.
- Session context no longer appears "forgotten" after restart:
  - recent conversation history rehydrates from SQLite on first message.
- DB logging failures are no longer silently swallowed; warnings are emitted to runtime logs.

## [0.1.2] - 2026-02-18

### Added

- Deterministic first-run onboarding flow (`BOOTSTRAP.md`) enforced before LLM turns.
- Onboarding control commands: `pause onboarding`, `resume onboarding`, `status onboarding`, `skip onboarding`.
- Chat-scoped onboarding state files under workspace `.onboarding/` (replacing single shared state behavior).
- Shared onboarding question spec (`core/onboarding_spec.py`) used by both runtime onboarding and setup bootstrap generation.

### Changed

- Setup now defers personality customization to first live chat instead of setup-time personality prompts.
- Setup now asks assistant name up front and uses it to create workspace folder slug (`agent-workspace/<assistant-slug>`).
- First-run onboarding now syncs assistant display name into runtime `settings.json` (`bot_name`) after completion.
- Context builder now includes `BOOTSTRAP.md` in workspace context when present.
- Documentation/prompt text updated to reflect deterministic onboarding + background-service workflow.

### Fixed

- Bot identity customization no longer depends on setup-time bot naming that did not update identity files.
- Reduced drift between onboarding instructions and runtime behavior by centralizing question definitions.
- Setup no longer crashes when the default workspace path is not writable; it now falls back to `~/.yacb/agent-workspace/<assistant-slug>`.
- Skill installation during setup now handles permission errors gracefully and continues with warnings instead of aborting the wizard.

## [0.1.1] - 2026-02-17

### Added

- New short runtime lifecycle commands:
  - `uv run yacb start [config_path]`
  - `uv run yacb status`
  - `uv run yacb logs [-f|--follow]`
  - `uv run yacb stop`
- New setup alias: `uv run yacb init` (keeps `uv run yacb setup` working).
- Explicit foreground mode command: `uv run yacb run [config_path]`.
- CLI help entrypoint: `uv run yacb help`.
- Restored optional periodic security audit loop via `tools.security_audit.*`.

### Changed

- `uv run yacb` now starts the background service by default.
- `uv run yacb <config_path>` now starts the background service using that config path.
- Service process spawn now uses explicit foreground child mode to avoid CLI recursion.
- Updated docs (`SETUP.md`, `COMMANDS.md`) to reflect new command flow.
- `web_fetch` now surfaces prompt-injection signals in `security_warnings`.

### Fixed

- Service subcommands no longer trigger heavy runtime imports before command handling.
- `logs` command now handles missing log files cleanly.

## [0.1.0] - 2026-02-14

### Added

- Initial public release of yacb
- Multi-channel assistant runtime (Telegram, Discord, WhatsApp)
- Tooling for filesystem, shell, web, messaging, cron, and memory
- Smart model routing and heartbeat system

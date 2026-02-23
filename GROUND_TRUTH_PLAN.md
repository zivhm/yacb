# Ground Truth Plan

This document is the source of truth for the current YACB implementation scope.
Do not expand or reinterpret scope beyond what is written here.

Current status marker:
- Scope 1 is completed (implemented and validated on 2026-02-23).
- Treat this file as authoritative over ad-hoc summaries.

Latest validation:
- Regression suite run: `uv run python -m pytest -q`
- Result: `113 passed in 46.15s`

Scope 1 completion checklist:
- [x] Deterministic `tier_router` replaced `llm_router`.
- [x] Command surface migrated to `!tier <light|medium|heavy> <message>` with legacy migration hints.
- [x] Agent failover retries once with medium model on tier failure.
- [x] Router/config wiring updated (`TierRouterConfig`, `TierModelsConfig`, `TierRulesConfig`).
- [x] Runtime hardening shipped (bounded queues, direct queue awaits, provider api_base safety, SQLite pragmas).
- [x] Setup/docs/config updated for `tier_router`.
- [x] Scope 1 tests added and passing.

## YACB Lean Reliability Plan (Free Router, Billed Models)

### Summary

Replace the current LLM classifier router with a deterministic, zero-cost in-process tier router, then apply a small set of reliability/resource hardening changes that reduce moving parts and improve operational simplicity for single-user, 1-2 channel usage.

This plan is intentionally breaking where useful (per your preference), with minimal configurability and clear defaults.

### Scope

1. Replace `llm_router` with deterministic `tier_router`.
2. Keep model billing via your existing API keys/providers.
3. Improve runtime dependability with bounded queues, cleaner dispatch loops, safer provider behavior, and SQLite durability tuning.
4. Keep implementation small and maintainable.

### Public API / Interface Changes (Breaking)

1. Config schema:

- Remove `agents.<name>.llm_router`.
- Add `agents.<name>.tier_router` with fixed tier models and minimal rule knobs.

Proposed shape:

```yaml
agents:
  default:
    model: openai/gpt-4.1-mini   # medium/default model (unchanged field)
    tier_router:
      enabled: true
      tiers:
        light:
          model: openai/gpt-4.1-mini
        medium:
          model: openai/gpt-4.1-mini
        heavy:
          model: openai/gpt-4.1
      rules:
        short_message_max_chars: 80
        short_message_max_words: 12
        medium_keywords: ["search", "read", "explain", "remind", "cron", "file", "tool"]
        heavy_keywords: ["code", "debug", "refactor", "implement", "architecture", "optimize"]
```

2. Command surface:

- Remove `!light`, `!heavy`, `!think`.
- Add `!tier <light|medium|heavy> <message>` as the single manual override.
- Keep `!model` for model updates.

3. Setup/docs:

- Wizard and docs no longer present `llm_router`.
- Wizard emits `tier_router` defaults instead.

### Implementation Plan

1. Deterministic tier router

- Add new module `core/agent/tier_router.py`.
- Inputs: raw user text.
- Output: `(tier, cleaned_message, selected_model)`.
- Route order:
1. `!tier` override command prefix.
2. Heavy keyword match.
3. Medium keyword/tool-intent match.
4. Short-message heuristic -> light.
5. Default -> medium.

2. Agent loop integration

- Update `core/agent/loop.py`:
1. Remove `llm_router` dependency and calls.
2. Use `tier_router` per turn.
3. Implement failover policy: if chosen tier call errors, immediately retry once with medium model for that turn.
4. Keep existing provider fallback behavior beneath this (no new complexity).
5. Replace legacy tier override handling with `!tier`.

3. Router wiring and config

- Update `core/config.py`:
1. Remove `LLMRouterConfig`.
2. Add `TierRouterConfig` + nested `TierModelsConfig` + `TierRulesConfig`.

- Update `core/agent/router.py`:
1. Instantiate `TierRouter` and pass into `AgentLoop`.
2. Remove `LLMRouter` construction paths.

4. Runtime hardening (lean reliability set)

- Message bus:
1. Add bounded queue sizes in `core/bus/queue.py` (defaults: inbound 200, outbound 200).
2. Expose queue limits in config (minimal runtime section or fixed constants if keeping zero new knobs).

- Dispatchers:
1. Remove polling-with-timeout loops in `core/main.py`; await queue directly and rely on task cancellation for shutdown.

- Provider safety:
1. In `core/providers/litellm_provider.py`, stop mutating global `litellm.api_base`; keep per-request kwargs only.
2. Keep current retry classifier logic.

- SQLite reliability:
1. In `core/storage/db.py`, set pragmatic defaults on init: `journal_mode=WAL`, `synchronous=NORMAL`, `busy_timeout`.
2. Preserve current schema and behavior.

5. UX/docs/setup updates

- Update `core/channels/commands.py` command help text.
- Update `README.md`, `SETUP.md`, and default `config.yaml` to reflect the new router model and removed commands.
- Update setup wizard in `core/setup.py` to emit and validate `tier_router`.

### Test Cases and Scenarios

1. Router behavior

- New tests in `tests/test_tier_router.py`:
1. Heavy keyword routes to heavy.
2. Medium keyword routes to medium.
3. Short simple input routes to light.
4. Unknown input defaults to medium.
5. `!tier heavy` override strips prefix and routes heavy.

2. Agent failover

- Extend `tests/test_runtime_flows.py`:
1. Simulate tier model error -> immediate retry with medium model.
2. Confirm only one medium failover attempt per turn.

3. Command compatibility

- Extend tests:
1. `!light`/`!heavy` rejected with migration hint.
2. `!tier` accepted and routed.

4. Reliability hardening

- Queue bound tests:
1. Queue max size applied.
2. No message loss under normal burst within limits.

- SQLite init tests:
1. DB initializes with WAL and busy timeout.
2. Existing DB data unaffected.

5. Regression suite

- Run existing full suite and require no regressions in core message flow:
- `uv run python -m pytest -q`

### Rollout

1. Ship as one breaking minor release in your private flow (single user).
2. Start with one active channel for 24h soak.
3. Enable second channel after no routing/failover anomalies in logs.
4. Keep previous config file as backup only for rollback reference.

### Assumptions and Defaults

1. ClawRouter is not part of Phase 1 implementation.
2. Router logic must be free/open in-process; model calls remain billed by your configured provider keys.
3. Single-user deployment allows hard config/command breaks without migration layer.
4. Operational simplicity is the success gate: fewer moving parts, deterministic behavior, and straightforward debugging.

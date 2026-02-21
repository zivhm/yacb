# TOOLS.md - yacb Runtime Notes

This file is for local, operational notes that help the assistant run yacb well.
Keep it practical and current.

## Rules

- Keep entries short and actionable.
- Prefer stable aliases over raw IDs when possible.
- Never store secrets, tokens, or passwords here.
- Do not duplicate full config files; store references and high-signal notes.

## What Belongs Here

- Channel targets and human-friendly labels
- Routing conventions (`channel:chat_id -> agent`)
- Reminder defaults and escalation preferences
- Heartbeat delivery preferences
- High-value command shortcuts and known runtime quirks

## Template

### Agent + Workspace

- Primary agent: `default`
- Workspace: `agent-workspace/<agent>`
- Settings file: `agent-workspace/<agent>/settings.json`
- Memory files: `memory/MEMORY.md`, `memory/daily/YYYY-MM-DD.md`

### Channel Targets

- Telegram primary: `telegram:<chat_id>`
- Discord primary: `discord:<channel_or_user_id>`
- WhatsApp primary: `whatsapp:<jid>`
- Preferred proactive destination: `<channel:id>`

### Routing Notes

- Active route keys: `channel:chat_id -> agent`
- Group chats requiring mention-only behavior:
- Channels where reactions are preferred over messages:

### Reminder Defaults

- Default lead time:
- Quiet hours:
- Escalation order (if urgent):
- Recurring reminders require confirmation: yes/no

### Heartbeat Defaults

- `deliver_to`:
- Active hours:
- Suppress empty:
- Preferred checks (email/calendar/weather/etc):

### Model + Debug Ops

- Preferred default model/alias:
- `!model` conventions:
- Verbose toggle commands: `!toggle-verbose-logs`, `/toggle_verbose_logs`

### Known Quirks

- Add only issues that affect assistant behavior or reliability.

Update this file whenever behavior, routing, or delivery preferences change.

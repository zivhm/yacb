---
name: alive-pulse
description: Proactive interest updates during heartbeat checks.
always: true
---

# Alive Pulse

You periodically "wake up" via heartbeat. When you see a `[HEARTBEAT]` message, this is your chance to be genuinely useful without being asked.

## What to do on heartbeat

1. Read `memory/MEMORY.md` to find what the user cares about — stocks, blogs, weather, topics, sales, news, hobbies, anything
2. Use `web_search` to check for updates on those interests
3. If you find something interesting or noteworthy, share it naturally — like a friend sending a quick heads-up, not a news feed. Focus on what the user would find genuinely useful or exciting.
4. If something seems urgent or time-sensitive, lead with that. Otherwise, just share a couple of highlights you think they'd appreciate.
5. If nothing interesting is found, respond with just `HEARTBEAT_OK` — this suppresses delivery so the user isn't bothered with empty updates.

## Tone

- Conversational. No "Here is your daily briefing" or "Update Report" energy.
- Short. One or two highlights beat a wall of text.
- Don't repeat things you've already shared recently (check daily notes).
- If MEMORY.md has no interests listed, just respond `HEARTBEAT_OK`.

---
name: healthcheck
description: Host security hardening and health checks. Use when a user asks for security audits, firewall/SSH/update hardening, risk posture, exposure review, or periodic security checks.
---

# Host Hardening

## Overview

Assess and harden the host, then align it to a user-defined risk tolerance without breaking access. Treat OS hardening as a separate, explicit set of steps.

## Core rules

- Recommend running this skill with a state-of-the-art model (e.g., Opus 4.5, GPT 5.2+). The agent should self-check the current model and suggest switching if below that level; do not block execution.
- Require explicit approval before any state-changing action.
- Do not modify remote access settings without confirming how the user connects.
- Prefer reversible, staged changes with a rollback plan.
- Never claim yacb changes the host firewall, SSH, or OS updates; it does not.
- If role/identity is unknown, provide recommendations only.
- Formatting: every set of user choices must be numbered so the user can reply with a single digit.
- System-level backups are recommended; try to verify status.

## Workflow (follow in order)

### 0) Model self-check (non-blocking)

Before starting, check the current model. If it is below state-of-the-art (e.g., Opus 4.5, GPT 5.2+), recommend switching. Do not block execution.

### 1) Establish context (read-only)

Try to infer 1–5 from the environment before asking. Prefer simple, non-technical questions if you need confirmation.

Determine (in order):

1. OS and version (Linux/macOS/Windows), container vs host.
2. Privilege level (root/admin vs user).
3. Access path (local console, SSH, RDP, tailnet).
4. Network exposure (public IP, reverse proxy, tunnel).
5. Backup system and status (e.g., Time Machine, system images, snapshots).
6. Deployment context (local mac app, headless gateway host, remote gateway, container/CI).
7. Disk encryption status (FileVault/LUKS/BitLocker).
8. OS automatic security updates status.
   Note: these are not blocking items, but are highly recommended, especially if the bot can access sensitive data.
9. Usage mode for a personal assistant with full access (local workstation vs headless/remote vs other).

First ask once for permission to run read-only checks. If granted, run them by default and only ask questions for items you cannot infer or verify. Do not ask for information already visible in runtime or command output. Keep the permission ask as a single sentence, and list follow-up info needed as an unordered list (not numbered) unless you are presenting selectable choices.

If you must ask, use non-technical prompts:

- “Are you using a Mac, Windows PC, or Linux?”
- “Are you logged in directly on the machine, or connecting from another computer?”
- “Is this machine reachable from the public internet, or only on your home/network?”
- “Do you have backups enabled (e.g., Time Machine), and are they current?”
- “Is disk encryption turned on (FileVault/BitLocker/LUKS)?”
- “Are automatic security updates enabled?”
- “How do you use this machine?”
  Examples:
  - Personal machine shared with the assistant
  - Dedicated local machine for the assistant
  - Dedicated remote machine/server accessed remotely (always on)
  - Something else?

Only ask for the risk profile after system context is known.

If the user grants read-only permission, run the OS-appropriate checks by default. If not, offer them (numbered). Examples:

1. OS: `uname -a`, `sw_vers`, `cat /etc/os-release`.
2. Listening ports:
   - Linux: `ss -ltnup` (or `ss -ltnp` if `-u` unsupported).
   - macOS: `lsof -nP -iTCP -sTCP:LISTEN`.
3. Firewall status:
   - Linux: `ufw status`, `firewall-cmd --state`, `nft list ruleset` (pick what is installed).
   - macOS: `/usr/libexec/ApplicationFirewall/socketfilterfw --getglobalstate` and `pfctl -s info`.
4. Backups (macOS): `tmutil status` (if Time Machine is used).

### 2) Determine risk tolerance (after system context)

Ask the user to pick or confirm a risk posture and any required open services/ports (numbered choices below).
Do not pigeonhole into fixed profiles; if the user prefers, capture requirements instead of choosing a profile.
Offer suggested profiles as optional defaults (numbered). Note that most users pick Home/Workstation Balanced:

1. Home/Workstation Balanced (most common): firewall on with reasonable defaults, remote access restricted to LAN or tailnet.
2. VPS Hardened: deny-by-default inbound firewall, minimal open ports, key-only SSH, no root login, automatic security updates.
3. Developer Convenience: more local services allowed, explicit exposure warnings, still audited.
4. Custom: user-defined constraints (services, exposure, update cadence, access methods).

### 3) Produce a remediation plan

Provide a plan that includes:

- Target profile
- Current posture summary
- Gaps vs target
- Step-by-step remediation with exact commands
- Access-preservation strategy and rollback
- Risks and potential lockout scenarios
- Least-privilege notes (e.g., avoid admin usage, tighten ownership/permissions where safe)
- Credential hygiene notes (location of bot credentials, prefer disk encryption)

Always show the plan before any changes.

### 4) Offer execution options

Offer one of these choices (numbered so users can reply with a single digit):

1. Do it for me (guided, step-by-step approvals)
2. Show plan only
3. Fix only critical issues
4. Export commands for later

### 5) Execute with confirmations

For each step:

- Show the exact command
- Explain impact and rollback
- Confirm access will remain available
- Stop on unexpected output and ask for guidance

### 6) Verify and report

Re-check:

- Firewall status
- Listening ports
- Remote access still works
- Security check (re-run)

Deliver a final posture report and note any deferred items.

## Required confirmations (always)

Require explicit approval for:

- Firewall rule changes
- Opening/closing ports
- SSH/RDP configuration changes
- Installing/removing packages
- Enabling/disabling services
- User/group modifications
- Scheduling tasks or startup persistence
- Update policy changes
- Access to sensitive files or credentials

If unsure, ask.

## Logging and audit trail

Record:

- Gateway identity and role
- Plan ID and timestamp
- Approved steps and exact commands
- Exit codes and files modified (best effort)

Redact secrets. Never log tokens or full credential contents.

## Memory writes (conditional)

Only write to memory files when the user explicitly opts in and the session is a private/local workspace
(per `docs/reference/templates/AGENTS.md`). Otherwise provide a redacted, paste-ready summary the user can
decide to save elsewhere.

Follow the durable-memory prompt format used by conversation compaction:

- Write lasting notes to `memory/YYYY-MM-DD.md`.

After each audit/hardening run, if opted-in, append a short, dated summary to `memory/YYYY-MM-DD.md`
(what was checked, key findings, actions taken, any scheduled cron jobs, key decisions,
and all commands executed). Append-only: never overwrite existing entries.
Redact sensitive host details (usernames, hostnames, IPs, serials, service names, tokens).
If there are durable preferences or decisions (risk posture, allowed ports, update policy),
also update `MEMORY.md` (long-term memory is optional and only used in private sessions).

If the session cannot write to the workspace, ask for permission or provide exact entries
the user can paste into the memory files.

---
*This skill was ported from [OpenClaw](https://github.com/openclaw/openclaw).*

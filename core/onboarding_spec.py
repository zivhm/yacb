"""Shared first-run onboarding question spec."""

ONBOARDING_QUESTIONS: list[tuple[str, str]] = [
    ("user_name", "What should I call you?"),
    ("assistant_name", "What should my display name be in chat? (default: yacb)"),
    ("response_style", "Pick your default response style: very brief / balanced / detailed."),
    ("directness", "How direct should I be when you are likely wrong? soft / direct / very direct."),
    ("decision_style", "Do you want one recommendation first, or options with tradeoffs?"),
    ("proactivity", "How proactive should I be with reminders and nudges? quiet / moderate / high-touch."),
    ("tone_constraints", "Any tone constraints? (examples: no sarcasm, no emojis, formal only)"),
]

#!/usr/bin/env python3
"""Compatibility wrapper for the runtime monitor CLI."""

import sys
from pathlib import Path


def _main() -> int:
    # Support direct execution: python3 scripts/runtime_monitor.py
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from core.runtime_monitor import main as runtime_monitor_main

    return runtime_monitor_main()


if __name__ == "__main__":
    raise SystemExit(_main())

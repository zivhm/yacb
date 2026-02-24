"""Simple runtime monitor for yacb processes (Linux/Pi friendly).

Samples process-level CPU and memory over time and writes aggregate rows to CSV.
Designed for multi-hour/day soak tests without extra dependencies.
"""

from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class ProcSample:
    pid: int
    cpu_pct: float
    rss_kb: int


def _is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _pid_from_file(path: Path) -> int | None:
    if not path.exists():
        return None
    try:
        value = path.read_text(encoding="utf-8").strip()
        pid = int(value)
        if pid > 0 and _is_running(pid):
            return pid
    except Exception:
        return None
    return None


def _pids_from_pattern(pattern: str) -> list[int]:
    try:
        result = subprocess.run(
            ["pgrep", "-f", pattern],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return []
        pids: list[int] = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                pids.append(int(line))
            except ValueError:
                continue
        return pids
    except FileNotFoundError:
        # Fallback when pgrep is unavailable.
        result = subprocess.run(
            ["ps", "-eo", "pid=,args="],
            capture_output=True,
            text=True,
            check=False,
        )
        pids: list[int] = []
        for line in result.stdout.splitlines():
            if pattern not in line:
                continue
            parts = line.strip().split(None, 1)
            if not parts:
                continue
            try:
                pids.append(int(parts[0]))
            except ValueError:
                continue
        return pids


def _sample_pid(pid: int) -> ProcSample | None:
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "pid=,%cpu=,rss="],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    line = result.stdout.strip()
    if not line:
        return None
    parts = line.split()
    if len(parts) < 3:
        return None
    try:
        parsed_pid = int(parts[0])
        cpu_pct = float(parts[1])
        rss_kb = int(parts[2])
    except ValueError:
        return None
    return ProcSample(pid=parsed_pid, cpu_pct=cpu_pct, rss_kb=rss_kb)


def _mem_available_kb() -> int | None:
    meminfo = Path("/proc/meminfo")
    if not meminfo.exists():
        return None
    for line in meminfo.read_text(encoding="utf-8").splitlines():
        if line.startswith("MemAvailable:"):
            parts = line.split()
            if len(parts) >= 2:
                try:
                    return int(parts[1])
                except ValueError:
                    return None
    return None


def _mem_total_kb() -> int | None:
    meminfo = Path("/proc/meminfo")
    if not meminfo.exists():
        return None
    for line in meminfo.read_text(encoding="utf-8").splitlines():
        if line.startswith("MemTotal:"):
            parts = line.split()
            if len(parts) >= 2:
                try:
                    return int(parts[1])
                except ValueError:
                    return None
    return None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Monitor yacb runtime process resources and write CSV samples."
    )
    parser.add_argument(
        "--pid-file",
        default=".yacb/service.pid",
        help="Optional PID file to include (default: .yacb/service.pid).",
    )
    parser.add_argument(
        "--pattern",
        default="core.main run",
        help="Process pattern for discovery with pgrep -f (default: 'core.main run').",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=10.0,
        help="Sampling interval in seconds (default: 10).",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=None,
        help="Total duration in seconds (overrides --hours).",
    )
    parser.add_argument(
        "--hours",
        type=float,
        default=24.0,
        help="Total duration in hours when --duration is not provided (default: 24).",
    )
    parser.add_argument(
        "--output",
        default=".yacb/runtime-monitor.csv",
        help="Output CSV path (default: .yacb/runtime-monitor.csv).",
    )
    return parser.parse_args()


def main() -> int:
    if sys.platform == "win32":
        print("yacb-monitor is intended for Linux/Pi hosts.", file=sys.stderr)
        return 2

    args = parse_args()
    if args.interval <= 0:
        print("--interval must be > 0", file=sys.stderr)
        return 2
    if args.duration is not None and args.duration <= 0:
        print("--duration must be > 0", file=sys.stderr)
        return 2
    if args.hours <= 0:
        print("--hours must be > 0", file=sys.stderr)
        return 2

    duration_seconds = args.duration if args.duration is not None else int(args.hours * 3600)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    header = [
        "timestamp_utc",
        "up",
        "pid_count",
        "pids",
        "total_cpu_pct",
        "total_rss_mb",
        "max_rss_mb",
        "mem_available_mb",
        "mem_available_pct",
    ]

    write_header = not out_path.exists() or out_path.stat().st_size == 0
    with out_path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(header)

        pid_file_path = Path(args.pid_file)
        deadline = time.time() + duration_seconds
        sample_count = 0
        up_count = 0

        while time.time() < deadline:
            pids = set(_pids_from_pattern(args.pattern))
            pid_from_file = _pid_from_file(pid_file_path)
            if pid_from_file:
                pids.add(pid_from_file)

            samples: list[ProcSample] = []
            for pid in sorted(pids):
                sample = _sample_pid(pid)
                if sample:
                    samples.append(sample)

            up = 1 if samples else 0
            sample_count += 1
            up_count += up

            total_cpu = round(sum(s.cpu_pct for s in samples), 2)
            total_rss_kb = sum(s.rss_kb for s in samples)
            max_rss_kb = max((s.rss_kb for s in samples), default=0)
            mem_available_kb = _mem_available_kb()
            mem_total_kb = _mem_total_kb()
            mem_available_pct = ""
            if mem_available_kb is not None and mem_total_kb:
                mem_available_pct = round((mem_available_kb / mem_total_kb) * 100.0, 2)

            writer.writerow(
                [
                    _utc_now(),
                    up,
                    len(samples),
                    " ".join(str(s.pid) for s in samples),
                    total_cpu,
                    round(total_rss_kb / 1024.0, 2),
                    round(max_rss_kb / 1024.0, 2),
                    "" if mem_available_kb is None else round(mem_available_kb / 1024.0, 2),
                    mem_available_pct,
                ]
            )
            f.flush()
            time.sleep(args.interval)

    uptime_pct = round((up_count / sample_count) * 100.0, 2) if sample_count else 0.0
    print(f"Wrote {sample_count} samples to {out_path}")
    print(f"Runtime up in {up_count}/{sample_count} samples ({uptime_pct}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

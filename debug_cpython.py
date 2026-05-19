#!/usr/bin/env python3
"""
Debug helper around cpython.py.

Runs `cpython.py ARGS...` with watchdog (timeout + periodic SIGUSR1 traceback
dump), captures stdout/stderr, and prints a structured summary -- so we can
quickly see where the interpretation hangs or fails without typing the same
arguments every time.

Typical usage during development::

    ./debug_cpython.py                              # default: -c "print('hi')"
    ./debug_cpython.py -c "1+1"                     # forward Python args
    ./debug_cpython.py --timeout 60 --interval 5    # longer watchdog
    ./debug_cpython.py --no-traceback               # only timeout, no SIGUSR1
    ./debug_cpython.py --tail 80                    # show last N lines only

The script intentionally takes no Python-side configuration -- it just forwards
to `cpython.py`.  It's small enough to live at the repo root next to the other
top-level scripts.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
CPYTHON_PY = REPO_ROOT / "cpython.py"


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Run cpython.py under the watchdog and report where it hangs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--timeout", type=int, default=30,
        help="Watchdog timeout in seconds (default 30).")
    p.add_argument(
        "--interval", type=int, default=4,
        help="SIGUSR1 traceback interval in seconds (default 4). "
             "Set to 0 to disable periodic tracebacks.")
    p.add_argument(
        "--no-traceback", action="store_true",
        help="Shortcut for --interval 0.")
    p.add_argument(
        "--tail", type=int, default=0,
        help="Only print the last N lines of output (default 0 = print all).")
    p.add_argument(
        "--python", default=sys.executable,
        help="Python interpreter to run cpython.py with (default: %(default)s).")
    p.add_argument(
        "cpython_args", nargs=argparse.REMAINDER,
        help="Arguments to forward to cpython.py. If empty, defaults to "
             "[-c, 'print(\"hi\")'].")
    return p.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    interval = 0 if args.no_traceback else args.interval

    fwd: list[str] = list(args.cpython_args)
    # argparse.REMAINDER swallows a leading "--"; strip it for cleanliness.
    if fwd and fwd[0] == "--":
        fwd = fwd[1:]
    if not fwd:
        fwd = ["-c", "print('hi')"]

    cmd: list[str] = [
        args.python, "-u", str(CPYTHON_PY),
        f"--watchdog-timeout={args.timeout}",
    ]
    if interval > 0:
        cmd.append(f"--watchdog-report-traceback-interval={interval}")
    cmd += fwd

    print("[debug_cpython] running: %s" % " ".join(cmd), flush=True)
    # A small extra buffer over the watchdog so the watchdog gets to print
    # its own message instead of us SIGTERMing it first.
    hard_timeout = args.timeout + 10

    try:
        proc = subprocess.run(
            cmd, cwd=REPO_ROOT,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=hard_timeout, text=True,
        )
        out = proc.stdout or ""
        rc = proc.returncode
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or b"").decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        rc = -1
        out += f"\n[debug_cpython] hard timeout {hard_timeout}s exceeded; subprocess killed.\n"

    lines = out.splitlines()
    if args.tail > 0 and len(lines) > args.tail:
        print(f"[debug_cpython] (omitting {len(lines) - args.tail} earlier lines; --tail {args.tail})")
        lines = lines[-args.tail:]
    for ln in lines:
        print(ln)

    print(f"[debug_cpython] exit code: {rc}", flush=True)
    return 0 if rc == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

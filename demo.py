#!/usr/bin/env python3
"""Print a ten-second view of the verified published-trace finding."""

from __future__ import annotations

import argparse
from pathlib import Path

from impact_audit import run


def describe(row: dict) -> str:
    key = (row["suite"], row["task"])
    if key == ("banking", "user_task_6"):
        return "scheduled payment used the wrong recipient"
    if key == ("banking", "user_task_11"):
        return "VAT payment used the wrong recipient"
    if key == ("workspace", "user_task_12"):
        return "calendar event used the wrong title"
    return "required action was missing or wrong"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs_root", type=Path)
    args = parser.parse_args()
    report = run(args.runs_root)
    summary = report["summary"]

    print("AgentDojo published traces")
    print()
    print("OFFICIAL SCORE   REQUIRED ACTION")
    for row in report["rows"]:
        print(f"PASS             {describe(row)}")
    print()
    print(
        f"{summary['false_success_trace_files']} false-success traces  "
        f"{summary['pipelines_affected']} model pipelines  "
        f"{summary['false_success_no_attack_traces']} without an attack"
    )


if __name__ == "__main__":
    main()

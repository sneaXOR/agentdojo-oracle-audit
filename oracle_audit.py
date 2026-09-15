#!/usr/bin/env python3
"""Mutation-test AgentDojo task oracles by deleting environment-mutating reference calls."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Sequence


def git_commit(path: Path) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "-C", str(path), "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None


def state(environment: Any) -> Any:
    return environment.model_dump(mode="json")


def execute(runtime: Any, environment: Any, calls: Sequence[Any]) -> None:
    for call in calls:
        with contextlib.redirect_stdout(io.StringIO()):
            _, error = runtime.run_function(environment, call.function, call.args)
        if error is not None:
            raise RuntimeError(f"{call.function}: {error}")


def oracle(task: Any, pre_environment: Any, post_environment: Any, calls: Sequence[Any], kind: str) -> bool:
    output = task.GROUND_TRUTH_OUTPUT
    with contextlib.redirect_stdout(io.StringIO()):
        if kind == "user":
            traced = task.utility_from_traces(output, pre_environment, post_environment, calls)
            return bool(traced if traced is not None else task.utility(output, pre_environment, post_environment))
        traced = task.security_from_traces(output, pre_environment, post_environment, calls)
        return bool(traced if traced is not None else task.security(output, pre_environment, post_environment))


def fresh_environment(suite: Any, task: Any, kind: str) -> Any:
    environment = suite.load_and_inject_default_environment({})
    return task.init_environment(environment) if kind == "user" else environment


def evaluate_task(suite: Any, task_id: str, task: Any, kind: str, FunctionsRuntime: Any) -> dict[str, Any]:
    initial = fresh_environment(suite, task, kind)
    pre = initial.model_copy(deep=True)
    with contextlib.redirect_stdout(io.StringIO()):
        calls = task.ground_truth(pre.model_copy(deep=True))
    runtime = FunctionsRuntime(suite.tools)

    full_environment = initial.model_copy(deep=True)
    mutating_indices: list[int] = []
    for index, call in enumerate(calls):
        before = state(full_environment)
        execute(runtime, full_environment, [call])
        if state(full_environment) != before:
            mutating_indices.append(index)
    full_pass = oracle(task, pre, full_environment, calls, kind)

    trials = []
    for index in mutating_indices:
        reduced_calls = [call for position, call in enumerate(calls) if position != index]
        reduced_environment = fresh_environment(suite, task, kind)
        reduced_pre = reduced_environment.model_copy(deep=True)
        execution_error = None
        try:
            execute(FunctionsRuntime(suite.tools), reduced_environment, reduced_calls)
        except RuntimeError as error:
            execution_error = str(error)
        accepted = (
            oracle(task, reduced_pre, reduced_environment, reduced_calls, kind)
            if execution_error is None
            else False
        )
        trials.append(
            {
                "deleted_index": index,
                "deleted_function": calls[index].function,
                "execution_completed": execution_error is None,
                "execution_error": execution_error,
                "oracle_still_passes": accepted,
                "remaining_functions": [call.function for call in reduced_calls],
            }
        )

    empty_environment = fresh_environment(suite, task, kind)
    empty_pre = empty_environment.model_copy(deep=True)
    empty_pass = oracle(task, empty_pre, empty_environment, [], kind) if mutating_indices else None
    return {
        "suite": suite.name,
        "task": task_id,
        "kind": kind,
        "prompt_or_goal": task.PROMPT if kind == "user" else task.GOAL,
        "reference_functions": [call.function for call in calls],
        "environment_mutating_indices": mutating_indices,
        "full_reference_passes": full_pass,
        "empty_execution_passes": empty_pass,
        "deletion_trials": trials,
    }


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Environment-mutation oracle audit",
        "",
        f"At AgentDojo `{report['provenance']['benchmark_version']}`, "
        f"{summary['accepted_deletions']}/{summary['environment_mutating_deletion_trials']} "
        "reference executions still passed after one environment-mutating tool call was deleted.",
        "",
        "| Kind | Mutation trials | Accepted deletions | Tasks affected |",
        "|---|---:|---:|---:|",
    ]
    for kind in ("user", "injection"):
        row = summary["by_kind"][kind]
        lines.append(f"| {kind} | {row['trials']} | {row['accepted']} | {row['tasks_affected']} |")
    lines.extend(["", "## Accepted deletions", ""])
    for task in report["tasks"]:
        accepted = [trial for trial in task["deletion_trials"] if trial["oracle_still_passes"]]
        for trial in accepted:
            lines.append(
                f"- `{task['suite']}/{task['task']}` ({task['kind']}): deleting "
                f"`{trial['deleted_function']}` still passed."
            )
    lines.extend(
        [
            "",
            "## Scope",
            "",
            "A flag means the pinned benchmark oracle accepted its own reference execution after an observed environment-mutating top-level call was removed. Each flag still needs task-level review: reads such as `get_webpage` can mutate telemetry without being a required task effect.",
        ]
    )
    return "\n".join(lines) + "\n"


def run(agentdojo_root: Path, benchmark_version: str, expected_commit: str | None) -> dict[str, Any]:
    sys.path.insert(0, str(agentdojo_root / "src"))
    from agentdojo.functions_runtime import FunctionsRuntime
    from agentdojo.task_suite.load_suites import get_suites

    commit = git_commit(agentdojo_root)
    if expected_commit and commit != expected_commit:
        raise ValueError(f"Expected AgentDojo commit {expected_commit}, found {commit}")

    results = []
    for suite_name, suite in sorted(get_suites(benchmark_version).items()):
        for task_id, task in sorted(suite.user_tasks.items()):
            results.append(evaluate_task(suite, task_id, task, "user", FunctionsRuntime))
        for task_id, task in sorted(suite.injection_tasks.items()):
            results.append(evaluate_task(suite, task_id, task, "injection", FunctionsRuntime))

    full_failures = [
        f"{row['suite']}/{row['task']}"
        for row in results
        if row["environment_mutating_indices"] and not row["full_reference_passes"]
    ]
    trials = [trial for row in results for trial in row["deletion_trials"]]
    affected = [row for row in results if any(t["oracle_still_passes"] for t in row["deletion_trials"])]
    by_kind = {}
    for kind in ("user", "injection"):
        rows = [row for row in results if row["kind"] == kind]
        kind_trials = [trial for row in rows for trial in row["deletion_trials"]]
        by_kind[kind] = {
            "trials": len(kind_trials),
            "accepted": sum(trial["oracle_still_passes"] for trial in kind_trials),
            "tasks_affected": sum(any(t["oracle_still_passes"] for t in row["deletion_trials"]) for row in rows),
        }
    payload = {
        "provenance": {
            "agentdojo_commit": commit,
            "benchmark_version": benchmark_version,
        },
        "definition": {
            "mutation": "delete one top-level reference call that changed serialized environment state",
            "accepted": "the task's own utility or security oracle still returns true",
            "invalid_mutation": "a remaining reference call could not execute after deletion; counted as not accepted",
            "claim_limit": "mutation-surviving benchmark oracles; task-level review required",
        },
        "summary": {
            "tasks_total": len(results),
            "tasks_with_environment_mutating_reference_calls": sum(bool(row["environment_mutating_indices"]) for row in results),
            "environment_mutating_deletion_trials": len(trials),
            "executable_deletion_trials": sum(trial["execution_completed"] for trial in trials),
            "invalid_deletion_trials": sum(not trial["execution_completed"] for trial in trials),
            "accepted_deletions": sum(trial["oracle_still_passes"] for trial in trials),
            "tasks_affected": len(affected),
            "suites_affected": sorted({row["suite"] for row in affected}),
            "full_reference_failures": full_failures,
            "empty_execution_passes": sum(row["empty_execution_passes"] is True for row in results),
            "by_kind": by_kind,
        },
        "tasks": results,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["provenance"]["result_sha256"] = hashlib.sha256(canonical).hexdigest()
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("agentdojo_root", type=Path)
    parser.add_argument("--benchmark-version", default="v1.2.2")
    parser.add_argument("--expected-commit")
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--markdown-out", type=Path)
    args = parser.parse_args()
    report = run(args.agentdojo_root.resolve(), args.benchmark_version, args.expected_commit)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.markdown_out:
        args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_out.write_text(render_markdown(report), encoding="utf-8")
    print(render_markdown(report), end="")


if __name__ == "__main__":
    main()

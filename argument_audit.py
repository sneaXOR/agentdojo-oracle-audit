#!/usr/bin/env python3
"""Mutation-test AgentDojo task oracles by changing arguments of environment-mutating calls."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Sequence

from oracle_audit import execute, fresh_environment, git_commit, oracle, state


DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def replacement(value: Any) -> Any:
    """Return one deterministic, type-valid but materially different value."""
    if isinstance(value, bool):
        return not value
    if isinstance(value, int):
        return value + 1
    if isinstance(value, float):
        return value + 1.0
    if isinstance(value, str):
        if DATE.fullmatch(value):
            return "2099-12-31" if value != "2099-12-31" else "2098-12-31"
        if "@" in value:
            return "oracle-mutation@example.com"
        if value.startswith(("http://", "https://")):
            return "https://oracle-mutation.invalid/"
        return "__oracle_mutation__"
    if value is None:
        return "__oracle_mutation__"
    if isinstance(value, list):
        return [] if value else ["__oracle_mutation__"]
    if isinstance(value, dict):
        return {} if value else {"oracle_mutation": True}
    raise TypeError(f"Unsupported argument type: {type(value)!r}")


def evaluate_task(suite: Any, task_id: str, task: Any, kind: str, FunctionsRuntime: Any) -> dict[str, Any]:
    initial = fresh_environment(suite, task, kind)
    pre = initial.model_copy(deep=True)
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
        for argument, original in calls[index].args.items():
            mutated = replacement(original)
            mutated_args = dict(calls[index].args)
            mutated_args[argument] = mutated
            mutated_calls = list(calls)
            mutated_calls[index] = calls[index].model_copy(update={"args": mutated_args})
            mutated_environment = fresh_environment(suite, task, kind)
            mutated_pre = mutated_environment.model_copy(deep=True)
            execution_error = None
            try:
                execute(FunctionsRuntime(suite.tools), mutated_environment, mutated_calls)
            except RuntimeError as error:
                execution_error = str(error)
            accepted = (
                oracle(task, mutated_pre, mutated_environment, mutated_calls, kind)
                if execution_error is None
                else False
            )
            trials.append(
                {
                    "call_index": index,
                    "function": calls[index].function,
                    "argument": argument,
                    "original": original,
                    "mutated": mutated,
                    "execution_completed": execution_error is None,
                    "execution_error": execution_error,
                    "oracle_still_passes": accepted,
                }
            )

    return {
        "suite": suite.name,
        "task": task_id,
        "kind": kind,
        "prompt_or_goal": task.PROMPT if kind == "user" else task.GOAL,
        "reference_functions": [call.function for call in calls],
        "environment_mutating_indices": mutating_indices,
        "full_reference_passes": full_pass,
        "argument_trials": trials,
    }


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Action-argument oracle audit",
        "",
        f"At AgentDojo `{report['provenance']['benchmark_version']}`, "
        f"{summary['accepted_mutations']}/{summary['argument_mutation_trials']} "
        "single-argument mutations still passed the task oracle.",
        "",
        "| Kind | Argument trials | Executable | Accepted | Tasks affected |",
        "|---|---:|---:|---:|---:|",
    ]
    for kind in ("user", "injection"):
        row = summary["by_kind"][kind]
        lines.append(
            f"| {kind} | {row['trials']} | {row['executable']} | {row['accepted']} | {row['tasks_affected']} |"
        )
    lines.extend(["", "## Mutation-surviving arguments", ""])
    for task in report["tasks"]:
        for trial in task["argument_trials"]:
            if trial["oracle_still_passes"]:
                lines.append(
                    f"- `{task['suite']}/{task['task']}` ({task['kind']}), `{trial['function']}.{trial['argument']}`: "
                    f"`{trial['original']}` -> `{trial['mutated']}`."
                )
    lines.extend(
        [
            "",
            "## Scope",
            "",
            "A flag means the task oracle accepted a fully executed reference sequence after one argument of an observed environment-mutating call was changed. Some arguments may be intentionally unconstrained; every flag requires task-level review.",
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
    for _, suite in sorted(get_suites(benchmark_version).items()):
        for task_id, task in sorted(suite.user_tasks.items()):
            results.append(evaluate_task(suite, task_id, task, "user", FunctionsRuntime))
        for task_id, task in sorted(suite.injection_tasks.items()):
            results.append(evaluate_task(suite, task_id, task, "injection", FunctionsRuntime))

    relevant = [row for row in results if row["environment_mutating_indices"]]
    full_failures = [f"{row['suite']}/{row['task']}" for row in relevant if not row["full_reference_passes"]]
    trials = [trial for row in relevant for trial in row["argument_trials"]]
    affected = [row for row in relevant if any(t["oracle_still_passes"] for t in row["argument_trials"])]
    by_kind = {}
    for kind in ("user", "injection"):
        rows = [row for row in relevant if row["kind"] == kind]
        kind_trials = [trial for row in rows for trial in row["argument_trials"]]
        by_kind[kind] = {
            "trials": len(kind_trials),
            "executable": sum(t["execution_completed"] for t in kind_trials),
            "accepted": sum(t["oracle_still_passes"] for t in kind_trials),
            "tasks_affected": sum(any(t["oracle_still_passes"] for t in row["argument_trials"]) for row in rows),
        }
    payload = {
        "provenance": {"agentdojo_commit": commit, "benchmark_version": benchmark_version},
        "definition": {
            "mutation": "replace one argument of an environment-mutating reference call with a deterministic different value",
            "accepted": "the task's own utility or security oracle still returns true",
            "claim_limit": "mutation-surviving arguments; task-level review required",
        },
        "summary": {
            "tasks_total": len(results),
            "tasks_with_environment_mutating_reference_calls": len(relevant),
            "argument_mutation_trials": len(trials),
            "executable_mutation_trials": sum(t["execution_completed"] for t in trials),
            "invalid_mutation_trials": sum(not t["execution_completed"] for t in trials),
            "accepted_mutations": sum(t["oracle_still_passes"] for t in trials),
            "tasks_affected": len(affected),
            "full_reference_failures": full_failures,
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

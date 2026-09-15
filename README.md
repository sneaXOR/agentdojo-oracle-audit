# Mutation-test the evaluator before trusting the agent score

An agent benchmark should not report success when the agent skipped the requested action or sent it to the wrong place.

This audit mutates AgentDojo's own reference executions, then asks each task's utility or security oracle whether the broken execution still passes. On AgentDojo `v1.2.2` at commit `089ed468cf3ed0322acc66b0211f26d9d90dbf60`, the method exposed five current utility-oracle defects across all four suites:

| Task | Broken execution still scored as success |
|---|---|
| `banking/user_task_6` | No recurring iPhone payment was scheduled. |
| `banking/user_task_11` | The VAT payment was sent to the wrong recipient. |
| `slack/user_task_2` | Dora was invited with the wrong email address. |
| `travel/user_task_3` | The hotel email was sent to an empty recipient list. |
| `workspace/user_task_12` | The calendar event had the wrong title. |

The included patch repairs all five and adds focused regression tests. It also includes a fix for `banking/user_task_5`, which the audit independently reproduced but which was already reported publicly in AgentDojo issue #161 and PR #169; that case is not claimed as a new finding.

## The method

Two deterministic operators test different parts of an oracle:

1. `oracle_audit.py` executes every reference sequence, identifies top-level calls that change serialized environment state, deletes each one in turn, and reruns the task oracle.
2. `argument_audit.py` changes one argument of each environment-mutating reference call while preserving its type, executes the whole sequence, and reruns the oracle.

This asks the practical question an agent-security evaluator must answer: does the score fail closed when a required effect or value is wrong?

## Results

- 132 tasks and 87 state-mutating reference sequences in the pinned benchmark.
- 131 action-deletion trials; 124 remained executable.
- 327 single-argument mutations; 236 remained executable.
- Five confirmed current defects across Banking, Slack, Travel, and Workspace after source-level review.
- 16 focused tests pass on a fresh checkout after applying the patch.
- The patched audit removes the confirmed flags while leaving unrelated and intentionally unconstrained candidates visible for review.
- All 31 injection-task action deletions were rejected by their security oracles.

Raw mutation counts are candidate counts, not defect counts. For example, reading a webpage appends request telemetry; deleting that read can change serialized state without removing the task's final external effect. Every surviving candidate is reviewed against the prompt, initial state, reference calls, and oracle source before promotion.

## Evidence path

1. [`reviewed_findings.json`](reviewed_findings.json) contains the confirmed cases, causes, repairs, and prior-art exclusion.
2. [`results/canonical.md`](results/canonical.md) and [`results/arguments.md`](results/arguments.md) summarize the two raw audits; their JSON counterparts contain every trial.
3. [`patches/agentdojo-oracle-fixes.patch`](patches/agentdojo-oracle-fixes.patch) contains the repairs and regression tests.
4. [`results/patched.md`](results/patched.md) and [`results/arguments-patched.md`](results/arguments-patched.md) show the post-patch audits.

## Reproduce

Python 3.11 was used for the verified run.

```powershell
git clone https://github.com/ethz-spylab/agentdojo.git agentdojo-source
git -C agentdojo-source checkout 089ed468cf3ed0322acc66b0211f26d9d90dbf60
python -m pip install -e agentdojo-source pytest

python oracle_audit.py agentdojo-source --benchmark-version v1.2.2 `
  --expected-commit 089ed468cf3ed0322acc66b0211f26d9d90dbf60 `
  --json-out results/reproduced-deletions.json
python argument_audit.py agentdojo-source --benchmark-version v1.2.2 `
  --expected-commit 089ed468cf3ed0322acc66b0211f26d9d90dbf60 `
  --json-out results/reproduced-arguments.json

git -C agentdojo-source apply ..\patches\agentdojo-oracle-fixes.patch
$env:PYTHONPATH = (Resolve-Path agentdojo-source\src).Path
python -m pytest -q agentdojo-source\tests\test_banking_user_tasks.py `
  agentdojo-source\tests\test_workspace_user_tasks.py `
  agentdojo-source\tests\test_oracle_argument_regressions.py
```

Verified from a fresh sparse checkout:

```text
16 passed in 6.42s
```

## Claim boundary

This is a benchmark-oracle audit, not an estimate of model failure rates and not a claim about a Dynamo product defect. The mutation operators intentionally over-generate candidates; source review supplies the semantic judgment.

## License

MIT

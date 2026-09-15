# AgentDojo oracle audit

Six published AgentDojo traces are marked successful even though the required action is wrong.

![12-second terminal demo](media/oracle-audit-demo.gif)

Two examples are ordinary no-attack runs. Command R+ schedules a payment to the wrong account. GPT-4o mini sends the right amount to the wrong account. Both receive `utility=true`.

The audit checked 1,870 public trace files and found six complete false-success traces across three model pipelines. The exact rows are in [`results/impact.json`](results/impact.json).

## What found them

`oracle_audit.py` removes one state-changing action from each reference execution. `argument_audit.py` changes one argument at a time. The task's own grader is then run against the damaged execution.

That process found five current grader defects across Banking, Slack, Travel and Workspace.

| Task | Execution still accepted |
|---|---|
| `banking/user_task_6` | No new recurring payment, or a payment to the wrong account |
| `banking/user_task_11` | VAT payment sent to the wrong account |
| `slack/user_task_2` | Dora invited with the wrong email |
| `travel/user_task_3` | Hotel email sent to nobody |
| `workspace/user_task_12` | Calendar event created with the wrong title |

The patch in [`patches/agentdojo-oracle-fixes.patch`](patches/agentdojo-oracle-fixes.patch) fixes those checks without requiring fields the user never specified. Twenty focused tests pass from a fresh checkout.

`banking/user_task_5` was also reproduced and fixed, but it is not counted as a new finding because it was already reported in [issue 161](https://github.com/ethz-spylab/agentdojo/issues/161) and [PR 169](https://github.com/ethz-spylab/agentdojo/pull/169).

## Reproduce

```powershell
git clone https://github.com/ethz-spylab/agentdojo.git agentdojo-source
git -C agentdojo-source checkout 089ed468cf3ed0322acc66b0211f26d9d90dbf60
python -m pip install -e agentdojo-source pytest

python impact_audit.py agentdojo-source\runs
python oracle_audit.py agentdojo-source --expected-commit 089ed468cf3ed0322acc66b0211f26d9d90dbf60
python argument_audit.py agentdojo-source --expected-commit 089ed468cf3ed0322acc66b0211f26d9d90dbf60

git -C agentdojo-source apply ..\patches\agentdojo-oracle-fixes.patch
$env:PYTHONPATH = (Resolve-Path agentdojo-source\src).Path
python -m pytest -q agentdojo-source\tests\test_banking_user_tasks.py `
  agentdojo-source\tests\test_workspace_user_tasks.py `
  agentdojo-source\tests\test_oracle_argument_regressions.py
```

Verified on a fresh sparse checkout.

```text
20 passed in 5.19s
```

The six impact rows are trace files, not six independent model estimates. Four are attacked runs. Six empty-message result files and fourteen broken links were excluded from the impact count. The audit tests AgentDojo, not Dynamo.

MIT

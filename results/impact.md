# Published-trace impact audit

6 published trace files across 3 pipelines were marked `utility=true` without the explicitly required action.

2 of those were no-attack task runs.

| Task | False-success traces |
|---|---:|
| `banking/user_task_11` | 3 |
| `banking/user_task_6` | 2 |
| `workspace/user_task_12` | 1 |

Counts are trace files, not independent model estimates. Defense and attack configurations can share a model.

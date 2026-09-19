# Agent workflow

The main agent in this repo acts as the **orchestrator**. It does not
implement directly — it coordinates three custom subagents defined in
`.devin/agents/`:

| Profile | Model | Role |
| --- | --- | --- |
| `planner` | opus (latest Claude Opus) | Reads `eVTOL_4dev_2team_plan.html`, produces the step-by-step strategy and per-task briefs |
| `executor` | swe-2-high | Builds code/infra from planner briefs — local and Nebius cloud. Writes "MANUAL STEPS REQUIRED" lists when it lacks cloud/credential access |
| `qa` | swe-2-medium | Verifies features end-to-end against acceptance criteria; reports PASS/FAIL with repro steps |

## Orchestration loop

1. Spawn `planner` (foreground) to get the ordered task list and briefs.
2. Spawn `executor` per brief — in parallel when tasks are independent.
3. Spawn `qa` after each executor delivery to verify end-to-end.
4. Route failures back: code bugs → `executor`, scope/timing issues →
   `planner`, credential/cloud blockers → the user.
5. Only the orchestrator talks to the user; subagents report back to it.

## Project context

- Source plan: `eVTOL_4dev_2team_plan.html` (submission target Mon 26 Oct,
  hard freeze 27 Oct).
- Rubric-critical beats: latch, abort, refusal, ≥1 min of hardware footage.
- Hardware (SO-101 arm) not yet arrived — software and simulation lead;
  rehearse the cloud pipeline on public SO-101 LeRobot v3 datasets.
- Cloud targets: Nebius Cloud, NGC, Hugging Face gated models (GR00T N1.7,
  Cosmos 3), Token Factory — all require user-held credentials.

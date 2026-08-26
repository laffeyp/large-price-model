# Sprint 101 -- fail-loud on checkpoint kwargs (review §6.1)

---

```yaml
---
id: 101
status: closed
phase: F.close
pass_kind: architecture
determinism_budget: bit-deterministic
---
```

## scope

Strip placeholder defaults `checkpoint_run_id="sprint-NNN-no-checkpoint-id"` from all four `run_simulation_*` walkers and both sweep drivers. Same for the placeholder `cost_calibration_run_id`. Every call site must pass the real values.

Review §6.1: "the placeholder defaults are lies-lite -- legal string values that carry no meaning. Sprint 088 held-out simulation will call these walkers with a real checkpoint; the caller must remember to pass real kwargs. Defensive fix: change the signature to require them."

Aligns with Sprint 077's fail-loud opt-in pattern -- refuse the silent legal-but-lying default at the call site.

## deliverables

- `src/price_space_llm/simulation/skeleton.py` -- remove defaults on `checkpoint_run_id` and `cost_calibration_run_id` across four walkers (`run_simulation_skeleton`, `run_simulation_with_predictions`, `run_simulation_with_policy`, `run_simulation_with_trades`). The `SIM_RUN_STARTED.checkpoint_step` argument is currently hard-coded to `0` inside each walker body -- promote to a required kwarg `checkpoint_step: int` on all four.
- `src/price_space_llm/simulation/capacity.py` -- remove defaults; thread `checkpoint_step` + `checkpoint_run_id` + `cost_calibration_run_id` as required kwargs; forward to nested `run_simulation_with_trades`.
- `src/price_space_llm/simulation/sensitivity.py` -- same as capacity.
- `scripts/simulate.py` -- pass real values from the CLI (checkpoint path -> load `step` field; `--checkpoint-run-id`, `--cost-calibration-run-id` flags).

## tests (+3)

1. `test_run_simulation_with_trades_requires_checkpoint_kwargs` -- omitting either kwarg raises `TypeError` at call site.
2. `test_run_capacity_sweep_forwards_checkpoint_kwargs` -- kwargs propagate through the sweep to the nested walkers verbatim.
3. `test_run_kappa_sensitivity_forwards_checkpoint_kwargs` -- symmetric.

## artifact contract

- `src/price_space_llm/simulation/skeleton.py` -- edits only.
- `src/price_space_llm/simulation/capacity.py` -- edits only.
- `src/price_space_llm/simulation/sensitivity.py` -- edits only.
- `scripts/simulate.py` -- edits only.
- `tests/test_simulation_review_fixes_101.py` -- new.
- 4 code files + 1 test file. Under hard rule 6.

Content assertions:

- `! grep -q 'sprint-.*-no-checkpoint-id' src/price_space_llm/simulation/`

## signal contract

No new tags. `SIM_RUN_STARTED.checkpoint_step` and `.checkpoint_run_id` and `.cost_calibration_run_id` continue firing on the same payload shape; the values are now the caller's, not placeholders.

## observation contract

Re-run Sprint 100 smoke with the new required kwargs; verify identical numeric output and identical trace shape.

## commands

```
uv run ruff check .
uv run mypy
uv run pytest -q
```

## notes

- 4 code files. All existing tests calling the walkers need to add the two/three kwargs. Grep-and-fix during authorship.
- The two smoke scripts under `scratchpad/` similarly.
- Sprint 102 next: vectorize `block_bootstrap_sharpe` (review §3.2).

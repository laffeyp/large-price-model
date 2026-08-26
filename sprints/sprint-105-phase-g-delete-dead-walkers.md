# Sprint 105 -- delete dead intermediate walkers (Phase-F review §2)

---

```yaml
---
id: 105
status: closed
phase: G
pass_kind: architecture
determinism_budget: bit-deterministic
---
```

## scope

Delete `run_simulation_with_predictions` (Sprint 093 scaffold) and `run_simulation_with_policy` (Sprint 094 scaffold). Both were incremental walker layers built to give Sprint 093 → 094 → 096 a stable emit surface to extend. Sprint 096's `run_simulation_with_trades` supersedes both.

`grep` confirms zero production callers. Only `tests/test_simulation_prediction.py` and `tests/test_simulation_policy.py` reference either function. Those test files were scaffolds that proved the intermediate walkers built up correctly; they carry no product-facing guarantee.

The review's §2 walker-duplication complaint dissolves: after this deletion, `skeleton.py` contains one production walker (`run_simulation_with_trades`) and one CLI-facing bar-only walker (`run_simulation_skeleton`). The four-walker Template-Method-shaped duplication no longer exists. No `BarHook` framework required.

CLAUDE.md: "If you are certain that something is unused, you can delete it completely. Avoid backwards-compatibility hacks."

## deliverables

- `src/price_space_llm/simulation/skeleton.py` -- delete `run_simulation_with_predictions` (~90 lines) and `run_simulation_with_policy` (~130 lines). Remove `__all__` entries. Remove any imports these two functions used that neither survivor needs.
- `src/price_space_llm/simulation/__init__.py` -- drop the two exports from `__all__` and the import line.
- `tests/test_simulation_prediction.py` -- delete.
- `tests/test_simulation_policy.py` -- delete. The `variance_vn` / `decide` / `compute_edge` unit tests inside it (against pure `policy.py` functions) migrate to a new focused `tests/test_simulation_policy_functions.py`.

## tests (+0 net; migrate what remains testable)

- Migrate all unit-level `policy.py` function tests (`variance_vn`, `compute_edge`, `decide`) from `test_simulation_policy.py` to `test_simulation_policy_functions.py`. Walker-level tests deleted with the walker.
- Migrate `derive_prediction_scalars` unit tests from `test_simulation_prediction.py` to `test_simulation_prediction_functions.py`. Walker-level tests deleted.
- Delete the four walker-integration tests inside each file.

## artifact contract

Files created or modified:

- `src/price_space_llm/simulation/skeleton.py` -- ~220 lines removed.
- `src/price_space_llm/simulation/__init__.py` -- edit.
- `tests/test_simulation_prediction.py` -- deleted; `tests/test_simulation_prediction_functions.py` -- new.
- `tests/test_simulation_policy.py` -- deleted; `tests/test_simulation_policy_functions.py` -- new.
- 2 code files touched + 2 test files migrated. Under hard rule 6.

Content assertions:

- `! grep -q "def run_simulation_with_predictions" src/price_space_llm/simulation/skeleton.py`
- `! grep -q "def run_simulation_with_policy" src/price_space_llm/simulation/skeleton.py`

## signal contract

No new tags. No emit-surface change. The two deleted walkers emitted the same tags the survivor emits; every tag continues to fire from `run_simulation_with_trades`.

## observation contract

Re-run Sprint 100 smoke; expect identical numeric output.

## commands

```
uv run ruff check .
uv run mypy
uv run pytest -q
```

## notes

- 2 code files + 2 test-file migrations. Under hard rule 6.
- Total test count drops by whatever the two walker-integration tests contributed and rises by whatever unit-level tests migrated. Net expected: -8 or so.
- The `BarHook` composition refactor named in the review §2 is no longer needed. The remaining two walkers serve different consumers (CLI bar-only vs sweep-driven trades) and share almost no loop shape.

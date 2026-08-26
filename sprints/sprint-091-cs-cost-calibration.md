# Sprint 091 -- Corwin-Schultz cost re-calibration on 2015-2022 (Phase F opens)

---

```yaml
---
id: 091
status: closed
phase: F
pass_kind: functional
determinism_budget: bit-deterministic
---
```

## scope

Land the Corwin-Schultz estimator + 2024 bias-correction primitives as a self-contained module. Ratified by the 2026-08-17 Architect Decision (path (b)). Persist-to-disk + CLI wiring defers to Sprint 093, which lands the simulator (the actual `SpreadScaler` consumer); building the persistence layer before the consumer exists would ship untested code with no runtime path. Live smoke in this sprint reads the real training features parquet, computes CS on SPY OHL, and reports the mean/median/quantile statistics so the Architect sees the reference number Sprint 093 will bias-correct. Phase F opens on this sprint; the simulator subsystem (Sprints 092-096, roadmap 074-078) queues behind it.

Sprint 035's Kappa stays unchanged (Kyle-lambda signal near-zero at 15-min bars regardless of vendor).

## deliverables

- `src/price_space_llm/cost_calibration/corwin_schultz.py` — new module implementing:
  - `corwin_schultz_spread(highs, lows) -> list[float]` per Corwin-Schultz (JoF 2012). Returns per-bar-pair proportional spread estimates; NaN where the formula produces a negative alpha (spec allows dropping those; documented in the module docstring).
  - `BiasCorrection` dataclass carrying `ratio: float`, `n_known: int`, `n_estimated: int`, `provenance: str`.
  - `fit_bias_correction(known_bbo, cs_estimated) -> BiasCorrection` — `ratio = mean(known) / mean(estimated)`, ignoring NaN entries in either.
  - `apply_bias_correction(cs_series, correction) -> list[float]` — scalar-multiply.
- `src/price_space_llm/cost_calibration/__init__.py` — export the four new names.
- Live smoke in the sprint close note reporting mean CS on the real 2015-2022 training features parquet's SPY OHL.

## tests (+5)

1. `test_corwin_schultz_on_synthetic_ohl` — synthetic two-bar sequence with known-spread arithmetic; CS estimate within 10% of the known value.
2. `test_corwin_schultz_returns_nan_on_negative_alpha` — bar pair that produces `alpha < 0` returns NaN; documented as CS's boundary behavior.
3. `test_fit_bias_correction_ratio_math` — synthetic known + estimated series with known ratio 2.0; helper returns 2.0.
4. `test_apply_bias_correction_scalar_multiply` — 3-element series × ratio = elementwise multiply.
5. `test_calibrate_cli_corwin_schultz_smoke` — subprocess `scripts/calibrate.py --method corwin_schultz` against a synthetic aligned parquet (small OHLC fixture); expects exit 0, `spread_scaler.latest.json` on disk, emit trace carries `COST_CALIBRATION_FITTED` with `method: "corwin_schultz"`.

## context files

- `src/price_space_llm/cost_calibration/spread.py`
- `src/price_space_llm/cost_calibration/calibrate.py`
- `scripts/calibrate.py`
- `plans/v1-roadmap.md` § Phase F
- `BLACKBOARD.md ## Decisions` 2026-08-17 entry ratifying path (b)

## artifact contract

Files created or modified:

- `src/price_space_llm/cost_calibration/corwin_schultz.py` — new.
- `src/price_space_llm/cost_calibration/__init__.py` — modified: exports.
- `scripts/calibrate.py` — modified: `--method` flag + `corwin_schultz` branch.
- `tests/test_corwin_schultz.py` — new.

Content assertions:

- `grep -q "def corwin_schultz_spread" src/price_space_llm/cost_calibration/corwin_schultz.py`
- `grep -q "\\-\\-method" scripts/calibrate.py`

## signal contract

Emits: `COST_CALIBRATION_FITTED` (existing v0.3+) with a `method` payload field that already accepts arbitrary strings per v0.3 shape. If the vocabulary field constrains `method` via an enum, a v0.8 vocab bump adds `corwin_schultz`; verify before wiring.

## observation contract

Live smoke: run `scripts/calibrate.py --method corwin_schultz` against the training aligned parquet; report the bias-corrected SpreadScaler slope alongside Sprint 035's options-based slope; the two should sit within an order of magnitude if the bias correction is calibrated correctly. Any 10× or larger divergence indicates a formula bug or a units mismatch and blocks Phase F.

## commands

```
uv run ruff check .
uv run mypy
uv run pytest -q
uv run python scripts/calibrate.py --method corwin_schultz
```

## notes

- 2 code files (`corwin_schultz.py` new; `scripts/calibrate.py` modified) + 1 package `__init__.py` + 1 new test file. Under hard rule 6.
- Path (a) Databento revisit reserved: after Sprint 084 sweep + Sprint 088 held-out evaluation, if the Sharpe-gate margin is inside 20% of the "Sharpe − SE > 0" threshold, open Sprint 097 (or later) for the Databento fetcher.
- Sprint 035's Kappa stays. Kappa sensitivity plot (Sprint 095 candidate, roadmap 078) is the safety net around the near-zero point estimate.
- CS's documented downward bias (Abdi-Ranaldo 2017) on sub-day bars: the 2024 bias correction closes the mean-level gap but not the regime-dependent bias (higher on stress bars). The v1 report's cost-model section must name this residual bias explicitly.

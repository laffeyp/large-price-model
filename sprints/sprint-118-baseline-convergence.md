# Sprint 118 -- baseline convergence probe and public correction

---

```yaml
---
id: 118
status: closed
phase: H
pass_kind: functional
determinism_budget: bit-deterministic
---
```

## scope

An outside audit of the public repo (2026-09-27) read `fit_linear(n_steps=200)` and the logbook's "LinearBaseline ... n_steps=200" row and concluded the linear baseline was undertrained. The claim was wrong, and nothing public refuted it: the only table showing linear peaking at step 800 sat in `artifacts/sprint113-feature-role-report.md`, which is gitignored. This sprint commits a reproducible probe that answers the question, and puts the answer where a reader looks first.

Two findings the probe must record. (1) Linear at the project lr=1e-3 peaks near step 800 and overfits after; it was not undertrained. (2) Early-stopped at lr=3e-4, linear reaches ~3.255 and the MLP ~3.211, both better than the 3.289 the Phase H margin was computed against. The transformer's 5-seed mean of 3.180 beats the best tuned baseline by under 1 percent, not 3.29.

## deliverables

- `scripts/analysis/baseline_convergence.py` (new): lr x wd grid per baseline kind, early-stopped on the same 10,789 validation windows, best config re-run at seeds 0-4. Refuses any token artifact not named for 2015-01..2022-12.
- `reports/baseline-convergence.json` (new): the probe's output.
- `reports/baseline-convergence.md` (new): the table and the answer.
- `README.md`: the "What it found" section cites the tuned baselines and states plainly that linear was not undertrained.
- `src/price_space_llm/baselines.py`: `fit_linear` / `fit_mlp` / `fit_gru` docstrings say the defaults are smoke-test settings and point at the probe.
- `reports/phase-h-close.md`, `CHANGELOG.md`: dated correction appended; original text kept.

Seven files. Over the two-file sweet spot (hard rule 6); one concept (the baseline comparison), docs-dominant. Architect authorized the scope in chat 2026-09-27: "bring this up to snuff" and "make it so when an LLM looks at the GitHub page it's not wrong about the linear stuff."

## signal contract

### Emits

None. The probe follows the `scripts/analysis/linear_per_regime.py` precedent: a diagnostic outside the emitter. No vocabulary change.

### Invariants

- No held-out read. The probe opens only the normalized 2015-2022 artifact; no test look registered.
- The transformer numbers are not re-run; they come from `experiments/logbook.csv` rows for Sprint 115/116.
- Phase H text is corrected by appending, not by rewriting.

## artifact contract

### Content assertions

- `reports/baseline-convergence.json` parses; `best_config_multiseed` has keys `linear`, `mlp`, `gru`, each with five `per_seed` values.
- The linear grid row at lr=1e-3, wd=0 has `best_step` near 800 and its curve's last point above its best (overfit visible).
- `README.md` contains the string `not undertrained`.
- `fit_linear` docstring contains `smoke-test`.

### Command exit codes

- `uv run python scripts/analysis/baseline_convergence.py --output reports/baseline-convergence.json` returns 0.
- `uv run python scripts/analysis/baseline_convergence.py --tokens-pt data/tokenized/tokens.latest.pt --output /tmp/x.json` returns 2 (refuses the held-out symlink).
- `uv run pytest` returns 0.

## observation contract

- Probe at lr=1e-3, wd=0, seed 0 reproduces Sprint 111's 3.3325 at step 200 and Sprint 113's 3.289 at step 800 (checked in the scratch run before this card: 3.3325, 3.2886).

## notes

- The linear baseline sees only the target's own 64-bucket history; the transformer sees 20 channels and a different architecture. The gap does not isolate the channels' contribution; only the spec's target-only ablation does.
- Found during the audit, out of scope here, carried to the next cards: `data/tokenized/tokens.latest.pt` points at the held-out tokens while the README's reproduce command trains on that path, and `heldout_guard` recognizes neither held-out `.pt` filename nor is called by `train.py`.

## close (2026-09-27)

- Probe ran in 594 s on CPU. Seed-0 lr 1e-3 curve reproduces 3.3325 at step 200 and 3.2886 at step 800, then 3.3217 / 3.5020 / 3.6676 at 2,000 / 5,000 / 8,000.
- Best config per kind, 5 seeds: linear 3.2556 (sd 0.0019), GRU 3.2189 (sd 0.0007), MLP 3.2120 (sd 0.0041). Transformer 5-seed mean 3.1803 beats them by 2.31%, 1.20%, 0.99%. Every transformer seed beats every baseline seed.
- Pre-registered gates: not measurable with these baselines. The spec's linear and MLP read the multi-channel input and its GRU/TCN is ~1M parameters; the repo's baselines read target history only (65,568 / 273,664 / 107,296 parameters).
- Probe refuses `data/tokenized/tokens.latest.pt` (exit 2).
- Also corrected: `tests/test_simulation_prediction.py:16` over-length docstring (pre-existing ruff E501). `ruff check src scripts tests` clean; `mypy src` clean; `pytest` 634 pass, 2 skip.
- Historical records (BLACKBOARD Sprint 111/116 entries, KIT_DIARY, reviews, handoff) keep their original numbers as audit trail. Public entry points (README, CHANGELOG, phase-h-close, successor spec) carry the correction.

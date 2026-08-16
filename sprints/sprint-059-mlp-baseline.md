# Sprint 059 -- MLP baseline (128 → 64 → 32 GELU)

---

```yaml
---
id: 059
status: closed
phase: 3
pass_kind: functional
determinism_budget: statistically-deterministic
---
```

---

## scope

Closes one of the review § 3 baseline items: *"Small MLP (128→64→32) absent."* Product-spec § Baselines names five: linear (present), MLP (missing), GRU/TCN (missing), target-only (wrong shape), magnitude-weighted (present). Sprint 059 lands MLP.

### Deliverables

- `MLPBaseline(nn.Module)` — flatten `(B, T)` one-hot to `(B, T*V)`; then `Linear(T*V, 128) → GELU → Linear(128, 64) → GELU → Linear(64, 32) → Linear(32, V)`. Predicts the same "next token from context" as `LinearBaseline`.
- `fit_mlp(train_tokens, ...)` — same signature shape as `fit_linear`; uses Adam + CE.
- `fit_and_eval` gains the `"mlp"` kind and dispatches to `fit_mlp` + eval helper.
- Tests: architecture shape; determinism with fixed seed; end-to-end fit_and_eval smoke.

## signal contract

No new emit sites. `BaselineFitResult` shape unchanged; `kind="mlp"` in the payload.

## artifact contract

### Files (2 — under hard rule 6)

- `src/price_space_llm/baselines.py` — add `MLPBaseline`, `fit_mlp`, extend `BaselineKind` Literal + `fit_and_eval` dispatch.
- `tests/test_baselines.py` — new tests: forward shape; deterministic fit; fit_and_eval kind="mlp" returns MetricSet.

### Command exit codes

- ruff, ruff format, mypy: green.
- pytest: 381 → 385+.

---

## observation contract

Required (`pass_kind: functional`). Unit tests + a 30-step fit determinism check.

---

## honest audit

**What lands.** MLP baseline available on the same fit/eval harness as linear.

**What does not land.** GRU/TCN baseline (Sprint 060). Rewiring `TargetOnlyBaseline` as spec's zeroed-channel transformer (Sprint 061). Migrating baselines to the feats path (deferred until baselines are used against the market-state model in Sprint 086).

---

## plan-mode review checklist

- [ ] Files under hard rule 6 (2).
- [ ] Observation contract: unit tests.
- [ ] Determinism budget statistically-deterministic (same seed = same weights within numerical noise).
- [ ] Closes one of five spec baseline items: MLP.

# Sprint 060 -- GRU baseline

---

```yaml
---
id: 060
status: closed
phase: 3
pass_kind: functional
determinism_budget: statistically-deterministic
---
```

---

## scope

Closes the GRU/TCN baseline slot from product-spec § Baselines: *"GRU (1 hidden layer, 128 units, causal, ~1M params)."* Sprint 060 ships the GRU flavor; the TCN alternate stays deferred.

## deliverables

- `GRUBaseline` (nn.Module): `nn.Embedding(V, 128)` → `nn.GRU(128, 128, num_layers=1, batch_first=True)` → take final hidden state → `nn.Linear(128, V)` head.
- `fit_gru` + `eval_gru`.
- `BaselineKind` gains `"gru"`; `fit_and_eval` dispatch adds the GRU branch. `REQUIRED_DELTA_PCT["gru"] = 5.0`.
- Tests: forward shape, param-count band, deterministic fit, fit_and_eval end-to-end.

## honest audit

- **Param count.** For V=32 vocab + hidden=128: embedding 4,096 + GRU cell ~98K + head 4,128 ≈ 106K. The spec's "~1M params" figure assumes a wider vocab tokenizer; at V=32 the shape is much smaller. Documented in the test's assertion band (50K < params < 200K).
- **TCN alternate not shipped.** Deferred.
- **What ships.** GRU baseline available on the same fit/eval harness as linear/mlp; ready for Sprint 086's baseline ladder against the market-state transformer.

Tests +4 (forward shape, param count band, deterministic fit, fit_and_eval kind="gru"). Count 384 → 388. Ruff + mypy + pytest green.

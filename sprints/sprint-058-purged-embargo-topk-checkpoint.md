# Sprint 058 -- purged embargo at split boundary + top-K checkpoint selection

---

```yaml
---
id: 058
status: closed
phase: 3
pass_kind: functional
determinism_budget: bit-deterministic
---
```

---

## scope

Two review § 3 MEDIUM items in one sprint:

1. **Purged `H`-bar embargo at split boundaries** (spec § Testing + § 9.2). `dataset.py::split_tokens` and `_split_artifact` (Sprint 053) currently slice contiguously. Need to drop `horizon` bars at each split boundary so the val window's first target doesn't see the training window's last input.
2. **Top-K checkpoint selection by val NLL** (spec § 9.3). `trainer.py:250-255` currently symlinks `latest.pt` to the newest step. Need to keep only the top-K checkpoints ranked by val_nll and prune the rest.

### Deliverables

- `split_tokens(tokens, train_frac, embargo)` — new kwarg. Drops `embargo` tokens at the boundary: val starts at `n_train + embargo` instead of `n_train`. Default `embargo=0` preserves back-compat.
- `_split_artifact(artifact, train_frac, embargo)` — same pattern on the market-state path.
- `TrainerConfig.embargo: int = 0` — plumbed through both `run_training` and `run_training_feats`.
- `TrainerConfig.keep_top_k: int = 0` — 0 preserves current "keep every checkpoint" behavior; a positive value maintains a rolling priority queue on `val_nll` and prunes on write.
- `_ranked_checkpoint_cleanup(checkpoint_dir, run_id, keep_top_k)` — after each CHECKPOINT_WRITTEN, walk `{run_id}-step*.pt` files, sort by their recorded `val_nll`, delete files past the top-K.

## halt-and-articulate

**Checkpoint metadata reads.** Ranking existing checkpoints by val_nll requires the value on disk. Sprint 058 stores val_nll in the checkpoint's own `torch.save` dict (already done — the checkpoint carries `val_nll` in its metadata via CHECKPOINT_WRITTEN payload but not in the .pt itself). Fix: also write `val_nll` inside the .pt. Alternative: track val_nll in an in-memory dict inside the trainer loop; that only works within one run. Sprint 058 does BOTH — in-memory for the current run + val_nll in the .pt so an interrupted run can still be pruned by a later CLI.

## signal contract

No new emit sites. The existing CHECKPOINT_WRITTEN payload already carries `val_nll`. `latest.pt` symlink still flips to the newest write when top-K keeps it; if the newest is pruned (worse than K existing), the symlink stays on whatever WAS newest+kept.

### Invariants

- `split_tokens(tokens, train_frac=0.8, embargo=0)` returns the same shapes as pre-Sprint-058.
- `split_tokens(tokens, train_frac=0.8, embargo=32)` returns `train = tokens[:n_train]`, `val = tokens[n_train + 32:]`.
- `_split_artifact(..., embargo=H)` drops `H` rows on both features and targets at the boundary.
- `keep_top_k=0` disables pruning (current behavior).
- `keep_top_k=3` after 5 writes leaves 3 `.pt` files on disk (the top-3 by val_nll ascending).
- Every kept checkpoint's `.pt` file carries `val_nll` at the top level.

## artifact contract

### Files (3 — under hard rule 6)

- `src/price_space_llm/model/dataset.py` — `split_tokens` gains `embargo` kwarg; new signature is back-compat.
- `src/price_space_llm/model/trainer.py` — `TrainerConfig.embargo`, `TrainerConfig.keep_top_k`; `_split_artifact` gains embargo; both trainer loops write `val_nll` into the `.pt`; new `_prune_checkpoints_to_top_k`; pass `trainer_cfg.embargo` into `split_tokens` and `_split_artifact`.
- `tests/test_trainer.py` — new tests: embargo drops H tokens; top-K prunes correctly; the kept checkpoint file has `val_nll` inside.

### Command exit codes

- ruff, ruff format, mypy: green.
- pytest: 376 → 383+.
- Live smoke: `--n-steps 8 --eval-every 2 --embargo 32` writes 4 checkpoints; with `--keep-top-k 2` only 2 remain on disk.

---

## observation contract

Required (`pass_kind: functional`). Unit tests cover both mechanisms; live smoke verifies pruning against the real training .pt.

---

## honest audit

**What lands.** Both spec-mandated mechanisms wired into both trainer paths.

**What does not land.** `latest.pt` semantics under top-K pruning: if the newest checkpoint is pruned (rare in practice — newer usually improves), the symlink drops. Sprint 058 flips it to the highest-ranked kept checkpoint. Named in the notes.

---

## plan-mode review checklist

- [ ] Files under hard rule 6 (3).
- [ ] No new emit sites.
- [ ] Observation contract: unit tests + live smoke pruning check.
- [ ] Determinism budget bit-deterministic (same seed + same tokens + same embargo = same batches).
- [ ] Closes review § 3 MEDIUM items on purged embargo + top-K checkpoint.

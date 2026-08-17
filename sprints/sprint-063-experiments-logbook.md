# Sprint 063 -- experiments/logbook.csv writer + scripts/register_run.py

---

```yaml
---
id: 063
status: closed
phase: 4
pass_kind: functional
determinism_budget: bit-deterministic
---
```

## scope

Closes review § 3 aggregate-audit HIGH item: *"No `experiments/logbook.csv` writer. `experiments/` dir absent."* Tech-arch §13 mandates one row per training run in an append-only CSV with the operator-facing manifest of every registered run.

## deliverables

- `src/price_space_llm/logbook.py`: `LogbookEntry` dataclass (22 fields matching tech-arch §13 column order: date / run_id / branch / git_sha / notes / target / model_size / context_len / patch_size / head_type / n_buckets / train_loss / val_nll / val_ece / val_brier / val_rps / val_dir_acc / held_out_sharpe / held_out_sharpe_se / lambda_risk / alpha_mag_weight / touched_test). `append_run` writes header on first append; is strictly append-only. `read_logbook` returns every row as `dict[str, str]`.
- `scripts/register_run.py` CLI: takes run metadata + val metrics + optional held-out fields; resolves current git branch via subprocess; appends via `append_run`. Defaults populate optional fields with NaN or 0.
- Tests +5: append creates file + header; append-only across two calls; missing-file read returns []; header column order matches spec; CLI end-to-end.

## honest audit

- **`register_run` is a shell-invoked tool, not wired into `run_training`.** By design: the trainer emits `TRAINING_STEP_COMPLETED` per step + `CHECKPOINT_WRITTEN` per eval; those live in the JSONL trace. `register_run` is the operator's post-hoc summary row when they decide a run is worth logging. Sprint 084's sweep script will invoke `register_run` per completed run.
- **No dependency on external metrics libs.** stdlib `csv` handles everything.

Tests +5. Count 396 → 401. Ruff + mypy + pytest green.

# Sprint 119 -- held-out guard covers token artifacts and the training entrypoint

---

```yaml
---
id: 119
status: closed
phase: H
pass_kind: functional
determinism_budget: bit-deterministic
---
```

## scope

The 2026-09-27 audit found the held-out guard open on the path the README tells readers to run. After Sprint 117, `data/tokenized/tokens.latest.pt` is a symlink to `tokens.sprint117-heldout-sprint115-mixer-2024-01-2025-06-tokenize.pt`. The README's reproduce command trains on `tokens.latest.pt`. `scripts/train.py` never called `heldout_guard`, and the guard's patterns matched neither held-out token filename (`allow_unrecognized=True` returned "not held-out" for both). Nothing stopped a reader from training on the held-out window.

Fix: the guard treats any name carrying `heldout` as held-out, recognizes the bare `tokenize-features-align-YYYY-MM` bucketize output, and checks a symlink's target name as well as its own. `train.py` calls the guard before loading tokens and exits 2 on a held-out input, with no override. Test looks stay in `evaluate.py` and `simulate.py`.

## deliverables

- `src/price_space_llm/heldout_guard.py`: `HELDOUT_NAME_MARK`, the bare-bucketize pattern, symlink-target check.
- `scripts/train.py`: guard call after the tokens-path existence check.
- `tests/test_heldout_guard.py`: five tests planting the Sprint 117 shapes, including a subprocess run of `train.py` against a symlink named `tokens.latest.pt`.
- `tests/test_train_device.py`: four smoke tests named `tokens.latest.pt`; they now name the normalized 2015-2022 artifact.
- `README.md`: reproduce command names the normalized 2015-2022 artifact explicitly (landed with Sprint 118's README edit).

## signal contract

### Emits

None new. `train.py` exits before `script_session` opens, matching the existing argument-validation exits.

## artifact contract

### Command exit codes

- `uv run pytest tests/test_heldout_guard.py` returns 0 (14 pass).
- `uv run pytest` returns 0.

## observation contract

Verify-the-verifier (Addendum D3): with `heldout_guard.py` and `train.py` restored to `HEAD`, four of the five new tests fail (`test_heldout_name_mark_detected_whatever_the_date_layout`, `test_bare_bucketize_output_detected_as_heldout`, `test_innocent_symlink_to_heldout_is_heldout`, `test_train_refuses_symlink_to_heldout`). The fifth, `test_innocent_symlink_to_training_passes`, passes under both, as a pass-through test should. With the fix restored, 14 pass.

## finding at close

The guard's first full-suite run failed two tests: `test_train_cli_xs_smoke_on_pt_artifact` and `test_train_cli_c128_xs_smoke_on_pt_artifact`. Both trained on `data/tokenized/tokens.latest.pt`, which since Sprint 117 resolves to the held-out tokens. On this machine those smokes had been fitting a few steps on 2024-2025 data every suite run since 2026-08-25. No metric from them was recorded or reported, and a fresh clone skips them for lack of data, which is why nothing caught it. The four smokes now name the training artifact. Full suite 634 pass, 2 skip.

## notes

- The local `data/tokenized/tokens.latest.pt` symlink still points at the held-out tokens. It is gitignored local state; the guard now refuses it at the training entrypoint, and the README no longer names it.
- No held-out bytes were read during this sprint. Every test uses empty files under `tmp_path`.

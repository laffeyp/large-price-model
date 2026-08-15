# Sprint 051 -- review blockers: test-look guard wiring + device handling

---

```yaml
---
id: 051
status: closed
phase: 2
pass_kind: functional
determinism_budget: bit-deterministic
---
```

---

## scope

Fix two of the four pre-GPU blockers the Sprints 041-050 review named. Review items #3 (test-look guard wiring) and #4 (device handling) are small, independent, and code-reachable in one sprint. The other two blockers (MarketStateEmbedder SEVERE, frozen normalizer) each need their own sprint or two; the ratifications (RoPE, size + context sweeps) are Architect calls surfaced to BLACKBOARD.

### Review item #3 — test-look guard wiring

`src/price_space_llm/testlook.py::register_test_look` exists since Sprint 034. Nothing called it automatically. Any human running `scripts/evaluate.py` against the held-out test partition (2024-01 through 2025-06, Sprint 039) consumed zero of the 3-look budget and left no log entry. That is the "gate nobody has watched fail is not a gate" trap named in Addendum D.

**Fix.** `scripts/evaluate.py` gains three CLI flags:

- `--split {train,val,test}` (default `val`, preserves pre-Sprint-051 behavior).
- `--test-look-reason STRING` (required when `--split test`).
- `--i-know-this-is-a-test-look` (safety flag, required when `--split test`).

When `--split test`: the guard validates both safety args before any file check, then calls `register_test_look(reason, run_id, commit_sha, emitter)`. Exit 1 on missing safety args; exit 2 on `TestLookBudgetExhausted`; otherwise the eval proceeds with `TEST_LOOK_REGISTERED` in the trace and one new line in `experiments/test_looks.log`.

Filesystem guard on `data/aligned/*.parquet` for held-out reads is a separate item deferred to Sprint 081 per roadmap.

### Review item #4 — device handling

`run_training` in `src/price_space_llm/model/trainer.py` had zero `.to(device)` calls. Model + tensors lived on CPU only. First GPU rental (Sprint 083 per roadmap) would have crashed on the first backward pass.

**Fix.** `scripts/train.py` gains `--device {cpu,cuda,mps,auto}` (default `auto`; `_resolve_device` maps `auto` → cuda > mps > cpu at runtime). Passes the resolved device through to `run_training(device=...)`. The trainer:

- Creates `torch_device = torch.device(device)` and does `model.to(torch_device)` at construction.
- Moves `batch.inputs.to(torch_device)` and `batch.targets.to(torch_device)` inside the training loop before the forward pass.
- The val pass reads `next(model.parameters()).device` to move val batches to the same device — one source of truth for where the model lives.

Sampler generator stays on CPU (integer index sampling; batches move to device after generation). Back-compat default `device="cpu"` in `run_training` signature keeps every pre-Sprint-051 test working.

## halt-and-articulate

None expected. Both fixes are additive with back-compat defaults.

## signal contract

### Emits

- `TEST_LOOK_REGISTERED` — one per successful `--split test` invocation, payload: `date, run_id, reason, commit_sha, looks_used, looks_remaining`.
- `TEST_LOOK_BUDGET_EXHAUSTED` — fires on the fourth `--split test` invocation attempt, payload: `existing_looks, attempted_run_id, commit_sha`. Then raises `TestLookBudgetExhausted` and evaluate exits 2.

No new tags. Both tags are pre-declared in v0.4 vocab from Sprint 034.

### Invariants

- `--split val` (default) preserves the pre-Sprint-051 behavior byte-for-byte.
- `--split test` without `--i-know-this-is-a-test-look` OR without non-empty `--test-look-reason` exits 1 with a clear stderr message and does NOT touch `experiments/test_looks.log`.
- `--split test` with valid safety args and available budget appends one line to `experiments/test_looks.log`, emits `TEST_LOOK_REGISTERED`, and proceeds.
- `--split test` with valid safety args but exhausted budget emits `TEST_LOOK_BUDGET_EXHAUSTED` and exits 2.
- `_resolve_device("cpu"|"cuda"|"mps")` returns the input unchanged.
- `_resolve_device("auto")` returns `"cuda"` if available, else `"mps"` if available, else `"cpu"`.
- `run_training(device="cpu")` is the default; produces identical results to the pre-Sprint-051 code path.
- `run_training(device="cuda")` moves model + batches to cuda; CUDA-skipped-unless-available test verifies smoke completes without OOM.

## artifact contract

### Files

- `scripts/evaluate.py` — three new CLI flags; guard block runs before file-existence checks; `register_test_look()` call in the session-active branch; exit 2 mapped to `TestLookBudgetExhausted`.
- `scripts/train.py` — `_resolve_device()` helper; `--device` CLI flag; `device = _resolve_device(args.device)` before `run_training`.
- `src/price_space_llm/model/trainer.py` — `run_training(device: str = "cpu")` kwarg; `torch_device = torch.device(device)`; `model.to(torch_device)`; inputs/targets moved to device inside the train loop; val batches moved to `next(model.parameters()).device`.
- `tests/test_evaluate_test_look_guard.py` — new file, four subprocess-driven tests: missing safety flag exits 1; missing reason exits 1; default `val` doesn't require the flags; guard fires before file-existence check.
- `tests/test_train_device.py` — new file, five tests: `_resolve_device` pass-through for cpu/cuda/mps; `auto` returns the available device; `run_training(device="cpu")` completes a 2-step smoke; skipped-unless-CUDA test that `device="cuda"` completes.

### Command exit codes

- ruff, ruff format, mypy: green.
- pytest: 324 → 333 (+9 tests: 4 evaluate-guard + 5 device; 1 CUDA-skipped on macOS).
- Existing evaluate + train tests unaffected.

### Live smoke

Not run — this sprint's fixes are argparse plumbing + `.to(device)` plumbing, both covered by unit tests. The observation contract for a real GPU run lives on Sprint 083 when the first cloud instance boots.

---

## observation contract

Required (`pass_kind: functional`). Unit tests lock every guard branch and every `_resolve_device` branch. The CUDA-gated device test would fire on Sprint 083's first cloud run; on the current CPU-only local box it skips cleanly.

---

## honest audit

**What lands.** Two of the four pre-GPU review blockers close. Test-look budget is now structurally enforced whenever `scripts/evaluate.py --split test` runs; the pre-commit hook + filesystem guard are still Sprint 080/081 items but the runtime guard covers the primary attack surface. Device handling threads through cleanly; a `--device cuda` invocation would work today given a CUDA-available box.

**What does not land.** The SEVERE MarketStateEmbedder gap (review §1) stays open — that is Sprint 052. Frozen normalizer (review item #2) stays open — that is Sprint 053. Normalization-drift diagnostic (review #8) stays blocked on the normalizer. MLP + GRU baselines (review #6) stay open. RoPE (review #5) and size + context sweeps (review #7) are Architect calls surfaced to BLACKBOARD § Surfaced.

**What surfaces.** None new.

---

## notes

**Why the guard fires before file-existence.** Original ordering had the file checks first; a `--split test` invocation with a nonexistent checkpoint would have exited 1 with `checkpoint not found` rather than the safety-flag message. Reordering surfaces the intent-level error first. Tests explicitly verify this ordering.

**Why `_resolve_device` lives in `scripts/train.py` not `src/`.** It's CLI plumbing, not model code. If a second script (evaluate, baselines) needs device handling later, factor it out to `price_space_llm.device` at that time. Premature abstraction now would create a one-caller module.

**Why the sampler generator stays on CPU.** The generator produces integer indices for window starts; those are cheap python-side arithmetic. Batches materialize as CPU tensors and move to device after sampling. Alternative (generator on GPU) would add a device-to-device transfer per sample without saving any real work.

---

## plan-mode review checklist

- [x] Files under hard rule 6 (three code + two test files).
- [x] No new emit sites; TEST_LOOK_REGISTERED and TEST_LOOK_BUDGET_EXHAUSTED already declared in v0.4.
- [x] Observation contract (functional-band): nine unit tests covering every branch of both fixes.
- [x] Determinism budget bit-deterministic (test-look wiring changes CLI surface; device handling is transparent to CPU runs).
- [x] Two of four pre-GPU review blockers closed; other two escalated (SEVERE MarketStateEmbedder → Sprint 052 next; frozen normalizer → Sprint 053).

---

## close (2026-08-14)

Landed. `scripts/evaluate.py --split test` now consumes one of three looks via `register_test_look()`; refuses without `--i-know-this-is-a-test-look` + non-empty `--test-look-reason`; exits 2 on budget exhaustion. `scripts/train.py --device {cpu,cuda,mps,auto}` threads through `run_training(device=...)`; model and batches move to the resolved device. Test count 324 → 333 (+9 new: 4 evaluate-guard + 5 device, 1 CUDA-skipped). Four tools green. Two of four pre-GPU review blockers cleared; MarketStateEmbedder (SEVERE) and frozen normalizer remain — Sprints 052 and 053 open next.

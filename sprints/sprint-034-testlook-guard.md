# Sprint 034 -- test-look budget guard

---

```yaml
---
id: 034
status: closed
phase: 2
pass_kind: functional
determinism_budget: bit-deterministic
---
```

---

## scope

Author `src/price_space_llm/testlook.py::register_test_look` + a thin CLI. Enforces the product-spec §13 three-look budget against the held-out test partition. Emits `TEST_LOOK_REGISTERED` on authorized use, `TEST_LOOK_BUDGET_EXHAUSTED` (and raises) on any attempt past the budget. Append-only log at `experiments/test_looks.log`.

## why not the natural next sprint

Sprint 034 was originally scoped as cost calibration (three `calibrate` tags). Halted with `bridge_mapping_required` — see BLACKBOARD entry dated 2026-08-12. The Kappa fit needs real market-impact data (BBO or per-trade fills); Alpha-Vantage publishes 15-min OHLCV only. Substituting bar-range for BBO half-spread is a defensible half-measure for the spread scaler alone; fitting Kappa without impact data means fabricating values — the exact Sprint 020 anti-pattern. Pivoted to `testlook`: two tags, self-contained, no data dependency.

## signal contract

### Emits

- `TEST_LOOK_REGISTERED` (event) per authorized look. Payload: `date` (ISO), `run_id`, `reason`, `commit_sha`, `looks_used`, `looks_remaining`.
- `TEST_LOOK_BUDGET_EXHAUSTED` (incident) per attempted look beyond budget. Payload: `existing_looks`, `attempted_run_id`, `commit_sha`. Followed by `TestLookBudgetExhausted` raise.

### Invariants

- Log is append-only. `_read_existing` never rewrites; `register_test_look` only writes on the success path.
- Budget-exhausted attempts do NOT append to the log (`test_no_write_on_budget_exhausted` verifies via `read_bytes()` equality).
- Budget persists across emitter lifetimes: any new emitter reads the same log and respects the same count.
- Empty `reason` or `commit_sha` raise `ValueError` before any emit — pre-commit hook contract.

## artifact contract

### Files created

- `src/price_space_llm/testlook.py` (~130 lines: `register_test_look`, `looks_used`, `TestLookRecord` dataclass, `TestLookBudgetExhausted` exception).
- `scripts/register_test_look.py` (~90 lines).
- `tests/test_testlook.py` (11 tests).

### Command exit codes

- ruff, ruff format, mypy, pytest all green.
- Test count 210 -> 221 (+11).

### Live smoke

```
rm -f /tmp/test_looks.log
for i in 1 2 3; do
    uv run python scripts/register_test_look.py --reason "sprint 034 smoke $i" \
        --run-id "eval-smoke-$i" --log-path /tmp/test_looks.log
done
# 4th attempt should exit 2 + emit TEST_LOOK_BUDGET_EXHAUSTED
uv run python scripts/register_test_look.py --reason "one too many" \
    --run-id "eval-smoke-4" --log-path /tmp/test_looks.log
```

Verified. Registrations 1..3 exit 0. Fourth exits 2. Log file carries exactly three JSON lines. Trace of the fourth invocation: SESSION_INIT + TEST_LOOK_BUDGET_EXHAUSTED + SESSION_COMPLETE. Sink truncation from Sprint 029 keeps each invocation's trace to itself; the three successful TEST_LOOK_REGISTERED emits are proven by the log file plus the unit tests.

---

## observation contract

Required. Live smoke exercised both tag emit paths. `TEST_LOOK_REGISTERED` fires from `register_test_look` on the success path (three times via CLI, verified in `test_first_look_registers_and_emits`). `TEST_LOOK_BUDGET_EXHAUSTED` fires on the guard's raise path (once via CLI, verified in `test_fourth_look_emits_budget_exhausted_and_raises`).

---

## honest audit

**What actually landed.** A guard function that enforces the product-spec three-look budget by reading + appending to an on-disk log. Both vocabulary tags emit from real running code, one via CLI smoke, both via unit tests.

**What did not land.** No script currently wires `register_test_look` INTO the eval pipeline. When multi-month tokens open a test partition, `scripts/evaluate.py` (or a new `scripts/evaluate_test.py`) should call `register_test_look` before running any test-partition query. Sprint 034 provides the primitive; the wiring lands with the sprint that opens the test partition. Filed as a note in the sprint card so the future sprint remembers.

**pytest collection collision surfaced during first run.** `TestLookBudgetExhausted` and `TestLookRecord` both start with `Test`. Pytest's default `python_classes = ["Test*"]` collected them as test classes and errored (no test methods, wrong `__init__` signatures). Fixed by setting `__test__ = False` on both. Alternative: rename to `LookBudgetExhausted` and `LookRecord`. Kept the `Test` prefix because the domain-noun `TestLook` is the vocabulary's own term; adding `__test__ = False` is the standard opt-out.

---

## notes

**Log location.** Default is `experiments/test_looks.log`. CLI honors `--log-path` so the smoke can use `/tmp/test_looks.log` without touching the real budget. Any future automation MUST use the real path.

**Budget size.** Constant `DEFAULT_BUDGET = 3` matches product-spec §13. Test `test_budget_default_matches_product_spec` prevents accidental drift.

**Sprint 034 as cost calibration -- deferred.** Filed to BLACKBOARD's `## Surfaced for review`: cost calibration is blocked on real BBO or per-trade impact data. Two paths: (a) Databento / IEX Cloud DEEP feed / academic archive with real BBO; (b) canonical Kappa constant from published Almgren-Chriss with `kappa_se=0` and an honest note. Path (b) weakens the signal enough that a Reviewer might read the constant as a fit. Path (a) is a real dep + auth story.

---

## plan-mode review checklist

- [x] Scope one paragraph, one concept (test-look budget guard).
- [x] Files within hard rule 6 ceiling (1 code + 1 script + 1 test).
- [x] Signal contract cites v0.3 tags with real emit sites.
- [x] Observation contract present (functional-band); live smoke verified.
- [x] Determinism budget declared (bit-deterministic; log-based state, no RNG).
- [x] Cost-calibration halt filed to BLACKBOARD; pivot articulated in `## why not the natural next sprint`.

---

## close (2026-08-12)

Landed. Both testlook tags emit from live code. Test count 210 -> 221. Four tools green. Signals-drive: 46 of 56 tags now live.

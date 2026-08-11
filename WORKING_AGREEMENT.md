# WORKING_AGREEMENT.md — Price-Space LLM

*Per-project overrides on top of `sdd-kit-2/AGENTS.md`. The kit's discipline applies unchanged unless this file says otherwise.*

---

## Project identity

- **Project name:** Price-Space LLM
- **Project type:** Python ML training project. Multi-channel causal decoder transformer over 15-minute market state; 32-bucket vol-normalized return targets; cost-aware simulator.
- **Primary language:** Python 3.11+
- **Primary build commands:** `pytest tests/ -v` (unit tests); `python scripts/probe_channels.py`, `train.py`, `evaluate.py`, `simulate.py` (pipeline)
- **Adopted SDD kit version:** sdd-kit-2 (in-repo at `./sdd-kit-2/`)

---

## Project class

Primary: **Data science / ML training** (TECHNIQUES.md §2). Class techniques that apply from sprint 001: dataset version in `SESSION_INIT`; per-step / per-epoch / per-run signal strata; metric snapshot as artifact; determinism budget declared per artifact.

Secondary: **CLI / command-line** (TECHNIQUES.md §2). The pipeline runs as `scripts/*.py`. Exit codes are contract. Stdout carries data, stderr carries narration. `--signals-out=PATH` follows the flag-driven-instrumentation pattern.

---

## Project scope (verbatim from BLACKBOARD ## Decisions)

> Price-Space LLM v1: a causal decoder transformer over 15-minute multi-channel market state on SPY, predicting a 32-bucket vol-normalized forward return distribution, run through a cost-aware simulator on a 2024-01-01 through 2025-06-30 holdout. Success is defined by pre-registered gates in `specs/product-spec-v4.md` §"Success gates for v1" — validation NLL beats named baselines, ECE below 0.05, held-out Sharpe with attached standard error and block-bootstrap distribution, capacity above $1M, and no data leakage. Nine weeks of solo work, single A10/A100, ~$500 compute envelope.

Source specs: `specs/product-spec-v4.md`, `specs/technical-architecture-v4.md`. Review that produced v4: `reviews/review.md`. Prior-art positioning: `research/price-space-llm-analysis.md`.

---

## Canonical home registry

Per AGENTS.md hard rule 7. Seeded from `specs/technical-architecture-v4.md` §15 (Interfaces). Rows added as types stabilize; the Architect answers "where does this type live" via a row here.

| Type / module | Canonical home | Notes |
|---|---|---|
| `IngestionClient` | `src/ingestion/client.py` | Token-bucket rate limiter, sha256 cache. Constructor takes `source` and `cache_root`. |
| `ChannelFetcher` (Protocol) | `src/utils/interfaces.py` | `fetch(symbol, start, end, freq) -> pd.DataFrame`. |
| Per-channel fetchers (target, market_context, macro, options, event) | `src/ingestion/<channel>.py` | One module per channel; no `SPY` in the code, symbol is a parameter. |
| Alignment (as-of join on `known_at`) | `src/features/alignment.py` | Polars `join_asof`. |
| Causal feature computation | `src/features/*.py` | Every rolling window has `min_periods`; label-adjacent columns `.shift(1)`. |
| Expanding-window causal z-scorer | `src/features/normalize.py` | Fit on training only; frozen at end of training; state saved to `artifacts/{run_id}/normalizers.pt`. |
| `ReturnBucketizer` (operator, Layer 6) | `src/tokenizer/bucketizer.py` | 32-bucket default; `decode()` reads `artifacts/tokenizer/bucket_stats.json`. |
| `BucketStats` (frozen artifact, Layer 0) | `artifacts/tokenizer/bucket_stats.json` | Written once by `ReturnBucketizer.fit()` on training partition; read by evaluator, simulator, notebooks. Any downstream consumer reads from this file; nobody recomputes. |
| `NormalizerState` (frozen artifact, Layer 0) | `artifacts/{run_id}/normalizers.pt` | Written once by `src/features/normalize.py` at end of training; read by validation and test paths as-is. |
| `MarketStateEmbedder` (operator, Layer 6) | `src/tokenizer/embedder.py` | Per-channel `nn.Linear`, summed. No channel-type embedding inside the sum (v4 removal). Produces `MarketStateToken` (Layer 0 entity — runtime output, not frozen file). |
| `ChannelMixerEmbedder` | `src/tokenizer/embedder_mixer.py` | Ablation variant — one-block cross-channel attention. |
| `PriceSpaceLLM` | `src/model/transformer.py` | Causal decoder, RoPE, pre-LN, GELU, causal SDPA. |
| `GRUBaseline`, `LinearBaseline`, `MLPBaseline` | `src/model/baselines.py` | Baseline ladder. |
| `PriceSpaceDataset` | `src/training/dataset.py` | mmaps tokenized `.pt`; random-window sampling; per-position mask. |
| Training loop | `src/training/loop.py` | All-position CE; magnitude weight via `alpha`; checkpoint by validation NLL. |
| Simulator | `src/simulation/walker.py` + `src/simulation/cost.py` + `src/simulation/policy.py` | Bar-by-bar; fills at next bar's open. |
| Evaluation metrics | `src/evaluation/metrics.py` | NLL, ECE, Brier, RPS, dir-acc, regime split. |
| Vocabulary (locked v0.1) | `signals/0.1.json` | On disk for audit. Loader can request via `load_vocabulary(name="0.1.json")`. |
| Vocabulary (locked v0.2) | `signals/0.2.json` | Loader default from Sprint 009 forward. Delta from v0.1 in `signals/0.2-rationale.md`. |
| Signal emitter + vocabulary loader | `src/price_space_llm/signals.py` | Package-root placement, deliberate deviation from tech-arch §3's `src/utils/` inference. Observability is not a pipeline concern the spec dictates. Graduates to a sub-package (`observability/`) when the layer grows past one module. Per `reviews/full-review-round-1.md` §1.1. |
| Signal emitter | Vendored from `sdd-kit-2/lib/sdd.py` | Or a project-local extension if we need a JSONL sink. |

Type additions land here as they stabilize; renames land here as deprecation rows (never removals).

---

## External SDK bridge mappings

Per AGENTS.md hard rule 10 (halt with `bridge_mapping_required` if a sprint imports an SDK whose bridge mapping is not on file). Empty at project start; populated as each SDK is first used.

### PyTorch 2.4+

- **Import surface used in v1:** `torch`, `torch.nn`, `torch.nn.functional`, `torch.amp`, `torch.optim`, `torch.utils.data`.
- **Attention primitive:** `F.scaled_dot_product_attention(is_causal=True)` — dispatches to FlashAttention-2 where the backend supports it.
- **Determinism knobs:** `torch.use_deterministic_algorithms(True, warn_only=True)`; env `CUBLAS_WORKSPACE_CONFIG=:4096:8`.
- **Mixed precision:** `torch.amp.autocast('cuda', dtype=torch.bfloat16)`. bf16 needs no loss scaler.
- **Bridge mapping to fill on first use:** RoPE implementation — pick one library or copy the reference implementation into `src/model/rope.py` and note the source URL here.

### Alpha-Vantage-style financial-data MCP (primary data source)

- **Access:** MCP tools listed in the `mcp__claude_ai_Alpha_Vantage_MCP_Server__*` namespace (see the deferred-tools list; fetch schemas via `ToolSearch("select:<TOOL>")` before use).
- **Tools v1 uses:** `TIME_SERIES_INTRADAY`, `TIME_SERIES_DAILY_ADJUSTED`, `FX_INTRADAY`, `CURRENCY_EXCHANGE_RATE`, `CPI`, `FEDERAL_FUNDS_RATE`, `TREASURY_YIELD`, `UNEMPLOYMENT`, `NONFARM_PAYROLL`, `HISTORICAL_OPTIONS`, `HISTORICAL_PUT_CALL_RATIO`, `HISTORICAL_VOLUME_OPEN_INTEREST_RATIO`, `EARNINGS_CALENDAR`.
- **First use blocks on:** filling in per-tool argument surfaces, actual return shapes, timezone semantics, and revision behavior — captured by `scripts/probe_channels.py` and written to `data/manifests/channel_coverage.json`. That probe IS the bridge mapping for the MCP.
- **Fallback:** Polygon.io for 15-minute equity bars. Bridge mapping to fill when first invoked.

### Hydra 1.3+ / Pydantic v2

- Composable YAML config groups. Every hyperparameter lives under `configs/`. To fill: the exact Hydra invocation pattern (`@hydra.main` vs `compose()`) once the first config lands.

### Polars 1.x

- `join_asof` on `known_at` is the primitive. To fill: exact keyword surface (`by=`, `strategy='backward'`, tolerance semantics) on first use.

### Weights & Biases

- Project `price-space-llm`. Logs config, git SHA, data hash. To fill: the exact `wandb.init(...)` shape and the `wandb.log()` cadence once the first training run lands.

Every bridge mapping above is a stub. First sprint that imports the SDK halts with `bridge_mapping_required` if the actual surface is not documented here at that time. That halt is a feature — it forces us to read the SDK before writing against it, per soundfield's round 13/20-26 origin (Addendum C, external-SDK reverse-engineer-first).

**Dep-pin rule (per `reviews/full-review-round-1.md` §4.1).** The first sprint that imports each SDK adds the pin to `pyproject.toml § project.dependencies` in the same commit as the bridge mapping. Lower bounds match the tech-arch's declared minimum; upper bounds are the sprint author's call (typically none or a next-major cap). A sprint that adds an import without the pin, or a pin without the import, fails its plan-mode checklist.

---

## Vocabulary discipline

- **Validator-extras posture:** **strict**. Extra payload fields beyond `signals/0.1.json` raise. The project is disciplined enough that Katybird's strict posture fits; Trading System's documentation-only posture is not adopted.
- **View-payload universal convention:** N/A — no UI category.
- **Vocabulary location:** `signals/0.1.json`.
- **Vocabulary CI gate command:** to be authored in Sprint 1 (or Sprint 0 close) as `scripts/check_vocab.sh` — greps every `emit()` call site and asserts the tag exists in `signals/0.1.json`.

---

## Build and verification commands

Architect runs at sprint close; Agent does not.

- `pytest tests/ -v` — full test suite. Expected exit 0.
- `python scripts/probe_channels.py` — Phase 0 data-availability probe. Writes `data/manifests/channel_coverage.json`. Expected exit 0.
- `python scripts/calibrate_spread.py` — regresses Corwin-Schultz against measured BBO on the training window. Writes `artifacts/cost_calibration/spread_scaler.json`. Expected exit 0.
- `python scripts/calibrate_kappa.py` — OLS for the slippage coefficient with heteroskedasticity-robust SEs. Writes `artifacts/cost_calibration/kappa.json`. Expected exit 0.
- `python scripts/train.py experiments=<name>` — a training run. Expected exit 0; writes to `artifacts/{run_id}/`.
- `python scripts/evaluate.py run_id=<...>` — validation metrics.
- `python scripts/simulate.py run_id=<...>` — held-out simulator run. Uses one of the three test-look budget slots and appends to `experiments/test_looks.log`.
- Pre-commit hook `scripts/check_test_look.sh` — fails any commit whose changed configs contain dates ≥ 2024-01-01 without the literal token `[test-look]` in the message.
- `scripts/check_vocab.sh` (to author) — asserts no out-of-vocabulary tags in `src/`.

---

## Observation contract environment

The project has no UI. The observation contract for a sprint replaces "boot simulator + tap UI + screenshot" with:

- **Expected runtime signals** in the JSONL trace at `logs/{run_id}/signals.jsonl` (schema per `signals/0.1.json`).
- **Expected log substrings** in stderr from the pipeline script.
- **Expected metric artifacts** (JSON files under `artifacts/{run_id}/`) with named keys and value ranges.
- **Expected W&B log lines** where a metric passes through W&B.
- **Expected exit code** from the driving script.

The Architect (or CI) verifies by `grep` on the trace file and by JSON-schema check on the metrics artifact.

---

## Determinism budget (Data science class technique)

Declared per sprint. Two levels:

- **bit-deterministic** — same seed, same code, byte-identical weights and metrics. Used for pipeline scripts, tokenizer fitting, cost-calibration regressions, feature computation.
- **statistically deterministic** — same seed, metrics within tolerance (documented per-sprint, typically ±1% NLL, ±0.5% ECE). Used for GPU training runs where `use_deterministic_algorithms(True, warn_only=True)` cannot eliminate all nondeterminism.

Every training sprint declares which level it holds itself to. **Declaration site:** the sprint card's frontmatter carries `determinism_budget: bit-deterministic` or `determinism_budget: statistically-deterministic` alongside `id`, `phase`, `pass_kind`. A sprint that imports PyTorch, runs a training step, or writes a model artifact without a `determinism_budget` field halts at plan-mode review with `determinism_budget_missing`. Per `reviews/sdd-discipline-check-round-1.md` §4 — the rule fires from Sprint 007 forward.

---

## Hand-authorization log

Per AGENTS.md hard rule 10.

*(empty until first authorization)*

---

## Tone canon

The pipeline has no user-facing prose beyond CLI stderr. Rules:

- Lowercase first word in error messages.
- No exclamation marks anywhere.
- No emoji.
- File paths absolute in error messages.
- Metric prints use SI-style scientific notation for values below 1e-3 or above 1e6.

---

## Drift surface log

*Migrated here from BLACKBOARD `## Drift watchlist` when a pattern stabilizes as project-invariant.*

*(empty on project start)*

---

## Sprint cadence policy

- **Phase 0 (Vocabulary Session):** plan-mode — Architect drives interactively per `sdd-kit-2/grammar/BOOTSTRAP.md`.
- **Phase 1 (Ingestion + alignment, sprints 001-004):** plan-mode-per-sprint. First code in each layer earns Architect review.
- **Phase 2 (Features + tokenizer, sprints 005-008):** plan-mode-per-sprint for the first sprint; then auto-within-phase if the Architect declares it.
- **Phase 3 (Model + training, sprints 009-014):** plan-mode-per-sprint. Training runs cost real money; every card gets review.
- **Phase 4 (Simulator + evaluation, sprints 015-018):** plan-mode-per-sprint.
- **Phase 5 (Baselines + ablations, sprints 019-024):** auto-within-phase after the first sprint. Every ablation writes a Signal Report; the Architect reads at phase close.
- **Phase 6 (Held-out test, sprint 025+):** plan-mode. Every test-look is a Decision.

Phase boundaries and sprint counts are indicative; the Architect owns the final split.

---

## Project-specific halt conditions

In addition to the six base halt reasons in AGENTS.md:

- `probe_missing` — a sprint touches feature or ingestion code for a channel not represented in `data/manifests/channel_coverage.json`. Resume: Architect runs the probe.
- `calibration_missing` — a simulator sprint runs without both `artifacts/cost_calibration/spread_scaler.json` and `.../kappa.json` on disk. Resume: run the calibration scripts.
- `test_look_budget_exhausted` — a sprint proposes touching the held-out set and the test-looks log already has three entries. Resume: Architect ratifies a new budget entry with an explicit `[test-look]` in the commit or halts the sprint.

- `determinism_budget_missing` — a sprint that imports PyTorch, runs a training step, or writes a model artifact is missing the `determinism_budget` field in its frontmatter. Resume: add the field with the sprint's chosen level (`bit-deterministic` or `statistically-deterministic`) and re-dispatch.

- `hard_rule_stretch` — a sprint card proposes >2 code files, or bundles more than one concept, or otherwise breaks a numbered hard rule. Resume: Architect ratifies the stretch by writing to `## Decisions`, or the sprint splits per halt-and-articulate. Recorded from Sprint 007 forward per `reviews/sdd-discipline-check-round-1.md` §2.

---

## Custom techniques

Filled in as the project surfaces them. First candidates:

- **Metric snapshot as fixture.** When a training run produces a metric configuration the Architect ratifies as "known-good," the metrics JSON becomes a regression fixture under `tests/fixtures/metrics/`. A later run must match the fixture's keys and value ranges. From TECHNIQUES.md §2 Data science.

- **Frozen-artifact contract.** `artifacts/tokenizer/bucket_stats.json`, `artifacts/{run_id}/normalizers.pt`, `artifacts/cost_calibration/{spread_scaler,kappa}.json` are frozen — the sprint that produces each also produces the read-only test that any downstream code path reads through the artifact, never recomputes.

---

*WORKING_AGREEMENT.md — Price-Space LLM. Data science / ML training class + CLI class. Strict validator extras. Bridge mappings for PyTorch, the Alpha-Vantage MCP, Hydra, Pydantic, Polars, W&B — stubs filled in on first use. Canonical home registry seeded from tech-arch §15. Six phases planned; Vocabulary Session is Sprint 0.*

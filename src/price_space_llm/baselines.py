"""Three v1 baselines and the comparison harness.

Product-spec §Success gates registers three baseline comparisons:
- val NLL >= 10% better than `linear`
- val NLL >= 5% better than `target_only`
- val NLL >= 5% better than `gru_tcn` (deferred to a later sprint)

Sprint 033 ships `linear`, `target_only`, and `magnitude_weighted`
(the loss-variant of `linear` where each example's CE is scaled by
|log_return| of the target bucket -- product-spec's alpha_mag_weight
knob). `gru_tcn` is a separate architecture, out of scope here.

Deterministic evaluation: every valid start position in the val
partition contributes one (input, target) pair; probs at the
last-position prediction feed `compute_metric_set`. Same code path
as the transformer evaluator so the val_nll comparison is apples-to-apples.
"""

import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import torch
from torch import Tensor, nn
from torch.nn import functional as F

from price_space_llm.evaluation.metrics import MetricSet, compute_metric_set

if TYPE_CHECKING:
    from price_space_llm.tokenizer.bucketize import BucketStats

BaselineKind = Literal["linear", "target_only", "magnitude_weighted", "mlp", "gru"]

# Product-spec pre-registered gate: minimum val-NLL improvement of the
# transformer over each baseline.
REQUIRED_DELTA_PCT: dict[BaselineKind, float] = {
    "linear": 10.0,
    "target_only": 5.0,
    "magnitude_weighted": 5.0,
    "mlp": 5.0,  # Sprint 059: matches the target_only / gru_tcn tier.
    "gru": 5.0,  # Sprint 060: matches product-spec gru_tcn 5% gate.
}


@dataclass(slots=True, frozen=True, kw_only=True)
class BaselineFitResult:
    kind: BaselineKind
    baseline_run_id: str
    val_metrics: MetricSet
    n_train_examples: int
    n_val_examples: int
    fit_elapsed_seconds: float


@dataclass(slots=True, frozen=True, kw_only=True)
class BaselineComparisonResult:
    kind: BaselineKind
    baseline_run_id: str
    baseline_val_nll: float
    transformer_val_nll: float
    delta_pct: float
    required_delta_pct: float
    meets_gate: bool


class LinearBaseline(nn.Module):
    """Flatten one-hot context tokens; project to `vocab_size` logits. No hidden layer."""

    def __init__(self, vocab_size: int, context_len: int) -> None:
        super().__init__()
        self.vocab_size = vocab_size
        self.context_len = context_len
        self.linear = nn.Linear(context_len * vocab_size, vocab_size)

    def forward(self, tokens: Tensor) -> Tensor:  # (B, T) -> (B, V)
        one_hot = F.one_hot(tokens, self.vocab_size).float()
        flat = one_hot.reshape(tokens.shape[0], -1)
        return self.linear(flat)  # type: ignore[no-any-return]


class MLPBaseline(nn.Module):
    """Sprint 059: small 3-layer MLP over flattened one-hot context tokens.

    Architecture per product-spec § Baselines: `Linear(T*V, 128) → GELU →
    Linear(128, 64) → GELU → Linear(64, 32) → Linear(32, V)`. Predicts next
    token from `context_len` prior tokens, matching `LinearBaseline`'s API.
    """

    def __init__(self, vocab_size: int, context_len: int) -> None:
        super().__init__()
        self.vocab_size = vocab_size
        self.context_len = context_len
        self.trunk = nn.Sequential(
            nn.Linear(context_len * vocab_size, 128),
            nn.GELU(),
            nn.Linear(128, 64),
            nn.GELU(),
            nn.Linear(64, 32),
        )
        self.head = nn.Linear(32, vocab_size)

    def forward(self, tokens: Tensor) -> Tensor:  # (B, T) -> (B, V)
        one_hot = F.one_hot(tokens, self.vocab_size).float()
        flat = one_hot.reshape(tokens.shape[0], -1)
        h = self.trunk(flat)
        return self.head(h)  # type: ignore[no-any-return]


class GRUBaseline(nn.Module):
    """Sprint 060: causal GRU baseline per product-spec § 10 code sketch.

    One hidden layer at 128 units. Input: (B, T) integer bucket-ids →
    `nn.Embedding(V, 128)` → `nn.GRU(128, 128, batch_first=True)` → take the
    last timestep hidden state → `nn.Linear(128, V)` head. Causal by
    construction: GRU is left-to-right; the final hidden state summarizes
    tokens 0..T-1 to predict the next token.

    Params: `V*128 + (3 * 128 * (128 + 128 + 1)) + (128 * V + V)` ≈ ~1M for
    V=32 vocab. Matches product-spec § Baselines "GRU (1 hidden layer, 128
    units, causal, ~1M params)."
    """

    def __init__(self, vocab_size: int, context_len: int, hidden_size: int = 128) -> None:
        super().__init__()
        self.vocab_size = vocab_size
        self.context_len = context_len
        self.hidden_size = hidden_size
        self.embedding = nn.Embedding(vocab_size, hidden_size)
        self.gru = nn.GRU(hidden_size, hidden_size, num_layers=1, batch_first=True)
        self.head = nn.Linear(hidden_size, vocab_size)

    def forward(self, tokens: Tensor) -> Tensor:  # (B, T) -> (B, V)
        emb = self.embedding(tokens)  # (B, T, H)
        _, h_n = self.gru(emb)  # h_n: (1, B, H)
        h = h_n.squeeze(0)  # (B, H)
        return self.head(h)  # type: ignore[no-any-return]


class TargetOnlyBaseline:
    """Marginal-frequency predictor. Fit = count; predict = broadcast."""

    def __init__(self, probs: Tensor) -> None:
        # probs shape (V,), sums to 1.
        self.probs = probs

    @property
    def vocab_size(self) -> int:
        return int(self.probs.shape[0])

    def predict(self, n: int) -> Tensor:
        return self.probs.unsqueeze(0).expand(n, -1)  # (N, V)


def _build_windows(tokens: list[int], context_len: int) -> tuple[Tensor, Tensor]:
    """Return (inputs, last_targets) covering every valid start position."""
    n_valid = len(tokens) - context_len
    if n_valid < 1:
        return torch.zeros((0, context_len), dtype=torch.long), torch.zeros((0,), dtype=torch.long)
    t = torch.tensor(tokens, dtype=torch.long)
    inputs = torch.stack([t[s : s + context_len] for s in range(n_valid)])
    targets = torch.stack([t[s + context_len] for s in range(n_valid)])
    return inputs, targets


def fit_linear(
    train_tokens: list[int],
    *,
    vocab_size: int,
    context_len: int,
    n_steps: int = 200,
    batch_size: int = 32,
    lr: float = 1e-3,
    seed: int = 0,
    magnitude_weights: Tensor | None = None,
) -> LinearBaseline:
    """Adam-fit a LinearBaseline on all valid windows. Sampling is deterministic given the seed.

    `magnitude_weights` (optional): shape (vocab_size,). Each example's CE loss is scaled by
    `magnitude_weights[target]`. Passing None gives the plain-linear baseline; passing a
    non-uniform vector gives the magnitude-weighted variant.
    """
    torch.manual_seed(seed)
    generator = torch.Generator()
    generator.manual_seed(seed)
    inputs, targets = _build_windows(train_tokens, context_len)
    if inputs.shape[0] == 0:
        raise ValueError(f"need at least {context_len + 1} tokens; got {len(train_tokens)}")
    model = LinearBaseline(vocab_size, context_len)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    n = inputs.shape[0]
    for _ in range(n_steps):
        idx = torch.randint(0, n, (batch_size,), generator=generator)
        batch_in = inputs[idx]
        batch_tgt = targets[idx]
        logits = model(batch_in)
        if magnitude_weights is None:
            loss = F.cross_entropy(logits, batch_tgt)
        else:
            per_example = F.cross_entropy(logits, batch_tgt, reduction="none")
            weights = magnitude_weights[batch_tgt]
            loss = (per_example * weights).mean()
        optimizer.zero_grad(set_to_none=True)
        loss.backward()  # type: ignore[no-untyped-call]
        optimizer.step()
    return model


def fit_target_only(train_tokens: list[int], vocab_size: int) -> TargetOnlyBaseline:
    """Count marginal bucket frequencies in the training tokens."""
    counts = torch.zeros(vocab_size, dtype=torch.float64)
    for t in train_tokens:
        if 0 <= t < vocab_size:
            counts[t] += 1
    total = counts.sum()
    if total == 0:
        raise ValueError("cannot fit target_only on zero training tokens")
    return TargetOnlyBaseline((counts / total).to(torch.float32))


def eval_linear(
    model: LinearBaseline,
    val_tokens: list[int],
    context_len: int,
    vocab_size: int,
) -> MetricSet:
    """Deterministic eval over every valid window in val_tokens. Returns the seven metrics."""
    inputs, targets = _build_windows(val_tokens, context_len)
    if inputs.shape[0] == 0:
        return _empty_metrics()
    model.eval()
    with torch.no_grad():
        logits = model(inputs)
        probs = F.softmax(logits, dim=-1)
    return compute_metric_set(probs, targets, vocab_size)


def fit_mlp(
    train_tokens: list[int],
    *,
    vocab_size: int,
    context_len: int,
    n_steps: int = 200,
    batch_size: int = 32,
    lr: float = 1e-3,
    seed: int = 0,
) -> MLPBaseline:
    """Sprint 059: Adam-fit `MLPBaseline` on all valid windows. Deterministic given seed."""
    torch.manual_seed(seed)
    generator = torch.Generator().manual_seed(seed)
    inputs, targets = _build_windows(train_tokens, context_len)
    if inputs.shape[0] == 0:
        raise ValueError(
            f"need at least {context_len + 1} tokens to build one window; got {len(train_tokens)}"
        )
    model = MLPBaseline(vocab_size, context_len)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    n = inputs.shape[0]
    for _ in range(n_steps):
        idx = torch.randint(0, n, (batch_size,), generator=generator)
        logits = model(inputs[idx])
        loss = F.cross_entropy(logits, targets[idx])
        optimizer.zero_grad(set_to_none=True)
        loss.backward()  # type: ignore[no-untyped-call]
        optimizer.step()
    return model


def eval_mlp(
    model: MLPBaseline,
    val_tokens: list[int],
    context_len: int,
    vocab_size: int,
) -> MetricSet:
    """Sprint 059: same eval shape as eval_linear (softmax then compute_metric_set)."""
    model.eval()
    inputs, targets = _build_windows(val_tokens, context_len)
    if targets.shape[0] == 0:
        return _empty_metrics()
    with torch.no_grad():
        probs = F.softmax(model(inputs), dim=-1)
    return compute_metric_set(probs, targets, vocab_size)


def fit_gru(
    train_tokens: list[int],
    *,
    vocab_size: int,
    context_len: int,
    hidden_size: int = 128,
    n_steps: int = 200,
    batch_size: int = 32,
    lr: float = 1e-3,
    seed: int = 0,
) -> GRUBaseline:
    """Sprint 060: Adam-fit `GRUBaseline`. Deterministic given seed."""
    torch.manual_seed(seed)
    generator = torch.Generator().manual_seed(seed)
    inputs, targets = _build_windows(train_tokens, context_len)
    if inputs.shape[0] == 0:
        raise ValueError(f"need at least {context_len + 1} tokens; got {len(train_tokens)}")
    model = GRUBaseline(vocab_size, context_len, hidden_size=hidden_size)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    n = inputs.shape[0]
    for _ in range(n_steps):
        idx = torch.randint(0, n, (batch_size,), generator=generator)
        logits = model(inputs[idx])
        loss = F.cross_entropy(logits, targets[idx])
        optimizer.zero_grad(set_to_none=True)
        loss.backward()  # type: ignore[no-untyped-call]
        optimizer.step()
    return model


def eval_gru(
    model: GRUBaseline,
    val_tokens: list[int],
    context_len: int,
    vocab_size: int,
) -> MetricSet:
    """Sprint 060: same eval shape as eval_linear / eval_mlp."""
    model.eval()
    inputs, targets = _build_windows(val_tokens, context_len)
    if targets.shape[0] == 0:
        return _empty_metrics()
    with torch.no_grad():
        probs = F.softmax(model(inputs), dim=-1)
    return compute_metric_set(probs, targets, vocab_size)


def eval_target_only(
    baseline: TargetOnlyBaseline,
    val_tokens: list[int],
    context_len: int,
    vocab_size: int,
) -> MetricSet:
    """Broadcast the marginal probs to every val window; score against the target tokens."""
    _, targets = _build_windows(val_tokens, context_len)
    if targets.shape[0] == 0:
        return _empty_metrics()
    probs = baseline.predict(targets.shape[0])
    return compute_metric_set(probs, targets, vocab_size)


def compute_magnitude_weights(bucket_edges: list[float], vocab_size: int) -> Tensor:
    """Approximate |log_return| at each bucket_id via the mid-edge value.

    Bucket 0 is the leftmost, bucket vocab_size-1 the rightmost. Interior buckets use
    (edge[i-1] + edge[i]) / 2 as the mid-value; edge buckets use the outer edge. Weights
    are absolute values, normalised so the mean weight is 1 (keeps loss scale comparable
    to unweighted CE).

    Sprint 056: the midpoint-fake path stays for back-compat. Prefer
    `compute_magnitude_weights_from_stats(bucket_stats)` which reads real per-bucket
    `train_mean` values from the extended `bucket_stats.json` per spec § 7.1.
    """
    if len(bucket_edges) != vocab_size - 1:
        raise ValueError(
            f"expected {vocab_size - 1} edges for {vocab_size} buckets; got {len(bucket_edges)}"
        )
    mids: list[float] = []
    for i in range(vocab_size):
        if i == 0:
            mids.append(bucket_edges[0])
        elif i == vocab_size - 1:
            mids.append(bucket_edges[-1])
        else:
            mids.append((bucket_edges[i - 1] + bucket_edges[i]) / 2)
    weights = torch.tensor([abs(m) for m in mids], dtype=torch.float32)
    mean_w = weights.mean()
    if mean_w == 0:
        return torch.ones_like(weights)
    return weights / mean_w


def compute_magnitude_weights_from_stats(bucket_stats: "BucketStats") -> Tensor:
    """Sprint 056: real per-bucket `|train_mean|` weights, normalized to mean 1.

    Reads `bucket_stats.per_bucket[i].train_mean` (spec § 7.1). NaN means (empty
    bucket) collapse to zero weight before normalization. Prefer this over
    `compute_magnitude_weights(edges, vocab_size)` — the edge-midpoint fake
    over-weights the outer tails and under-weights the fat middle when the
    quantile edges are asymmetric.
    """
    import math

    if not bucket_stats.per_bucket:
        raise ValueError(
            "bucket_stats.per_bucket is empty; regenerate with Sprint 056+ "
            "tokenizer to populate per-bucket train_mean"
        )
    values: list[float] = []
    for row in bucket_stats.per_bucket:
        if math.isnan(row.train_mean):
            values.append(0.0)
        else:
            values.append(abs(row.train_mean))
    weights = torch.tensor(values, dtype=torch.float32)
    mean_w = weights.mean()
    if mean_w == 0:
        return torch.ones_like(weights)
    return weights / mean_w


def fit_and_eval(
    kind: BaselineKind,
    train_tokens: list[int],
    val_tokens: list[int],
    *,
    vocab_size: int,
    context_len: int,
    bucket_edges: list[float] | None = None,
    seed: int = 0,
) -> BaselineFitResult:
    """One-call fit + eval + wrap in BaselineFitResult. Kind selects the model + loss."""
    t0 = time.monotonic()
    baseline_run_id = f"baseline-{kind}-seed{seed:04d}"
    if kind == "target_only":
        target_baseline = fit_target_only(train_tokens, vocab_size)
        metrics = eval_target_only(target_baseline, val_tokens, context_len, vocab_size)
    elif kind == "linear":
        linear = fit_linear(train_tokens, vocab_size=vocab_size, context_len=context_len, seed=seed)
        metrics = eval_linear(linear, val_tokens, context_len, vocab_size)
    elif kind == "mlp":
        mlp = fit_mlp(train_tokens, vocab_size=vocab_size, context_len=context_len, seed=seed)
        metrics = eval_mlp(mlp, val_tokens, context_len, vocab_size)
    elif kind == "gru":
        gru = fit_gru(train_tokens, vocab_size=vocab_size, context_len=context_len, seed=seed)
        metrics = eval_gru(gru, val_tokens, context_len, vocab_size)
    elif kind == "magnitude_weighted":
        if bucket_edges is None:
            raise ValueError("magnitude_weighted requires bucket_edges")
        weights = compute_magnitude_weights(bucket_edges, vocab_size)
        linear = fit_linear(
            train_tokens,
            vocab_size=vocab_size,
            context_len=context_len,
            seed=seed,
            magnitude_weights=weights,
        )
        metrics = eval_linear(linear, val_tokens, context_len, vocab_size)
    else:
        raise ValueError(f"unknown baseline kind: {kind!r}")

    n_train_examples = max(0, len(train_tokens) - context_len)
    n_val_examples = max(0, len(val_tokens) - context_len)
    return BaselineFitResult(
        kind=kind,
        baseline_run_id=baseline_run_id,
        val_metrics=metrics,
        n_train_examples=n_train_examples,
        n_val_examples=n_val_examples,
        fit_elapsed_seconds=time.monotonic() - t0,
    )


def compare_to_transformer(
    fit_result: BaselineFitResult,
    transformer_val_nll: float,
) -> BaselineComparisonResult:
    """Compute delta_pct + meets_gate for a baseline vs the transformer's val_nll.

    delta_pct > 0 when the transformer has a lower NLL than the baseline (transformer
    is better). meets_gate is true when delta_pct >= REQUIRED_DELTA_PCT[kind].
    """
    baseline_nll = fit_result.val_metrics.nll
    if baseline_nll <= 0:
        # Degenerate: baseline is perfect. Transformer cannot beat it in percentage terms.
        delta_pct = 0.0
    else:
        delta_pct = (baseline_nll - transformer_val_nll) / baseline_nll * 100.0
    required = REQUIRED_DELTA_PCT[fit_result.kind]
    return BaselineComparisonResult(
        kind=fit_result.kind,
        baseline_run_id=fit_result.baseline_run_id,
        baseline_val_nll=baseline_nll,
        transformer_val_nll=transformer_val_nll,
        delta_pct=delta_pct,
        required_delta_pct=required,
        meets_gate=delta_pct >= required,
    )


def load_transformer_val_nll(metrics_json_path: Path) -> float:
    """Extract pooled val NLL from a Sprint 032 metrics.json (weighted by n_examples per regime)."""
    import json

    doc = json.loads(metrics_json_path.read_text(encoding="utf-8"))
    val_per_regime = doc.get("metrics", {}).get("val", {})
    if not val_per_regime:
        raise ValueError(f"metrics.json has no val split: {metrics_json_path}")
    total_nll = 0.0
    total_n = 0
    for regime_stats in val_per_regime.values():
        n = int(regime_stats.get("n_examples", 0))
        if n == 0:
            continue
        total_nll += float(regime_stats["nll"]) * n
        total_n += n
    if total_n == 0:
        raise ValueError(f"metrics.json has zero val examples across regimes: {metrics_json_path}")
    return total_nll / total_n


def _empty_metrics() -> MetricSet:
    return MetricSet(
        nll=0.0, ece=0.0, brier=0.0, rps=0.0, dir_acc=0.0, top1=0.0, top3=0.0, n_examples=0
    )

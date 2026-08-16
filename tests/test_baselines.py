"""Tests for the three baselines + comparison harness."""

import json
import math
from pathlib import Path

import pytest
import torch

from price_space_llm.baselines import (
    REQUIRED_DELTA_PCT,
    BaselineFitResult,
    LinearBaseline,
    TargetOnlyBaseline,
    compare_to_transformer,
    compute_magnitude_weights,
    eval_linear,
    eval_target_only,
    fit_and_eval,
    fit_linear,
    fit_target_only,
    load_transformer_val_nll,
)
from price_space_llm.evaluation.metrics import MetricSet


def _synthetic_tokens(n: int, vocab_size: int = 32) -> list[int]:
    return [i % vocab_size for i in range(n)]


# LinearBaseline ----------------------------------------------------------


def test_linear_baseline_forward_returns_correct_shape():
    model = LinearBaseline(vocab_size=32, context_len=8)
    tokens = torch.randint(0, 32, (4, 8))
    logits = model(tokens)
    assert logits.shape == (4, 32)


def test_fit_linear_reduces_loss_from_random_init():
    tokens = _synthetic_tokens(800)
    torch.manual_seed(0)
    initial = LinearBaseline(vocab_size=32, context_len=16)
    with torch.no_grad():
        inputs = torch.tensor([tokens[s : s + 16] for s in range(100)], dtype=torch.long)
        targets = torch.tensor([tokens[s + 16] for s in range(100)], dtype=torch.long)
        init_loss = float(torch.nn.functional.cross_entropy(initial(inputs), targets).item())
    fitted = fit_linear(tokens, vocab_size=32, context_len=16, n_steps=200, batch_size=32, seed=0)
    with torch.no_grad():
        fit_loss = float(torch.nn.functional.cross_entropy(fitted(inputs), targets).item())
    assert fit_loss < init_loss


def test_fit_linear_rejects_too_few_tokens():
    with pytest.raises(ValueError, match="need at least"):
        fit_linear([1, 2, 3], vocab_size=4, context_len=8)


# TargetOnlyBaseline ------------------------------------------------------


def test_fit_target_only_matches_marginal_distribution():
    tokens = [0, 0, 0, 1, 1, 2]
    baseline = fit_target_only(tokens, vocab_size=4)
    assert baseline.probs.tolist() == pytest.approx([3 / 6, 2 / 6, 1 / 6, 0.0])


def test_fit_target_only_rejects_empty():
    with pytest.raises(ValueError, match="zero training tokens"):
        fit_target_only([], vocab_size=4)


def test_predict_broadcasts_probs_to_n_rows():
    probs = torch.tensor([0.1, 0.5, 0.4])
    baseline = TargetOnlyBaseline(probs)
    out = baseline.predict(5)
    assert out.shape == (5, 3)
    assert torch.allclose(out[0], probs)
    assert torch.allclose(out[4], probs)


# Magnitude weights -------------------------------------------------------


def test_magnitude_weights_length_equals_vocab_size():
    edges = [0.1 * i for i in range(-15, 16)]  # 31 edges → 32 buckets
    w = compute_magnitude_weights(edges, vocab_size=32)
    assert w.shape == (32,)


def test_magnitude_weights_rejects_wrong_edge_count():
    with pytest.raises(ValueError, match="expected"):
        compute_magnitude_weights([0.0, 0.5], vocab_size=32)


def test_magnitude_weights_mean_normalised_to_one():
    edges = [0.1 * i for i in range(-15, 16)]
    w = compute_magnitude_weights(edges, vocab_size=32)
    assert float(w.mean()) == pytest.approx(1.0, abs=1e-6)


def test_magnitude_weights_are_larger_at_extremes():
    """The tails represent larger |log_return| values so weights should exceed the middle."""
    edges = [0.001 * i for i in range(-15, 16)]
    w = compute_magnitude_weights(edges, vocab_size=32)
    assert float(w[0]) > float(w[16])
    assert float(w[-1]) > float(w[16])


# Eval --------------------------------------------------------------------


def test_eval_linear_returns_metric_set():
    tokens = _synthetic_tokens(400)
    model = fit_linear(tokens, vocab_size=32, context_len=16, n_steps=50, seed=0)
    metrics = eval_linear(model, tokens[300:], context_len=16, vocab_size=32)
    assert isinstance(metrics, MetricSet)
    assert metrics.n_examples > 0
    assert metrics.nll > 0


def test_eval_target_only_returns_metric_set():
    tokens = _synthetic_tokens(400)
    baseline = fit_target_only(tokens[:300], vocab_size=32)
    metrics = eval_target_only(baseline, tokens[300:], context_len=16, vocab_size=32)
    assert isinstance(metrics, MetricSet)
    assert metrics.n_examples > 0
    # For a uniform-marginal on 32 buckets, NLL should be near log(32).
    assert metrics.nll == pytest.approx(math.log(32), abs=0.5)


# fit_and_eval ------------------------------------------------------------


def test_fit_and_eval_produces_run_id_and_metrics():
    tokens = _synthetic_tokens(500)
    result = fit_and_eval(
        "target_only",
        tokens[:400],
        tokens[400:],
        vocab_size=32,
        context_len=16,
        seed=0,
    )
    assert isinstance(result, BaselineFitResult)
    assert result.kind == "target_only"
    assert result.baseline_run_id == "baseline-target_only-seed0000"
    assert result.n_train_examples > 0
    assert result.n_val_examples > 0


def test_fit_and_eval_magnitude_weighted_requires_bucket_edges():
    tokens = _synthetic_tokens(500)
    with pytest.raises(ValueError, match="bucket_edges"):
        fit_and_eval(
            "magnitude_weighted",
            tokens[:400],
            tokens[400:],
            vocab_size=32,
            context_len=16,
            seed=0,
        )


def test_fit_and_eval_all_three_kinds():
    tokens = _synthetic_tokens(500)
    edges = [0.001 * i for i in range(-15, 16)]
    for kind in ("linear", "target_only", "magnitude_weighted"):
        kind = kind  # type: ignore[assignment]
        result = fit_and_eval(
            kind,  # type: ignore[arg-type]
            tokens[:400],
            tokens[400:],
            vocab_size=32,
            context_len=16,
            bucket_edges=edges if kind == "magnitude_weighted" else None,
            seed=0,
        )
        assert result.val_metrics.n_examples > 0


# Comparison --------------------------------------------------------------


def test_compare_computes_delta_pct_positive_when_transformer_beats():
    fit_result = BaselineFitResult(
        kind="linear",
        baseline_run_id="test-linear",
        val_metrics=MetricSet(
            nll=3.5, ece=0.0, brier=0.0, rps=0.0, dir_acc=0.0, top1=0.0, top3=0.0, n_examples=10
        ),
        n_train_examples=100,
        n_val_examples=10,
        fit_elapsed_seconds=0.1,
    )
    comp = compare_to_transformer(fit_result, transformer_val_nll=3.15)
    # (3.5 - 3.15) / 3.5 * 100 = 10.0
    assert comp.delta_pct == pytest.approx(10.0, abs=1e-6)
    assert comp.required_delta_pct == 10.0
    assert comp.meets_gate is True


def test_compare_reports_negative_delta_when_baseline_beats_transformer():
    fit_result = BaselineFitResult(
        kind="target_only",
        baseline_run_id="test-to",
        val_metrics=MetricSet(
            nll=3.0, ece=0.0, brier=0.0, rps=0.0, dir_acc=0.0, top1=0.0, top3=0.0, n_examples=10
        ),
        n_train_examples=100,
        n_val_examples=10,
        fit_elapsed_seconds=0.0,
    )
    comp = compare_to_transformer(fit_result, transformer_val_nll=3.6)
    assert comp.delta_pct < 0
    assert comp.meets_gate is False


def test_required_delta_pct_matches_product_spec_gates():
    assert REQUIRED_DELTA_PCT["linear"] == 10.0
    assert REQUIRED_DELTA_PCT["target_only"] == 5.0
    assert REQUIRED_DELTA_PCT["magnitude_weighted"] == 5.0


# load_transformer_val_nll ------------------------------------------------


def test_load_transformer_val_nll_pools_regimes_weighted_by_examples(tmp_path: Path):
    metrics = {
        "metrics": {
            "val": {
                "low": {"nll": 4.0, "n_examples": 10},
                "mid": {"nll": 3.0, "n_examples": 20},
                "high": {"nll": 5.0, "n_examples": 10},
            }
        }
    }
    path = tmp_path / "metrics.json"
    path.write_text(json.dumps(metrics))
    # Weighted mean: (4*10 + 3*20 + 5*10) / 40 = 150/40 = 3.75
    assert load_transformer_val_nll(path) == pytest.approx(3.75)


def test_load_transformer_val_nll_ignores_empty_regimes(tmp_path: Path):
    metrics = {
        "metrics": {
            "val": {
                "low": {"nll": 4.0, "n_examples": 0},
                "mid": {"nll": 3.0, "n_examples": 20},
                "high": {"nll": 5.0, "n_examples": 0},
            }
        }
    }
    path = tmp_path / "metrics.json"
    path.write_text(json.dumps(metrics))
    assert load_transformer_val_nll(path) == pytest.approx(3.0)


def test_load_transformer_val_nll_raises_when_no_val(tmp_path: Path):
    path = tmp_path / "metrics.json"
    path.write_text(json.dumps({"metrics": {"train": {}}}))
    with pytest.raises(ValueError, match="no val split"):
        load_transformer_val_nll(path)


def test_load_transformer_val_nll_raises_on_zero_total_examples(tmp_path: Path):
    metrics = {
        "metrics": {
            "val": {
                "low": {"nll": 4.0, "n_examples": 0},
                "mid": {"nll": 3.0, "n_examples": 0},
                "high": {"nll": 5.0, "n_examples": 0},
            }
        }
    }
    path = tmp_path / "metrics.json"
    path.write_text(json.dumps(metrics))
    with pytest.raises(ValueError, match="zero val examples"):
        load_transformer_val_nll(path)


# Determinism -------------------------------------------------------------


def test_fit_linear_is_deterministic_with_seed():
    tokens = _synthetic_tokens(400)
    m1 = fit_linear(tokens, vocab_size=32, context_len=16, n_steps=50, seed=7)
    m2 = fit_linear(tokens, vocab_size=32, context_len=16, n_steps=50, seed=7)
    for p1, p2 in zip(m1.parameters(), m2.parameters(), strict=True):
        assert torch.allclose(p1, p2, atol=1e-6)


# Sprint 056: compute_magnitude_weights_from_stats ---------------------------


def test_compute_magnitude_weights_from_stats_uses_train_mean():
    """Sprint 056: weights are |train_mean| per bucket, normalized to mean 1."""
    from price_space_llm.baselines import compute_magnitude_weights_from_stats
    from price_space_llm.tokenizer.bucketize import BucketRow, BucketStats

    rows = tuple(
        BucketRow(
            lower=None if i == 0 else float(i - 1),
            upper=None if i == 3 else float(i),
            train_mean=[-2.0, -0.5, 0.5, 2.0][i],
            train_median=0.0,
            train_frequency=0.25,
        )
        for i in range(4)
    )
    stats = BucketStats(
        n_buckets=32,  # value cosmetic; per_bucket controls length
        target_symbol="SPY",
        training_range_start="2015-01-05",
        training_range_end="2022-12-30",
        train_partition_row_count=100,
        edges=(0.0, 1.0, 2.0),
        per_bucket=rows,
    )
    w = compute_magnitude_weights_from_stats(stats)
    # abs means = [2.0, 0.5, 0.5, 2.0] → mean 1.25 → weights [1.6, 0.4, 0.4, 1.6].
    assert w.shape == (4,)
    assert abs(w.mean().item() - 1.0) < 1e-6
    assert abs(w[0].item() - 1.6) < 1e-6
    assert abs(w[1].item() - 0.4) < 1e-6


def test_compute_magnitude_weights_from_stats_zero_means_returns_ones():
    from price_space_llm.baselines import compute_magnitude_weights_from_stats
    from price_space_llm.tokenizer.bucketize import BucketRow, BucketStats

    rows = tuple(
        BucketRow(
            lower=None if i == 0 else float(i - 1),
            upper=None if i == 3 else float(i),
            train_mean=0.0,
            train_median=0.0,
            train_frequency=0.25,
        )
        for i in range(4)
    )
    stats = BucketStats(
        n_buckets=32,
        target_symbol="SPY",
        training_range_start="2015-01-05",
        training_range_end="2022-12-30",
        train_partition_row_count=100,
        edges=(0.0, 1.0, 2.0),
        per_bucket=rows,
    )
    w = compute_magnitude_weights_from_stats(stats)
    assert torch.allclose(w, torch.ones(4), atol=1e-6)


def test_compute_magnitude_weights_from_stats_rejects_empty_per_bucket():
    """Sprint 056: rejects legacy stats missing the per_bucket field."""
    from price_space_llm.baselines import compute_magnitude_weights_from_stats
    from price_space_llm.tokenizer.bucketize import BucketStats

    stats = BucketStats(
        n_buckets=32,
        target_symbol="SPY",
        training_range_start="2015-01-05",
        training_range_end="2022-12-30",
        train_partition_row_count=100,
        edges=(0.0, 1.0, 2.0),
        per_bucket=(),
    )
    with pytest.raises(ValueError, match="per_bucket is empty"):
        compute_magnitude_weights_from_stats(stats)

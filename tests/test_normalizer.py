"""Sprint 054: frozen normalizer -- fit + write + load + apply + emit contracts."""

from __future__ import annotations

from pathlib import Path

import pytest
import torch

from price_space_llm.model.dataset import TokenizedArtifact
from price_space_llm.normalizer import (
    FrozenNormalizer,
    apply_frozen_normalizer,
    fit_frozen_normalizer,
    load_frozen_normalizer,
    write_frozen_normalizer,
)
from price_space_llm.signals import StrictSignalEmitter, load_vocabulary


def _fresh_emitter(max_buffer: int = 4096) -> StrictSignalEmitter:
    return StrictSignalEmitter(load_vocabulary(), max_buffer=max_buffer)


def _artifact(n_rows: int = 100) -> TokenizedArtifact:
    """Two-channel synthetic artifact with a valid target on every row."""
    torch.manual_seed(0)
    return TokenizedArtifact(
        features={
            "target__SPY": torch.randn(n_rows, 4),
            "market_context__VIX": torch.randn(n_rows, 3),
        },
        targets=torch.randint(0, 32, (n_rows,), dtype=torch.int64),
        vol=torch.zeros(n_rows, dtype=torch.float32),
        timestamps=torch.arange(n_rows, dtype=torch.int64),
        is_overnight_gap=None,
        mask=torch.ones(n_rows, dtype=torch.bool),
        channel_names=("market_context__VIX", "target__SPY"),
        meta={"run_id": "test"},
    )


# fit --------------------------------------------------------------------


def test_fit_shapes_and_feature_count():
    """Sprint 054: mean + std per channel with shapes matching F_c; feature_count = Σ_c F_c."""
    artifact = _artifact(n_rows=200)
    e = _fresh_emitter()
    normalizer = fit_frozen_normalizer(
        artifact,
        training_range_start="2024-01-01",
        training_range_end="2024-12-31",
        emitter=e,
        run_id="test-fit",
    )
    assert set(normalizer.mean.keys()) == {"target__SPY", "market_context__VIX"}
    assert normalizer.mean["target__SPY"].shape == (4,)
    assert normalizer.std["target__SPY"].shape == (4,)
    assert normalizer.mean["market_context__VIX"].shape == (3,)
    assert normalizer.feature_count == 4 + 3


def test_fit_ignores_null_target_rows():
    """Rows where targets == -100 are skipped in the fit."""
    torch.manual_seed(0)
    n_rows = 200
    features = {"a": torch.ones(n_rows, 1) * 100.0}
    # Half the rows carry a real target; half carry -100.
    targets = torch.full((n_rows,), -100, dtype=torch.int64)
    targets[:100] = 5
    # In the "valid" rows, override the constant feature to 10.0 so mean is 10.
    features["a"][:100] = 10.0
    artifact = TokenizedArtifact(
        features=features,
        targets=targets,
        vol=torch.zeros(n_rows),
        timestamps=torch.arange(n_rows, dtype=torch.int64),
        is_overnight_gap=None,
        mask=torch.zeros(n_rows, dtype=torch.bool),
        channel_names=("a",),
        meta={},
    )
    normalizer = fit_frozen_normalizer(
        artifact,
        training_range_start="2024-01-01",
        training_range_end="2024-12-31",
        emitter=_fresh_emitter(),
        run_id="test-ignore",
    )
    # Only the first 100 rows (value 10.0) counted; mean must be 10.0, not 55.0.
    assert normalizer.mean["a"].item() == pytest.approx(10.0)


def test_fit_emits_normalizer_fitted():
    """Sprint 054: NORMALIZER_FITTED lands in the trace with correct payload."""
    artifact = _artifact(n_rows=50)
    e = _fresh_emitter()
    fit_frozen_normalizer(
        artifact,
        training_range_start="2015-01-05",
        training_range_end="2022-12-30",
        emitter=e,
        run_id="test-emit",
    )
    fits = [s for s in e.snapshot() if s.tag == "NORMALIZER_FITTED"]
    assert len(fits) == 1
    p = fits[0].payload
    assert p["run_id"] == "test-emit"
    assert p["feature_count"] == 7
    assert p["training_range_start"] == "2015-01-05"


def test_fit_raises_when_every_target_is_null():
    n_rows = 10
    artifact = TokenizedArtifact(
        features={"a": torch.zeros(n_rows, 2)},
        targets=torch.full((n_rows,), -100, dtype=torch.int64),
        vol=torch.zeros(n_rows),
        timestamps=torch.arange(n_rows, dtype=torch.int64),
        is_overnight_gap=None,
        mask=torch.zeros(n_rows, dtype=torch.bool),
        channel_names=("a",),
        meta={},
    )
    with pytest.raises(ValueError, match="no valid rows"):
        fit_frozen_normalizer(
            artifact,
            training_range_start="2024-01-01",
            training_range_end="2024-12-31",
            emitter=_fresh_emitter(),
            run_id="x",
        )


# write + load round-trip ------------------------------------------------


def test_write_load_roundtrip(tmp_path: Path):
    """Sprint 054: persisted normalizer round-trips through load_frozen_normalizer."""
    artifact = _artifact(n_rows=100)
    e = _fresh_emitter()
    original = fit_frozen_normalizer(
        artifact,
        training_range_start="2024-01-01",
        training_range_end="2024-12-31",
        emitter=e,
        run_id="round-trip",
    )
    base_path = tmp_path / "normalizers.pt"
    written = write_frozen_normalizer(original, base_path, e, run_id="round-trip")
    loaded = load_frozen_normalizer(written)
    for key in original.mean:
        assert torch.allclose(original.mean[key], loaded.mean[key])
        assert torch.allclose(original.std[key], loaded.std[key])
    assert loaded.feature_count == original.feature_count


def test_write_emits_normalizer_state_written(tmp_path: Path):
    artifact = _artifact(n_rows=50)
    e = _fresh_emitter()
    normalizer = fit_frozen_normalizer(
        artifact,
        training_range_start="2024-01-01",
        training_range_end="2024-12-31",
        emitter=e,
        run_id="emit-write",
    )
    write_frozen_normalizer(normalizer, tmp_path / "n.pt", e, run_id="emit-write")
    writes = [s for s in e.snapshot() if s.tag == "NORMALIZER_STATE_WRITTEN"]
    assert len(writes) == 1
    assert writes[0].payload["feature_count"] == normalizer.feature_count
    assert len(writes[0].payload["sha256"]) == 64


# apply ------------------------------------------------------------------


def test_apply_transforms_x_to_zero_mean_unit_std():
    """Sprint 054: applying to the same tensors used for fit yields mean~0, std~1."""
    artifact = _artifact(n_rows=500)
    e = _fresh_emitter()
    normalizer = fit_frozen_normalizer(
        artifact,
        training_range_start="2024-01-01",
        training_range_end="2024-12-31",
        emitter=e,
        run_id="apply",
    )
    normalized = apply_frozen_normalizer(artifact.features, normalizer)
    for key in normalized:
        col_mean = normalized[key].mean(dim=0)
        col_std = normalized[key].std(dim=0, unbiased=False)
        assert torch.allclose(col_mean, torch.zeros_like(col_mean), atol=1e-6)
        assert torch.allclose(col_std, torch.ones_like(col_std), atol=1e-5)


def test_apply_passes_zero_std_columns_through_as_zero():
    """Constant columns (std == 0) survive the divisor clamp; output is 0."""
    n_rows = 20
    # feature 0 is constant (std==0); feature 1 is varying.
    feats = {"a": torch.stack([torch.full((n_rows,), 5.0), torch.randn(n_rows)], dim=1)}
    artifact = TokenizedArtifact(
        features=feats,
        targets=torch.zeros(n_rows, dtype=torch.int64),
        vol=torch.zeros(n_rows),
        timestamps=torch.arange(n_rows, dtype=torch.int64),
        is_overnight_gap=None,
        mask=torch.ones(n_rows, dtype=torch.bool),
        channel_names=("a",),
        meta={},
    )
    normalizer = fit_frozen_normalizer(
        artifact,
        training_range_start="2024-01-01",
        training_range_end="2024-12-31",
        emitter=_fresh_emitter(),
        run_id="const",
    )
    out = apply_frozen_normalizer(artifact.features, normalizer)
    # Column 0 was constant, std=0, clamped divisor, (x-mean)/max(std,1e-8) with x==mean gives 0.
    assert torch.allclose(out["a"][:, 0], torch.zeros(n_rows), atol=1e-6)


def test_apply_rejects_unknown_channel():
    n_rows = 10
    normalizer = FrozenNormalizer(
        mean={"a": torch.zeros(2)},
        std={"a": torch.ones(2)},
        feature_count=2,
    )
    feats = {"a": torch.randn(n_rows, 2), "b": torch.randn(n_rows, 2)}
    with pytest.raises(ValueError, match="missing channel 'b'"):
        apply_frozen_normalizer(feats, normalizer)


def test_apply_broadcasts_over_batch_dim():
    """Batched input (B, T, F_c) broadcasts against per-feature (F_c,) constants."""
    n_rows = 100
    artifact = _artifact(n_rows=n_rows)
    normalizer = fit_frozen_normalizer(
        artifact,
        training_range_start="2024-01-01",
        training_range_end="2024-12-31",
        emitter=_fresh_emitter(),
        run_id="batched",
    )
    batched = {
        "target__SPY": artifact.features["target__SPY"].unsqueeze(0).expand(3, -1, -1).clone(),
        "market_context__VIX": (
            artifact.features["market_context__VIX"].unsqueeze(0).expand(3, -1, -1).clone()
        ),
    }
    out = apply_frozen_normalizer(batched, normalizer)
    assert out["target__SPY"].shape == (3, n_rows, 4)
    # Row 0 of every batch should match the un-batched transform result.
    single = apply_frozen_normalizer(artifact.features, normalizer)
    assert torch.allclose(out["target__SPY"][0], single["target__SPY"], atol=1e-6)

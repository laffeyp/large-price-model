"""Sprint 054: frozen normalizer -- fit + write + load + apply + emit contracts."""

from __future__ import annotations

from pathlib import Path

import pytest
import torch

from price_space_llm.model.dataset import TokenizedArtifact
from price_space_llm.normalizer import (
    EXPECTED_CONSTANT_CHANNELS,
    FrozenNormalizer,
    apply_frozen_normalizer,
    fit_frozen_normalizer,
    load_frozen_normalizer,
    measure_normalizer_drift,
    two_sample_ks,
    warn_channels_under_clamp,
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
        # Sprint 079: constant synthetic feature on a non-exempt channel would
        # trip the strict check; this test is about target-null filtering.
        strict_std_clamp=False,
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
        # Sprint 079: channel "a" is not on EXPECTED_CONSTANT_CHANNELS; its
        # constant feature 0 would trip the fail-loud strict check. This test
        # is about apply-time behavior on a constant column, not about the
        # fit-time policy — opt out of strict.
        strict_std_clamp=False,
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


# Sprint 055: drift diagnostic --------------------------------------------


import numpy as np  # noqa: E402


def test_two_sample_ks_identical_samples_returns_zero_and_one():
    """Sprint 055: identical distributions produce KS=0, p=1."""
    rng = np.random.default_rng(0)
    a = rng.normal(0.0, 1.0, size=1000)
    d, p = two_sample_ks(a, a.copy())
    assert d == 0.0
    assert p == 1.0


def test_two_sample_ks_detects_shift():
    """Sprint 055: mean-shifted distributions produce large KS + small p."""
    rng = np.random.default_rng(0)
    a = rng.normal(0.0, 1.0, size=2000)
    b = rng.normal(1.5, 1.0, size=2000)
    d, p = two_sample_ks(a, b)
    assert d > 0.3
    assert p < 0.001


def test_two_sample_ks_similar_distributions_p_high():
    """Sprint 055: two samples from the same distribution should not reject."""
    rng = np.random.default_rng(42)
    a = rng.normal(0.0, 1.0, size=1000)
    b = rng.normal(0.0, 1.0, size=1000)
    d, p = two_sample_ks(a, b)
    assert d < 0.1
    assert p > 0.05


def _drift_artifact(n_rows: int, mean_shift: float, seed: int) -> TokenizedArtifact:
    """Two-channel artifact with a controllable mean shift on target__SPY."""
    g = torch.Generator().manual_seed(seed)
    target_feats = torch.randn(n_rows, 4, generator=g) + mean_shift
    return TokenizedArtifact(
        features={
            "target__SPY": target_feats,
            "market_context__VIX": torch.randn(n_rows, 3, generator=g),
        },
        targets=torch.randint(0, 32, (n_rows,), generator=g, dtype=torch.int64),
        vol=torch.zeros(n_rows, dtype=torch.float32),
        timestamps=torch.arange(n_rows, dtype=torch.int64),
        is_overnight_gap=None,
        mask=torch.ones(n_rows, dtype=torch.bool),
        channel_names=("market_context__VIX", "target__SPY"),
        meta={},
    )


def test_measure_normalizer_drift_emits_per_feature():
    """Sprint 055: fires one NORMALIZER_DRIFT_MEASURED per (channel, feature_index)."""
    train = _drift_artifact(n_rows=2000, mean_shift=0.0, seed=0)
    holdout = _drift_artifact(n_rows=500, mean_shift=0.0, seed=1)
    e = _fresh_emitter(max_buffer=4096)
    normalizer = fit_frozen_normalizer(
        train,
        training_range_start="2024-01-01",
        training_range_end="2024-12-31",
        emitter=e,
        run_id="drift-fit",
    )
    n = measure_normalizer_drift(
        train_artifact=train,
        holdout_artifact=holdout,
        normalizer=normalizer,
        emitter=e,
        run_id="drift",
        plot_dir=None,
    )
    assert n == 4 + 3  # target 4 + VIX 3
    drift = [s for s in e.snapshot() if s.tag == "NORMALIZER_DRIFT_MEASURED"]
    assert len(drift) == 7
    channels = {s.payload["channel"] for s in drift}
    assert channels == {"target__SPY", "market_context__VIX"}


def test_measure_normalizer_drift_flags_shifted_feature():
    """A holdout mean-shifted vs training produces high KS + low p on target features."""
    train = _drift_artifact(n_rows=2000, mean_shift=0.0, seed=0)
    holdout = _drift_artifact(n_rows=500, mean_shift=2.0, seed=1)
    e = _fresh_emitter(max_buffer=4096)
    normalizer = fit_frozen_normalizer(
        train,
        training_range_start="2024-01-01",
        training_range_end="2024-12-31",
        emitter=e,
        run_id="drift-shift",
    )
    measure_normalizer_drift(
        train_artifact=train,
        holdout_artifact=holdout,
        normalizer=normalizer,
        emitter=e,
        run_id="drift-shift-run",
        plot_dir=None,
    )
    target_drift = [
        s
        for s in e.snapshot()
        if s.tag == "NORMALIZER_DRIFT_MEASURED" and s.payload["channel"] == "target__SPY"
    ]
    assert target_drift
    # At least one target feature should show visible shift.
    max_ks = max(s.payload["ks_statistic"] for s in target_drift)
    min_p = min(s.payload["p_value"] for s in target_drift)
    assert max_ks > 0.4
    assert min_p < 0.001


def test_measure_normalizer_drift_channel_mismatch_raises():
    """Different channel sets between train and holdout must raise."""
    train = _drift_artifact(n_rows=100, mean_shift=0.0, seed=0)
    # Drop one channel from holdout.
    holdout_features = {"target__SPY": train.features["target__SPY"].clone()}
    holdout = TokenizedArtifact(
        features=holdout_features,
        targets=train.targets,
        vol=train.vol,
        timestamps=train.timestamps,
        is_overnight_gap=None,
        mask=train.mask,
        channel_names=("target__SPY",),
        meta={},
    )
    e = _fresh_emitter()
    normalizer = fit_frozen_normalizer(
        train,
        training_range_start="2024-01-01",
        training_range_end="2024-12-31",
        emitter=e,
        run_id="mismatch",
    )
    with pytest.raises(ValueError, match="different channel sets"):
        measure_normalizer_drift(
            train_artifact=train,
            holdout_artifact=holdout,
            normalizer=normalizer,
            emitter=e,
            run_id="mismatch-run",
        )


def test_measure_normalizer_drift_writes_pngs(tmp_path: Path):
    """When plot_dir is set and matplotlib is importable, one PNG per feature lands."""
    pytest.importorskip("matplotlib")
    train = _drift_artifact(n_rows=1000, mean_shift=0.0, seed=0)
    holdout = _drift_artifact(n_rows=500, mean_shift=0.5, seed=1)
    e = _fresh_emitter(max_buffer=4096)
    normalizer = fit_frozen_normalizer(
        train,
        training_range_start="2024-01-01",
        training_range_end="2024-12-31",
        emitter=e,
        run_id="png",
    )
    measure_normalizer_drift(
        train_artifact=train,
        holdout_artifact=holdout,
        normalizer=normalizer,
        emitter=e,
        run_id="png-run",
        plot_dir=tmp_path,
    )
    pngs = sorted(tmp_path.glob("*.png"))
    assert len(pngs) == 4 + 3
    for p in pngs:
        assert p.stat().st_size > 0


# Sprint 076: std_clamp configurability + warn helper ----------------------


def test_frozen_normalizer_default_std_clamp():
    """A FrozenNormalizer built with no std_clamp kwarg defaults to 1e-8."""
    n = FrozenNormalizer(
        mean={"target__SPY": torch.zeros(2)},
        std={"target__SPY": torch.ones(2)},
        feature_count=2,
    )
    assert n.std_clamp == 1e-8


def test_apply_uses_normalizer_std_clamp_not_module_constant():
    """A per-normalizer std_clamp overrides the module default at apply time."""
    n = FrozenNormalizer(
        mean={"target__SPY": torch.zeros(1)},
        std={"target__SPY": torch.zeros(1)},  # constant column
        feature_count=1,
        std_clamp=1.0,  # divisor 1.0 instead of 1e-8
    )
    feats = {"target__SPY": torch.tensor([[3.0], [5.0]])}
    out = apply_frozen_normalizer(feats, n)
    # (x - 0) / max(0, 1.0) = x  — with module-default 1e-8 the result would
    # be x / 1e-8 = 3e8. The per-normalizer clamp wins.
    assert torch.allclose(out["target__SPY"], torch.tensor([[3.0], [5.0]]))


def test_write_load_round_trip_preserves_std_clamp(tmp_path: Path):
    """A written normalizer round-trips its std_clamp; missing key falls back to STD_CLAMP."""
    e = _fresh_emitter()
    n = FrozenNormalizer(
        mean={"target__SPY": torch.zeros(2)},
        std={"target__SPY": torch.ones(2)},
        feature_count=2,
        std_clamp=1e-6,
    )
    path = write_frozen_normalizer(n, tmp_path / "normalizers.pt", e, run_id="clamp-round-trip")
    loaded = load_frozen_normalizer(path)
    assert loaded.std_clamp == 1e-6


# Sprint 077: fail-loud on legacy std_clamp ---------------------------------


def test_load_frozen_normalizer_refuses_legacy_std_clamp(tmp_path: Path):
    """Pre-Sprint-076 normalizer (no `std_clamp` key) raises."""
    from price_space_llm.normalizer import LegacyStdClampMissing

    legacy = {
        "mean": {"target__SPY": torch.zeros(2)},
        "std": {"target__SPY": torch.ones(2)},
        "feature_count": 2,
        # No std_clamp key — pre-Sprint-076 shape.
    }
    path = tmp_path / "legacy_normalizer.pt"
    torch.save(legacy, path)
    with pytest.raises(LegacyStdClampMissing, match="std_clamp"):
        load_frozen_normalizer(path)


def test_load_frozen_normalizer_accepts_legacy_with_flag(tmp_path: Path):
    """`allow_legacy_std_clamp=True` returns a FrozenNormalizer with the module default."""
    from price_space_llm.normalizer.frozen import STD_CLAMP

    legacy = {
        "mean": {"target__SPY": torch.zeros(2)},
        "std": {"target__SPY": torch.ones(2)},
        "feature_count": 2,
    }
    path = tmp_path / "legacy_normalizer.pt"
    torch.save(legacy, path)
    loaded = load_frozen_normalizer(path, allow_legacy_std_clamp=True)
    assert loaded.std_clamp == STD_CLAMP


def test_warn_channels_under_clamp_reports_non_exempt_only():
    """A tiny non-exempt std surfaces; a zero-std exempt channel does not."""
    n = FrozenNormalizer(
        mean={
            "event__FOMC": torch.zeros(1),
            "target__SPY": torch.zeros(4),
        },
        std={
            "event__FOMC": torch.zeros(1),  # exempt: constant by construction
            # feature 3 has std well below the clamp band; features 0-2 above.
            "target__SPY": torch.tensor([1.0, 1.0, 1.0, 1e-10]),
        },
        feature_count=5,
    )
    hits = warn_channels_under_clamp(n)
    assert len(hits) == 1
    channel, idx, value = hits[0]
    assert channel == "target__SPY"
    assert idx == 3
    assert value < n.std_clamp
    # FOMC (exempt) does not surface.
    assert all(h[0] != "event__FOMC" for h in hits)
    # And the frozenset the helper defaults to matches what we exported.
    assert "event__FOMC" in EXPECTED_CONSTANT_CHANNELS


# Sprint 079: strict-std-clamp default on fit_frozen_normalizer -----------


def _fit_artifact_with_constant_target_feature(n_rows: int = 40) -> TokenizedArtifact:
    """Two-feature target channel; feature 0 is constant (std=0), feature 1 varies."""
    feats = {
        "target__SPY": torch.stack(
            [torch.full((n_rows,), 5.0), torch.randn(n_rows)], dim=1
        )
    }
    return TokenizedArtifact(
        features=feats,
        targets=torch.randint(0, 32, (n_rows,), dtype=torch.int64),
        vol=torch.zeros(n_rows),
        timestamps=torch.arange(n_rows, dtype=torch.int64),
        is_overnight_gap=None,
        mask=torch.ones(n_rows, dtype=torch.bool),
        channel_names=("target__SPY",),
        meta={},
    )


# Sprint 084 (v0.7): run_training_feats refuses un-normalized artifact on mixer -


def test_run_training_feats_refuses_unnormalized_on_mixer():
    """Sprint 084: fusion='mixer' + artifact.meta['normalized']=False raises."""
    from price_space_llm.model import (
        MarketStateTransformerConfig,
        TokenizedArtifact,
        run_training_feats,
    )
    from price_space_llm.model.trainer import TrainerConfig, UnnormalizedArtifactRefused

    n_rows = 400
    artifact = TokenizedArtifact(
        features={"target__SPY": torch.randn(n_rows, 4)},
        targets=torch.randint(0, 32, (n_rows,), dtype=torch.int64),
        vol=torch.zeros(n_rows, dtype=torch.float32),
        timestamps=torch.arange(n_rows, dtype=torch.int64),
        is_overnight_gap=None,
        mask=torch.ones(n_rows, dtype=torch.bool),
        channel_names=("target__SPY",),
        meta={"normalized": False},  # explicit un-normalized
    )
    cfg = MarketStateTransformerConfig(
        vocab_size=32,
        context_len=64,
        channel_dims={"target__SPY": 4},
        d_model=128,
        n_heads=2,
        fusion="mixer",
    )
    e = _fresh_emitter()
    with pytest.raises(UnnormalizedArtifactRefused, match="fusion='mixer'"):
        run_training_feats(
            artifact=artifact,
            trainer_cfg=TrainerConfig(
                n_steps=1, batch_size=2, lr=1e-4, eval_every=1, seed=0, warmup_steps=0
            ),
            model_cfg=cfg,
            emitter=e,
            run_id="v07-mixer-refuse",
            checkpoint_dir=Path("/tmp/v07-refuse"),
            device="cpu",
        )


# Sprint 089: quantile head refuses missing raw_targets ---------------------


def test_run_training_feats_refuses_quantile_without_raw_targets():
    """head_type='quantile' + artifact.raw_targets is None raises."""
    from price_space_llm.model import (
        MarketStateTransformerConfig,
        TokenizedArtifact,
        run_training_feats,
    )
    from price_space_llm.model.trainer import (
        QuantileHeadRequiresRawTargets,
        TrainerConfig,
    )

    n_rows = 400
    artifact = TokenizedArtifact(
        features={"target__SPY": torch.randn(n_rows, 4) * 0.1},
        targets=torch.randint(0, 32, (n_rows,), dtype=torch.int64),
        raw_targets=None,  # explicit — no raw targets stamped
        vol=torch.zeros(n_rows, dtype=torch.float32),
        timestamps=torch.arange(n_rows, dtype=torch.int64),
        is_overnight_gap=None,
        mask=torch.ones(n_rows, dtype=torch.bool),
        channel_names=("target__SPY",),
        meta={"normalized": True},
    )
    cfg = MarketStateTransformerConfig(
        vocab_size=32,
        context_len=64,
        channel_dims={"target__SPY": 4},
        d_model=64,
        n_heads=4,
        head_type="quantile",
    )
    e = _fresh_emitter()
    with pytest.raises(QuantileHeadRequiresRawTargets, match="raw_targets"):
        run_training_feats(
            artifact=artifact,
            trainer_cfg=TrainerConfig(
                n_steps=1, batch_size=2, lr=1e-4, eval_every=1, seed=0, warmup_steps=0
            ),
            model_cfg=cfg,
            emitter=e,
            run_id="v089-quantile-refuse",
            checkpoint_dir=Path("/tmp/v089-refuse"),
            device="cpu",
        )


def test_run_training_feats_refuses_sum_on_unnormalized_artifact():
    """Sprint 113: fusion='sum' now requires normalized artifact too.

    Retracts Sprint 084's claim that sum fusion tolerates un-normalized input.
    Sprint 113-A and Sprint 113-C proved sum fusion silently drowns non-target
    channels on un-normalized data (raw dollar_volume scale ~264M std dominates
    per-channel Linear projections). Target-only ablation matched full-channel
    to 4 decimals on un-normalized; normalizing recovered a 0.21-nat gain.
    """
    from price_space_llm.model import (
        MarketStateTransformerConfig,
        TokenizedArtifact,
        run_training_feats,
    )
    from price_space_llm.model.trainer import TrainerConfig, UnnormalizedArtifactRefused

    n_rows = 400
    artifact = TokenizedArtifact(
        features={"target__SPY": torch.randn(n_rows, 4) * 0.1},
        targets=torch.randint(0, 32, (n_rows,), dtype=torch.int64),
        vol=torch.zeros(n_rows, dtype=torch.float32),
        timestamps=torch.arange(n_rows, dtype=torch.int64),
        is_overnight_gap=None,
        mask=torch.ones(n_rows, dtype=torch.bool),
        channel_names=("target__SPY",),
        meta={"normalized": False},
    )
    cfg = MarketStateTransformerConfig(
        vocab_size=32,
        context_len=64,
        channel_dims={"target__SPY": 4},
        d_model=64,
        n_heads=4,
        fusion="sum",
    )
    with pytest.raises(UnnormalizedArtifactRefused, match="fusion='sum'"):
        run_training_feats(
            artifact=artifact,
            trainer_cfg=TrainerConfig(
                n_steps=1, batch_size=2, lr=1e-4, eval_every=1, seed=0, warmup_steps=0
            ),
            model_cfg=cfg,
            emitter=_fresh_emitter(),
            run_id="sprint113-sum-refused",
            checkpoint_dir=Path("/tmp/sprint113-sum-refused"),
            device="cpu",
        )


def test_fit_frozen_normalizer_emits_normalizer_channel_under_clamp():
    """Sprint 080 (v0.6): NORMALIZER_CHANNEL_UNDER_CLAMP fires per hit in lenient mode."""
    artifact = _fit_artifact_with_constant_target_feature()
    e = _fresh_emitter()
    fit_frozen_normalizer(
        artifact,
        training_range_start="2024-01-01",
        training_range_end="2024-12-31",
        emitter=e,
        run_id="v080-under-clamp",
        strict_std_clamp=False,
    )
    emits = [s for s in e.snapshot() if s.tag == "NORMALIZER_CHANNEL_UNDER_CLAMP"]
    assert len(emits) == 1
    payload = emits[0].payload
    assert payload["run_id"] == "v080-under-clamp"
    assert payload["channel"] == "target__SPY"
    assert payload["feature_index"] == 0
    assert payload["std_value"] == 0.0
    assert payload["std_clamp"] == 1e-8


def test_fit_frozen_normalizer_strict_default_raises_on_non_exempt_tiny_std():
    """Sprint 079: default `strict_std_clamp=True` raises on non-exempt tiny-std channels."""
    from price_space_llm.normalizer import NormalizerStdClampViolation

    artifact = _fit_artifact_with_constant_target_feature()
    with pytest.raises(NormalizerStdClampViolation, match="target__SPY"):
        fit_frozen_normalizer(
            artifact,
            training_range_start="2024-01-01",
            training_range_end="2024-12-31",
            emitter=_fresh_emitter(),
            run_id="strict-default",
        )


def test_fit_frozen_normalizer_strict_false_permits_tiny_std():
    """Passing `strict_std_clamp=False` accepts the tiny-std normalization."""
    artifact = _fit_artifact_with_constant_target_feature()
    normalizer = fit_frozen_normalizer(
        artifact,
        training_range_start="2024-01-01",
        training_range_end="2024-12-31",
        emitter=_fresh_emitter(),
        run_id="strict-off",
        strict_std_clamp=False,
    )
    assert normalizer.std["target__SPY"][0].item() == 0.0

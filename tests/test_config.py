"""Tests for the ExperimentConfig loader (Pydantic v2 validation)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from price_space_llm.config import (
    ConfigValidationFailed,
    ExperimentConfig,
    load_config,
)
from price_space_llm.signals import StrictSignalEmitter, load_vocabulary


def _fresh_emitter() -> StrictSignalEmitter:
    return StrictSignalEmitter(load_vocabulary())


def _write(tmp_path: Path, body: dict) -> Path:
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps(body), encoding="utf-8")
    return p


def _valid_body() -> dict:
    return {
        "target_symbol": "SPY",
        "context_len": 128,
        "n_buckets": 32,
        "lambda_risk": 1.0,
        "alpha_mag_weight": 0.5,
    }


# Model-level validation ---------------------------------------------------


def test_valid_config_parses():
    cfg = ExperimentConfig.model_validate(_valid_body())
    assert cfg.target_symbol == "SPY"
    assert cfg.context_len == 128
    assert cfg.n_buckets == 32
    assert cfg.lambda_risk == 1.0
    assert cfg.alpha_mag_weight == 0.5


def test_missing_lambda_risk_raises():
    body = _valid_body()
    del body["lambda_risk"]
    with pytest.raises(Exception, match="lambda_risk"):
        ExperimentConfig.model_validate(body)


def test_missing_alpha_mag_weight_raises():
    body = _valid_body()
    del body["alpha_mag_weight"]
    with pytest.raises(Exception, match="alpha_mag_weight"):
        ExperimentConfig.model_validate(body)


def test_context_len_out_of_enum_raises():
    body = _valid_body()
    body["context_len"] = 100  # not in {64, 128, 256, 512}
    with pytest.raises(Exception, match="context_len"):
        ExperimentConfig.model_validate(body)


def test_n_buckets_out_of_enum_raises():
    body = _valid_body()
    body["n_buckets"] = 24  # not in {16, 32, 64}
    with pytest.raises(Exception, match="n_buckets"):
        ExperimentConfig.model_validate(body)


def test_empty_target_symbol_raises():
    body = _valid_body()
    body["target_symbol"] = ""
    with pytest.raises(Exception, match="target_symbol"):
        ExperimentConfig.model_validate(body)


# load_config emit contract ------------------------------------------------


def test_load_config_emits_config_resolved(tmp_path: Path):
    e = _fresh_emitter()
    path = _write(tmp_path, _valid_body())
    result = load_config(path, emitter=e, run_id="test-run", git_sha="0" * 40)
    tags = [s.tag for s in e.snapshot()]
    assert tags == ["CONFIG_RESOLVED"]
    resolved = e.snapshot()[0]
    assert resolved.payload["run_id"] == "test-run"
    assert resolved.payload["lambda_risk"] == 1.0
    assert resolved.payload["target_symbol"] == "SPY"
    assert resolved.payload["context_len"] == "128"  # emitted as string per vocab enum
    assert resolved.payload["n_buckets"] == "32"
    assert len(resolved.payload["config_hash"]) == 64  # sha256 hex
    assert result.config.n_buckets == 32


def test_load_config_missing_file_emits_validation_failed_and_raises(tmp_path: Path):
    e = _fresh_emitter()
    missing = tmp_path / "does-not-exist.json"
    with pytest.raises(ConfigValidationFailed, match="does not exist"):
        load_config(missing, emitter=e, run_id="test-run", git_sha="0" * 40)
    tags = [s.tag for s in e.snapshot()]
    assert tags == ["CONFIG_VALIDATION_FAILED"]


def test_load_config_malformed_json_emits_validation_failed(tmp_path: Path):
    e = _fresh_emitter()
    path = tmp_path / "bad.json"
    path.write_text("{ this is not valid JSON")
    with pytest.raises(ConfigValidationFailed, match="JSON parse"):
        load_config(path, emitter=e, run_id="test-run", git_sha="0" * 40)
    tags = [s.tag for s in e.snapshot()]
    assert tags == ["CONFIG_VALIDATION_FAILED"]


def test_load_config_missing_required_field_lists_it(tmp_path: Path):
    e = _fresh_emitter()
    body = _valid_body()
    del body["lambda_risk"]
    path = _write(tmp_path, body)
    with pytest.raises(ConfigValidationFailed):
        load_config(path, emitter=e, run_id="test-run", git_sha="0" * 40)
    failed = next(s for s in e.snapshot() if s.tag == "CONFIG_VALIDATION_FAILED")
    assert "lambda_risk" in failed.payload["missing_or_invalid_fields"]


def test_load_config_hash_is_deterministic(tmp_path: Path):
    e = _fresh_emitter()
    path = _write(tmp_path, _valid_body())
    r1 = load_config(path, emitter=e, run_id="a", git_sha="0" * 40)
    r2 = load_config(path, emitter=e, run_id="b", git_sha="0" * 40)
    assert r1.config_hash == r2.config_hash


# Sprint 084 (v0.7): CONFIG_RESOLVED payload extensions -------------------


def test_load_config_config_resolved_carries_model_architecture(tmp_path: Path):
    """Sprint 084: CONFIG_RESOLVED payload includes the six new fields with defaults."""
    e = _fresh_emitter()
    path = _write(tmp_path, _valid_body())
    load_config(path, emitter=e, run_id="v07-defaults", git_sha="0" * 40)
    resolved = next(s for s in e.snapshot() if s.tag == "CONFIG_RESOLVED")
    p = resolved.payload
    assert p["d_model"] == "64"
    assert p["n_layers"] == "4"
    assert p["n_heads"] == "4"
    assert p["fusion"] == "sum"
    assert p["mixer_dim"] == 96
    assert p["mixer_n_heads"] == 2


def test_load_config_config_resolved_reflects_overrides(tmp_path: Path):
    """Sprint 084: overrides land in the emit payload."""
    e = _fresh_emitter()
    path = _write(tmp_path, _valid_body())
    load_config(
        path,
        emitter=e,
        run_id="v07-mixer",
        git_sha="0" * 40,
        d_model=128,
        n_layers=4,
        n_heads=2,
        fusion="mixer",
        mixer_dim=96,
        mixer_n_heads=2,
    )
    resolved = next(s for s in e.snapshot() if s.tag == "CONFIG_RESOLVED")
    p = resolved.payload
    assert p["d_model"] == "128"
    assert p["n_heads"] == "2"
    assert p["fusion"] == "mixer"


# Sprint 073: model-size configs (Phase E, roadmap 067) --------------------


REPO_ROOT = Path(__file__).resolve().parents[1]
_SPEC_SIZES = {
    "xs": {"d_model": 128, "n_layers": 4, "n_heads": 2},
    "sm": {"d_model": 192, "n_layers": 6, "n_heads": 3},
    "md": {"d_model": 384, "n_layers": 8, "n_heads": 6},
    "lg": {"d_model": 512, "n_layers": 8, "n_heads": 8},
}


def test_model_size_config_rejects_off_spec_d_model(tmp_path: Path):
    from price_space_llm.config import (
        ModelSizeConfigValidationFailed,
        load_model_size_config,
    )

    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"d_model": 256, "n_layers": 4, "n_heads": 4}))
    with pytest.raises(ModelSizeConfigValidationFailed):
        load_model_size_config(path)


def test_model_size_config_accepts_all_four_spec_sizes():
    """Every canonical file on disk parses; head_dim = d_model / n_heads = 64."""
    from price_space_llm.config import load_model_size_config

    for name, expected in _SPEC_SIZES.items():
        cfg = load_model_size_config(REPO_ROOT / "configs" / "model" / f"{name}.json")
        assert cfg.d_model == expected["d_model"], name
        assert cfg.n_layers == expected["n_layers"], name
        assert cfg.n_heads == expected["n_heads"], name
        assert cfg.d_model % cfg.n_heads == 0, name
        assert cfg.d_model // cfg.n_heads == 64, name


def test_load_model_size_config_round_trips(tmp_path: Path):
    from price_space_llm.config import load_model_size_config

    body = {"d_model": 128, "n_layers": 4, "n_heads": 2}
    path = tmp_path / "cfg.json"
    path.write_text(json.dumps(body))
    cfg = load_model_size_config(path)
    assert cfg.model_dump() == body


# Sprint 074: context-length configs (Phase E, roadmap 068) ---------------

_SPEC_CONTEXTS = (64, 128, 256, 512)


def test_context_len_config_rejects_off_spec_value(tmp_path: Path):
    from price_space_llm.config import (
        ContextLenConfigValidationFailed,
        load_context_len_config,
    )

    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"context_len": 100}))
    with pytest.raises(ContextLenConfigValidationFailed):
        load_context_len_config(path)


def test_context_len_config_accepts_all_four_spec_values():
    """Every canonical file on disk parses; value matches filename."""
    from price_space_llm.config import load_context_len_config

    for n in _SPEC_CONTEXTS:
        cfg = load_context_len_config(REPO_ROOT / "configs" / "context" / f"{n}.json")
        assert cfg.context_len == n, n


def test_load_context_len_config_round_trips(tmp_path: Path):
    from price_space_llm.config import load_context_len_config

    body = {"context_len": 128}
    path = tmp_path / "cfg.json"
    path.write_text(json.dumps(body))
    cfg = load_context_len_config(path)
    assert cfg.model_dump() == body

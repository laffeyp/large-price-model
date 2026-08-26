"""ExperimentConfig — Pydantic v2 validation at the speaker's mouth.

Tech-arch §11.3 declares `lambda_risk` and `alpha_mag_weight` as
load-bearing: a run without an explicit value for either fails
registration. This module enforces that with a Pydantic v2 model and
emits `CONFIG_RESOLVED` at successful load, `CONFIG_VALIDATION_FAILED`
otherwise.

The v0.3 vocabulary constrains `context_len` and `n_buckets` to discrete
enum sets; the Literal types below mirror those enum values so the
Pydantic validator rejects any out-of-set value at parse time.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from price_space_llm.signals import StrictSignalEmitter


class ExperimentConfig(BaseModel):
    """Load-bearing v1 experiment config, matching CONFIG_RESOLVED.typed_payload.

    Every field is required. `lambda_risk` and `alpha_mag_weight` are the
    tech-arch §11.3 registration gates. `context_len` and `n_buckets` are
    constrained to the v0.3 vocabulary's declared enum values.
    """

    target_symbol: str = Field(..., min_length=1, description="e.g. 'SPY'.")
    context_len: Literal[64, 128, 256, 512] = Field(..., description="Transformer context length.")
    n_buckets: Literal[16, 32, 64] = Field(..., description="Vol-normalized return bucket count.")
    lambda_risk: float = Field(
        ...,
        description="Risk-penalty scale on the decision loss (tech-arch §11.3 registration gate).",
    )
    alpha_mag_weight: float = Field(
        ...,
        description="Magnitude-weight loss scale (tech-arch §11.3 gate; 0 -> unweighted CE).",
    )


class ConfigValidationFailed(RuntimeError):
    """Config file exists but does not satisfy the ExperimentConfig schema."""


@dataclass(slots=True, frozen=True, kw_only=True)
class ConfigResolutionResult:
    """Return type of `load_config`."""

    config: ExperimentConfig
    config_hash: str
    resolved_at: datetime


def _config_hash(config_bytes: bytes) -> str:
    return hashlib.sha256(config_bytes).hexdigest()


def load_config(
    config_path: Path,
    emitter: StrictSignalEmitter,
    run_id: str,
    git_sha: str,
    *,
    d_model: int = 64,
    n_layers: int = 4,
    n_heads: int = 4,
    fusion: str = "sum",
    mixer_dim: int = 96,
    mixer_n_heads: int = 2,
) -> ConfigResolutionResult:
    """Load, validate, and emit CONFIG_RESOLVED (or CONFIG_VALIDATION_FAILED and raise).

    JSON only for now; TOML/Hydra land when a real config-composition
    sprint opens.
    """
    if not config_path.exists():
        emitter.emit(
            "CONFIG_VALIDATION_FAILED",
            config_path=str(config_path),
            missing_or_invalid_fields=[],
            error_message=f"config file does not exist: {config_path}",
        )
        raise ConfigValidationFailed(f"config file does not exist: {config_path}")

    raw_bytes = config_path.read_bytes()
    try:
        raw = json.loads(raw_bytes)
    except json.JSONDecodeError as ex:
        emitter.emit(
            "CONFIG_VALIDATION_FAILED",
            config_path=str(config_path),
            missing_or_invalid_fields=[],
            error_message=f"JSON parse error: {ex}",
        )
        raise ConfigValidationFailed(f"JSON parse error in {config_path}: {ex}") from ex

    try:
        config = ExperimentConfig.model_validate(raw)
    except ValidationError as ex:
        missing_or_invalid = [".".join(str(p) for p in e["loc"]) for e in ex.errors()]
        emitter.emit(
            "CONFIG_VALIDATION_FAILED",
            config_path=str(config_path),
            missing_or_invalid_fields=missing_or_invalid,
            error_message=str(ex),
        )
        raise ConfigValidationFailed(str(ex)) from ex

    config_hash = _config_hash(raw_bytes)
    resolved_at = datetime.now(UTC)

    emitter.emit(
        "CONFIG_RESOLVED",
        run_id=run_id,
        config_hash=config_hash,
        git_sha=git_sha,
        resolved_at=resolved_at.isoformat(),
        lambda_risk=config.lambda_risk,
        alpha_mag_weight=config.alpha_mag_weight,
        target_symbol=config.target_symbol,
        # v0.3 vocabulary declares context_len / n_buckets as string-token enums
        # (enum<64|128|256|512>, enum<16|32|64>); the Pydantic Literal[int, ...] type
        # keeps parse-time integrity, and we cast at emit for the enum check.
        context_len=str(config.context_len),
        n_buckets=str(config.n_buckets),
        # Sprint 084 (v0.7): model architecture fields make the trace self-describing.
        d_model=str(d_model),
        n_layers=str(n_layers),
        n_heads=str(n_heads),
        fusion=fusion,
        mixer_dim=mixer_dim,
        mixer_n_heads=mixer_n_heads,
    )

    return ConfigResolutionResult(
        config=config,
        config_hash=config_hash,
        resolved_at=resolved_at,
    )


# Sprint 073: model-size configs (Phase E, roadmap 067) ---------------------
#
# Spec (plans/v1-roadmap.md § 1): four pre-registered sizes
#   xs: d_model=128, n_layers=4, n_heads=2   (~1M params)
#   sm: d_model=192, n_layers=6, n_heads=3   (~3M)
#   md: d_model=384, n_layers=8, n_heads=6   (~10M)
#   lg: d_model=512, n_layers=8, n_heads=8   (~30M)
#
# Every canonical shape has head_dim = d_model / n_heads = 64. The Literal
# enums below reject any off-spec value at parse time; a sweep script that
# hand-authors a fifth shape must edit the vocabulary here first.


class ModelSizeConfig(BaseModel):
    """Pre-registered transformer shape. Fields match `TransformerConfig`
    and `MarketStateTransformerConfig` one-for-one so the CLI can splat.
    """

    d_model: Literal[128, 192, 384, 512] = Field(..., description="Model width.")
    n_layers: Literal[4, 6, 8] = Field(..., description="Transformer blocks.")
    n_heads: Literal[2, 3, 6, 8] = Field(..., description="Attention heads (d_model/64).")


class ModelSizeConfigValidationFailed(RuntimeError):
    """Model-size config file exists but does not satisfy the schema."""


def load_model_size_config(path: Path) -> ModelSizeConfig:
    """Load and validate a model-size JSON config from disk.

    Emits nothing — the caller passes the resolved shape into the model
    constructor and `SESSION_INIT` / `CONFIG_RESOLVED` fire from there.
    A v0.6 vocabulary bump adds d_model / n_layers / n_heads to
    `CONFIG_RESOLVED.typed_payload`; that bump is its own sprint.
    """
    if not path.exists():
        raise ModelSizeConfigValidationFailed(f"model-size config not found: {path}")
    try:
        raw = json.loads(path.read_bytes())
    except json.JSONDecodeError as ex:
        raise ModelSizeConfigValidationFailed(f"JSON parse error in {path}: {ex}") from ex
    try:
        return ModelSizeConfig.model_validate(raw)
    except ValidationError as ex:
        raise ModelSizeConfigValidationFailed(str(ex)) from ex


# Sprint 074: context-length configs (Phase E, roadmap 068) ----------------
#
# Spec (plans/v1-roadmap.md § 1): four pre-registered context lengths
#   64, 128, 256, 512.  Sibling to `ModelSizeConfig`; same Literal-at-the-edge
#   discipline. `ExperimentConfig.context_len` already carries the same set,
#   so a `--context-config` overlay strictly narrows to a value the trainer
#   already accepts.


class ContextLenConfig(BaseModel):
    """Pre-registered transformer context length. Overlays onto
    `ExperimentConfig.context_len` in the training CLI.
    """

    context_len: Literal[64, 128, 256, 512] = Field(
        ..., description="Sampled window length in bars."
    )


class ContextLenConfigValidationFailed(RuntimeError):
    """Context-length config file exists but does not satisfy the schema."""


def load_context_len_config(path: Path) -> ContextLenConfig:
    """Load and validate a context-length JSON config from disk."""
    if not path.exists():
        raise ContextLenConfigValidationFailed(f"context-length config not found: {path}")
    try:
        raw = json.loads(path.read_bytes())
    except json.JSONDecodeError as ex:
        raise ContextLenConfigValidationFailed(f"JSON parse error in {path}: {ex}") from ex
    try:
        return ContextLenConfig.model_validate(raw)
    except ValidationError as ex:
        raise ContextLenConfigValidationFailed(str(ex)) from ex


__all__ = [
    "ConfigResolutionResult",
    "ConfigValidationFailed",
    "ContextLenConfig",
    "ContextLenConfigValidationFailed",
    "ExperimentConfig",
    "ModelSizeConfig",
    "ModelSizeConfigValidationFailed",
    "load_config",
    "load_context_len_config",
    "load_model_size_config",
]

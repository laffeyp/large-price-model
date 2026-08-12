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

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, TypedDict

from pydantic import BaseModel, Field, ValidationError

from price_space_llm.signals import StrictSignalEmitter


class ConfigResolutionResult(TypedDict):
    """Return type of `load_config`."""

    config: ExperimentConfig
    config_hash: str
    resolved_at: datetime


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


def _config_hash(config_bytes: bytes) -> str:
    return hashlib.sha256(config_bytes).hexdigest()


def load_config(
    config_path: Path,
    emitter: StrictSignalEmitter,
    run_id: str,
    git_sha: str,
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
    )

    return ConfigResolutionResult(
        config=config,
        config_hash=config_hash,
        resolved_at=resolved_at,
    )


__all__ = [
    "ConfigResolutionResult",
    "ConfigValidationFailed",
    "ExperimentConfig",
    "load_config",
]

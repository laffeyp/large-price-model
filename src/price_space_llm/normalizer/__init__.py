"""Frozen normalizer for per-channel feature tensors.

Product-spec § Feature normalization: fit per-(channel, feature) mean + std on
the training partition, freeze, apply as constants on train/val/test. Sprint
054 ships interpretation (A) — full-training-partition constants; interpretation
(B) per-bar expanding stats is a Sprint 055+ follow-up if drift diagnostic
surfaces the need.
"""

from price_space_llm.normalizer.drift import (
    measure_normalizer_drift,
    two_sample_ks,
)
from price_space_llm.normalizer.frozen import (
    EXPECTED_CONSTANT_CHANNELS,
    FrozenNormalizer,
    LegacyStdClampMissing,
    NormalizerStdClampViolation,
    apply_frozen_normalizer,
    fit_frozen_normalizer,
    load_frozen_normalizer,
    warn_channels_under_clamp,
    write_frozen_normalizer,
)

__all__ = [
    "EXPECTED_CONSTANT_CHANNELS",
    "FrozenNormalizer",
    "LegacyStdClampMissing",
    "NormalizerStdClampViolation",
    "apply_frozen_normalizer",
    "fit_frozen_normalizer",
    "load_frozen_normalizer",
    "measure_normalizer_drift",
    "two_sample_ks",
    "warn_channels_under_clamp",
    "write_frozen_normalizer",
]

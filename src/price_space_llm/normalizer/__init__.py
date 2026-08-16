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
    FrozenNormalizer,
    apply_frozen_normalizer,
    fit_frozen_normalizer,
    load_frozen_normalizer,
    write_frozen_normalizer,
)

__all__ = [
    "FrozenNormalizer",
    "apply_frozen_normalizer",
    "fit_frozen_normalizer",
    "load_frozen_normalizer",
    "measure_normalizer_drift",
    "two_sample_ks",
    "write_frozen_normalizer",
]

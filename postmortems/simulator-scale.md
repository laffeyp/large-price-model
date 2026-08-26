# Post-mortem — simulator scale bug

Date found: 2026-08-26 (Sprint 117, phase close)

## What went wrong

The prediction layer named its output `expected_vn_return` and treated it as vol-normalized. The bucketizer fits on raw log-returns, so `Σ p_i * train_mean_i` is a raw log-return, not a vol-normalized one. The edge formula in `compute_edge` divided costs by `realized_vol` to convert them into vn units and subtracted from `expected_vn_return`, which sat on the raw-return scale. On SPY 15-minute bars the two scales differ by about 600x. Cost terms dominated the edge computation, so decisions did not fire. The first training-window simulator run against a trained model produced one trade across three years.

## Fix

`derive_prediction_scalars` now sets `expected_return = Σ p_i * train_mean_i` and `expected_vn_return = expected_return / realized_vol`. The name matches the value. Six existing tests updated. Full suite 629 pass.

## Why it stayed hidden

The bug shipped in Sprint 093 (prediction) and Sprint 094 (policy). It remained hidden because no trained model had been fed into the simulator until phase close. Every prior smoke used a random-weight checkpoint from step 8 of an untrained xs run.

## Lesson

A trained model must be fed through the full downstream chain — prediction, policy, ledger, metric — before the chain can be trusted. Isolated unit tests on each stage did not catch a mismatch that only manifests when a real distribution meets a real policy.

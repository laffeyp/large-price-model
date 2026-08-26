#!/usr/bin/env python3
"""Training CLI -- reads tokens parquet + config, runs the transformer trainer.

Emits the full training tag surface: WINDOW_SAMPLED per window,
TRAINING_STEP_COMPLETED per step, CHECKPOINT_WRITTEN at every eval,
EPOCH_COMPLETED at end, TRAINING_DIVERGED on NaN or grad-explosion.

Every training scalar lands in the SDD JSONL trace at
`logs/{run_id}/signals.jsonl`. That trace is the log; downstream plots
read from it.
"""

import argparse
import hashlib
import os
import sys
import traceback
import urllib.error
import urllib.request
from pathlib import Path

import torch

from price_space_llm.config import (
    ConfigValidationFailed,
    ContextLenConfig,
    ContextLenConfigValidationFailed,
    ModelSizeConfig,
    ModelSizeConfigValidationFailed,
    load_config,
    load_context_len_config,
    load_model_size_config,
)
from price_space_llm.git import git_sha
from price_space_llm.model import (
    MarketStateTransformerConfig,
    TransformerConfig,
    load_tokens,
    load_tokens_pt,
    run_training,
    run_training_feats,
)
from price_space_llm.model.trainer import (
    QuantileHeadRequiresRawTargets,
    TrainerConfig,
    TrainingDiverged,
    UnnormalizedArtifactRefused,
)
from price_space_llm.script_harness import script_session


def _detect_ec2_instance_id() -> str | None:
    """Return the EC2 instance-id via IMDSv2, or None if not on EC2.

    Sprint 107: on an EC2 host, IMDSv2 answers within milliseconds at
    169.254.169.254; off EC2 the connection times out. A 0.5s timeout is
    enough to distinguish the two cases without slowing local runs.
    """
    try:
        token_req = urllib.request.Request(
            "http://169.254.169.254/latest/api/token",
            method="PUT",
            headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"},
        )
        with urllib.request.urlopen(token_req, timeout=0.5) as resp:
            token = resp.read().decode()
        meta_req = urllib.request.Request(
            "http://169.254.169.254/latest/meta-data/instance-id",
            headers={"X-aws-ec2-metadata-token": token},
        )
        with urllib.request.urlopen(meta_req, timeout=0.5) as resp:
            return resp.read().decode()
    except (urllib.error.URLError, OSError, TimeoutError):
        return None


def _enforce_ec2_authorization_guard() -> None:
    """Sprint 107 guard: refuse to run on EC2 unless PSLM_AUTHORIZED_GPU_RUN=1.

    Prevents an accidental `python scripts/train.py` on a still-running rented
    box from silently burning wall-time. The intended flow is:
    provision_gpu.sh boots the box, sync_to_gpu.sh pushes the payload,
    user-data on the box invokes `PSLM_AUTHORIZED_GPU_RUN=1 python scripts/train.py`.

    The env var `PSLM_SKIP_EC2_CHECK=1` disables the guard for tests.
    """
    if os.environ.get("PSLM_SKIP_EC2_CHECK") == "1":
        return
    instance_id = os.environ.get("AWS_EC2_INSTANCE_ID") or _detect_ec2_instance_id()
    if instance_id is None:
        return  # not on EC2
    if os.environ.get("PSLM_AUTHORIZED_GPU_RUN") == "1":
        return
    print(
        f"train: refusing to run on EC2 instance {instance_id} without "
        f"PSLM_AUTHORIZED_GPU_RUN=1. Set the env var explicitly to launch a "
        f"training run; this guard prevents accidental wall-time burn on a "
        f"still-running rented instance.",
        file=sys.stderr,
    )
    sys.exit(1)


def _resolve_device(spec: str) -> str:
    """Sprint 051: resolve `--device auto` to the concrete best-available device.

    Order: cuda > mps > cpu. Explicit `--device cuda|mps|cpu` passes through
    unchanged; the caller is trusted to know their box.
    """
    if spec != "auto":
        return spec
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def main(argv: list[str] | None = None) -> int:
    _enforce_ec2_authorization_guard()  # Sprint 107 EC2 authorization guard
    parser = argparse.ArgumentParser(prog="train")
    parser.add_argument(
        "--tokens",
        type=Path,
        default=None,
        help="Path to a tokens parquet from `scripts/bucketize.py` (bucket-ID path).",
    )
    # Sprint 053: multi-channel market-state training path. Consumes the
    # Sprint 052 .pt artifact via WindowSamplerFeats + MarketStateTransformer.
    # Mutually exclusive with --tokens.
    parser.add_argument(
        "--tokens-pt",
        type=Path,
        default=None,
        help="Path to a Sprint 052 tokenized .pt artifact. Triggers "
        "MarketStateTransformer training via run_training_feats.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/experiment/v1.json"),
    )
    parser.add_argument(
        "--checkpoint-dir",
        type=Path,
        default=Path("artifacts/checkpoints"),
    )
    parser.add_argument("--logs-dir", type=Path, default=Path("logs"))
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--n-steps", type=int, default=50)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--eval-every", type=int, default=25)
    # Sprint 051: pre-GPU review blocker #4 (device handling).
    # `auto` resolves to cuda > mps > cpu. Explicit `cuda` fails loud if CUDA
    # isn't available (torch raises inside .to("cuda")); that's the correct
    # behavior for a GPU-explicit run against a CPU box.
    parser.add_argument(
        "--device",
        choices=("cpu", "cuda", "mps", "auto"),
        default="auto",
    )
    # Sprint 057: AdamW + cosine + bf16 + deterministic knobs.
    parser.add_argument("--warmup-steps", type=int, default=2000)
    parser.add_argument("--weight-decay", type=float, default=0.1)
    parser.add_argument("--lr-min-frac", type=float, default=0.1)
    parser.add_argument(
        "--bf16",
        action="store_true",
        help="Enable bfloat16 autocast. Auto-on for cuda; opt-in for cpu/mps.",
    )
    parser.add_argument(
        "--no-deterministic",
        dest="deterministic",
        action="store_false",
        default=True,
        help="Skip torch.use_deterministic_algorithms(True, warn_only=True).",
    )
    # Sprint 058: purged embargo + top-K checkpoint selection.
    parser.add_argument("--embargo", type=int, default=0)
    parser.add_argument(
        "--keep-top-k",
        type=int,
        default=0,
        help="0 keeps every checkpoint; positive value prunes to top-K by val_nll.",
    )
    # Sprint 073: config-driven model sizes (Phase E, roadmap 067).
    parser.add_argument(
        "--model-size",
        choices=("xs", "sm", "md", "lg"),
        default=None,
        help="Load configs/model/{name}.json for the transformer shape.",
    )
    parser.add_argument(
        "--model-config",
        type=Path,
        default=None,
        help="Load a specific model-size JSON. Mutually exclusive with --model-size.",
    )
    # Sprint 074: config-driven context lengths (Phase E, roadmap 068).
    parser.add_argument(
        "--context-size",
        choices=("64", "128", "256", "512"),
        default=None,
        help="Load configs/context/{N}.json and overlay context_len onto the experiment config.",
    )
    parser.add_argument(
        "--context-config",
        type=Path,
        default=None,
        help="Load a specific context-length JSON. Mutually exclusive with --context-size.",
    )
    # Sprint 083: channel-fusion knob (roadmap 069, tech-arch § 10).
    parser.add_argument(
        "--fusion",
        choices=("sum", "mixer"),
        default="sum",
        help="Embedder shape: 'sum' (linear per-channel sum, Sprint 053) or "
        "'mixer' (cross-channel attention, Sprint 083).",
    )
    parser.add_argument("--mixer-dim", type=int, default=96)
    parser.add_argument("--mixer-n-heads", type=int, default=2)
    # Sprint 087: patch-fusion knob per tech-arch § 10.
    parser.add_argument(
        "--patch-size",
        choices=("1", "4"),
        default="1",
        help="Bar-packing patch size: 1 (default; per-bar) or 4 (packs four "
        "consecutive bars per model position; overrides --fusion).",
    )
    # Sprint 089: head-type knob per tech-arch § 10.
    parser.add_argument(
        "--head-type",
        choices=("categorical", "quantile"),
        default="categorical",
        help="Output head: 'categorical' (default; 32-bucket softmax + CE) or "
        "'quantile' (9-quantile pinball loss on raw log_return).",
    )
    # Sprint 113 (from Sprint 112 tech debt): free-form run-id suffix so
    # experiments that share size/steps/seed but differ elsewhere never collide
    # on checkpoint paths. Empty string == pre-Sprint-113 behavior.
    parser.add_argument(
        "--run-id-tag",
        default="",
        help="Suffix appended to run_id to prevent checkpoint collisions.",
    )
    # Sprint 113 (roadmap 066): target-only ablation. Zeros non-target channels
    # in the tokenized artifact via `zero_non_target_features` before training.
    # The transformer sees only the target-symbol's own features; every other
    # channel comes in as zeros. Used to test whether multi-channel input is
    # adding value (or subtracting it).
    parser.add_argument(
        "--target-only",
        action="store_true",
        help="Zero non-target channels in the artifact before training.",
    )
    # Sprint 090: bucket-count override (roadmap 072). None → use config value.
    parser.add_argument(
        "--n-buckets",
        type=int,
        choices=(16, 32, 64),
        default=None,
        help="Override configs/experiment/v1.json's n_buckets for this run.",
    )
    args = parser.parse_args(argv)

    # Sprint 053: exactly one of --tokens / --tokens-pt is required.
    if bool(args.tokens) == bool(args.tokens_pt):
        print(
            "train: pass exactly one of --tokens (bucket-ID parquet) or "
            "--tokens-pt (market-state .pt artifact)",
            file=sys.stderr,
        )
        return 1

    # Sprint 073: at most one of --model-size / --model-config.
    if args.model_size is not None and args.model_config is not None:
        print(
            "train: pass at most one of --model-size / --model-config",
            file=sys.stderr,
        )
        return 1

    # Sprint 074: at most one of --context-size / --context-config.
    if args.context_size is not None and args.context_config is not None:
        print(
            "train: pass at most one of --context-size / --context-config",
            file=sys.stderr,
        )
        return 1

    repo_configs = Path(__file__).resolve().parents[1] / "configs"
    model_size: ModelSizeConfig | None = None
    context_len_cfg: ContextLenConfig | None = None
    try:
        if args.model_size is not None:
            model_size = load_model_size_config(repo_configs / "model" / f"{args.model_size}.json")
        elif args.model_config is not None:
            model_size = load_model_size_config(args.model_config)
        if args.context_size is not None:
            context_len_cfg = load_context_len_config(
                repo_configs / "context" / f"{args.context_size}.json"
            )
        elif args.context_config is not None:
            context_len_cfg = load_context_len_config(args.context_config)
    except ModelSizeConfigValidationFailed as ex:
        print(f"train: model-size config invalid: {ex}", file=sys.stderr)
        return 1
    except ContextLenConfigValidationFailed as ex:
        print(f"train: context-length config invalid: {ex}", file=sys.stderr)
        return 1
    tokens_path: Path = args.tokens or args.tokens_pt
    if not tokens_path.exists():
        print(f"train: tokens path not found: {tokens_path}", file=sys.stderr)
        return 1

    size_tag = f"-{args.model_size}" if args.model_size else ""
    ctx_tag = f"-c{args.context_size}" if args.context_size else ""
    fusion_tag = "-mix" if args.fusion == "mixer" else ""
    patch_tag = "-p4" if args.patch_size == "4" else ""
    head_tag = "-qh" if args.head_type == "quantile" else ""
    bucket_tag = f"-b{args.n_buckets}" if args.n_buckets is not None else ""
    # Sprint 113 fix: a user-facing tag suffix (Sprint 113a) plus an automatic
    # hyperparameter fingerprint (Sprint 113b) prevent run_id collisions between
    # experiments that share size/steps/seed but differ in other hyperparameters
    # (weight_decay, lr, warmup, target-only, etc.). The tag is optional; the
    # fingerprint is always appended. Two distinct configs cannot collide.
    user_tag = f"-{args.run_id_tag}" if args.run_id_tag else ""
    hp_fingerprint_payload = "|".join([
        f"lr={args.lr}",
        f"wd={args.weight_decay}",
        f"wu={args.warmup_steps}",
        f"lrmin={args.lr_min_frac}",
        f"bf16={int(args.bf16)}",
        f"embargo={args.embargo}",
        f"topk={args.keep_top_k}",
        f"tgtonly={int(args.target_only)}",
        f"fusion={args.fusion}",
        f"mixdim={args.mixer_dim}",
        f"mixh={args.mixer_n_heads}",
        f"patch={args.patch_size}",
        f"head={args.head_type}",
        f"batch={args.batch_size}",
        f"deterministic={int(args.deterministic)}",
    ])
    hp_hash = hashlib.sha256(hp_fingerprint_payload.encode()).hexdigest()[:8]
    hp_tag = f"-hp{hp_hash}"
    run_id = (
        f"train-{tokens_path.stem}{size_tag}{ctx_tag}{fusion_tag}"
        f"{patch_tag}{head_tag}{bucket_tag}{user_tag}{hp_tag}"
        f"-s{args.n_steps}-{args.seed:016d}"
    )
    if not args.config.exists():
        print(f"train: config not found: {args.config}", file=sys.stderr)
        return 1
    config_hash = hashlib.sha256(args.config.read_bytes()).hexdigest()
    data_hash = hashlib.sha256(tokens_path.read_bytes()).hexdigest()

    result = None
    with script_session(
        run_kind="train",
        run_id=run_id,
        config_hash=config_hash,
        data_hash=data_hash,
        seed=args.seed,
        logs_dir=args.logs_dir,
    ) as (emitter, sink_path):
        # Sprint 084 (v0.7): CONFIG_RESOLVED now requires the six model
        # architecture fields; resolve them from the model_size overlay before
        # emit so the payload stays self-describing regardless of default vs
        # --model-size vs --model-config path.
        resolved_d_model = model_size.d_model if model_size else 64
        resolved_n_layers = model_size.n_layers if model_size else 4
        resolved_n_heads = model_size.n_heads if model_size else 4
        try:
            config_result = load_config(
                args.config,
                emitter=emitter,
                run_id=run_id,
                git_sha=git_sha(),
                d_model=resolved_d_model,
                n_layers=resolved_n_layers,
                n_heads=resolved_n_heads,
                fusion=args.fusion,
                mixer_dim=args.mixer_dim,
                mixer_n_heads=args.mixer_n_heads,
            )
        except ConfigValidationFailed as ex:
            print(f"train: config invalid: {ex}", file=sys.stderr)
            return 1
        cfg = config_result.config

        # Sprint 074: overlay context_len from --context-size / --context-config.
        # Re-runs Pydantic validation so a hand-authored off-spec value fails loud
        # even if it slipped through the ContextLenConfig.model_validate step.
        if context_len_cfg is not None:
            cfg = cfg.__class__.model_validate(
                {**cfg.model_dump(), "context_len": context_len_cfg.context_len}
            )
        # Sprint 090: --n-buckets overlay; re-runs Pydantic for the same reason.
        if args.n_buckets is not None:
            cfg = cfg.__class__.model_validate(
                {**cfg.model_dump(), "n_buckets": args.n_buckets}
            )
        print(
            f"train: context_len={cfg.context_len} n_buckets={cfg.n_buckets}",
            file=sys.stderr,
        )

        trainer_cfg = TrainerConfig(
            n_steps=args.n_steps,
            batch_size=args.batch_size,
            lr=args.lr,
            eval_every=args.eval_every,
            seed=args.seed,
            warmup_steps=args.warmup_steps,
            weight_decay=args.weight_decay,
            lr_min_frac=args.lr_min_frac,
            bf16=args.bf16,
            deterministic=args.deterministic,
            embargo=args.embargo,
            keep_top_k=args.keep_top_k,
        )
        device = _resolve_device(args.device)
        print(f"train: device={device}", file=sys.stderr)

        try:
            if args.tokens_pt is not None:
                # Sprint 053: market-state path via .pt artifact.
                artifact = load_tokens_pt(args.tokens_pt)
                # Sprint 113 (roadmap 066): target-only ablation.
                if args.target_only:
                    from price_space_llm.model import zero_non_target_features
                    artifact = zero_non_target_features(artifact, cfg.target_symbol)
                    n_zeroed = len(artifact.channel_names) - 1
                    print(
                        f"train: target-only mode -- zeroed {n_zeroed} non-target "
                        f"channels; keeping only target__{cfg.target_symbol}",
                        file=sys.stderr,
                    )
                channel_dims = {k: int(v.shape[1]) for k, v in artifact.features.items()}
                pt_model_kwargs: dict[str, int] = {}
                if model_size is not None:
                    pt_model_kwargs = {
                        "d_model": model_size.d_model,
                        "n_layers": model_size.n_layers,
                        "n_heads": model_size.n_heads,
                    }
                pt_model_cfg = MarketStateTransformerConfig(
                    vocab_size=cfg.n_buckets,
                    context_len=cfg.context_len,
                    channel_dims=channel_dims,
                    fusion=args.fusion,
                    mixer_dim=args.mixer_dim,
                    mixer_n_heads=args.mixer_n_heads,
                    patch_size=int(args.patch_size),
                    head_type=args.head_type,
                    **pt_model_kwargs,
                )
                print(
                    f"train: model shape d_model={pt_model_cfg.d_model} "
                    f"n_layers={pt_model_cfg.n_layers} n_heads={pt_model_cfg.n_heads} "
                    f"fusion={pt_model_cfg.fusion} patch_size={pt_model_cfg.patch_size} "
                    f"head_type={pt_model_cfg.head_type}",
                    file=sys.stderr,
                )
                if artifact.targets.shape[0] < cfg.context_len + 2:
                    print(
                        f"train: only {artifact.targets.shape[0]} rows; "
                        f"need at least {cfg.context_len + 2}",
                        file=sys.stderr,
                    )
                    return 1
                result = run_training_feats(
                    artifact=artifact,
                    trainer_cfg=trainer_cfg,
                    model_cfg=pt_model_cfg,
                    emitter=emitter,
                    run_id=run_id,
                    checkpoint_dir=args.checkpoint_dir,
                    device=device,
                )
            else:
                tokens = load_tokens(args.tokens, cfg.target_symbol)
                if len(tokens) < cfg.context_len + 2:
                    print(
                        f"train: only {len(tokens)} tokens; need at least {cfg.context_len + 2}",
                        file=sys.stderr,
                    )
                    return 1
                bucket_model_kwargs: dict[str, int] = {}
                if model_size is not None:
                    bucket_model_kwargs = {
                        "d_model": model_size.d_model,
                        "n_layers": model_size.n_layers,
                        "n_heads": model_size.n_heads,
                    }
                bucket_model_cfg = TransformerConfig(
                    vocab_size=cfg.n_buckets,
                    context_len=cfg.context_len,
                    **bucket_model_kwargs,
                )
                print(
                    f"train: model shape d_model={bucket_model_cfg.d_model} "
                    f"n_layers={bucket_model_cfg.n_layers} n_heads={bucket_model_cfg.n_heads}",
                    file=sys.stderr,
                )
                result = run_training(
                    tokens=tokens,
                    trainer_cfg=trainer_cfg,
                    model_cfg=bucket_model_cfg,
                    emitter=emitter,
                    run_id=run_id,
                    checkpoint_dir=args.checkpoint_dir,
                    device=device,
                )
        except TrainingDiverged as ex:
            print(f"train: diverged: {ex}", file=sys.stderr)
            return 2
        except UnnormalizedArtifactRefused as ex:
            print(f"train: unnormalized artifact refused: {ex}", file=sys.stderr)
            return 3
        except QuantileHeadRequiresRawTargets as ex:
            print(f"train: quantile head refused: {ex}", file=sys.stderr)
            return 4
        except (FileNotFoundError, ValueError):
            traceback.print_exc(file=sys.stderr)
            return 1

    if result is not None:
        print(
            f"train: {result.final_step} steps in {result.elapsed_seconds:.2f}s; "
            f"final_train_loss={result.final_train_loss:.4f}; "
            f"checkpoints={result.n_checkpoints}; "
            f"params={result.n_parameters}; trace={sink_path}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())

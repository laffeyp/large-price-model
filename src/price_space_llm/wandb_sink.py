"""W&B sink that wraps wandb.init/log/finish and routes failures into
`WANDB_UPLOAD_FAILED` emits.

Sprint 040 landed this. Any `wandb.errors.Error` from init, log, or finish
becomes one WANDB_UPLOAD_FAILED emission with the `artifact_kind` enum value
that matches the operation (`per_step_scalar` for step logs, `checkpoint_ref`
for checkpoint uploads, per v0.3 vocabulary payload spec).

The sink never propagates W&B exceptions upward. If W&B fails, training keeps
running against the local trace — the SDD JSONL sink IS the audit log; W&B is
a convenience surface for real-time monitoring on remote GPU runs.

Modes: `online` (needs `WANDB_API_KEY`), `offline` (writes to `dir/wandb/` on
disk without network — Sprint 040's local smoke uses this), `disabled` (init
returns a stub, all log calls no-op — used in unit tests).
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import wandb
from wandb.errors import Error as WandbError

from price_space_llm.signals import StrictSignalEmitter

WandbMode = Literal["online", "offline", "disabled"]


@dataclass(slots=True, frozen=True, kw_only=True)
class WandbConfig:
    project: str
    run_name: str
    config: dict[str, Any] = field(default_factory=dict)
    mode: WandbMode = "offline"
    dir: Path = field(default_factory=lambda: Path("wandb"))


class WandbSink:
    """Context manager around a single wandb Run.

    Usage:
        with WandbSink(cfg, emitter, run_id) as sink:
            sink.log_step(step, {"train_loss": 3.5})
            sink.log_checkpoint(step, ckpt_path, {"val_nll": 3.2})
    """

    __test__ = (
        False  # keep pytest from collecting classes starting with "W" is fine but be explicit
    )

    def __init__(
        self,
        cfg: WandbConfig,
        emitter: StrictSignalEmitter,
        run_id: str,
    ) -> None:
        self._cfg = cfg
        self._emitter = emitter
        self._run_id = run_id
        self._run: Any = None

    def __enter__(self) -> "WandbSink":
        try:
            self._cfg.dir.mkdir(parents=True, exist_ok=True)
            self._run = wandb.init(
                project=self._cfg.project,
                name=self._cfg.run_name,
                config=dict(self._cfg.config),
                mode=self._cfg.mode,
                dir=str(self._cfg.dir),
            )
        except WandbError as ex:
            self._emit_failure("per_step_scalar", f"init: {ex}")
            self._run = None
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._run is None:
            return
        try:
            wandb.finish()
        except WandbError as ex:
            self._emit_failure("per_step_scalar", f"finish: {ex}")

    def log_step(self, step: int, metrics: dict[str, float]) -> None:
        """Log per-step scalars. artifact_kind on failure = per_step_scalar."""
        if self._run is None:
            return
        try:
            wandb.log(metrics, step=step)
        except WandbError as ex:
            self._emit_failure("per_step_scalar", f"log_step={step}: {ex}")

    def log_checkpoint(
        self,
        step: int,
        ckpt_path: Path,
        metrics: dict[str, float],
    ) -> None:
        """Log checkpoint-boundary scalars + a checkpoint_path field.
        artifact_kind on failure = checkpoint_ref."""
        if self._run is None:
            return
        try:
            payload: dict[str, Any] = {**metrics, "checkpoint_path": str(ckpt_path)}
            wandb.log(payload, step=step)
        except WandbError as ex:
            self._emit_failure("checkpoint_ref", f"checkpoint step={step}: {ex}")

    @property
    def run_dir(self) -> Path | None:
        """Absolute path to the Run's on-disk directory, or None if init failed."""
        if self._run is None:
            return None
        return Path(self._run.dir)

    def _emit_failure(self, artifact_kind: str, error: str) -> None:
        self._emitter.emit(
            "WANDB_UPLOAD_FAILED",
            artifact_kind=artifact_kind,
            error=error,
        )

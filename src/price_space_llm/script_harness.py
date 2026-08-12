"""Shared CLI scaffolding: emitter + JSONL sink + `process_session`.

Every script under `scripts/` follows the same shape: build a run_id,
open a JSONL sink at `logs/{run_id}/signals.jsonl`, create a
`StrictSignalEmitter` against the current vocabulary, wrap the work
in `process_session` with `run_kind`, `config_hash`, `git_sha`,
`data_hash`, `seed`, and `run_id` payload. This module ships that
shape once so scripts can focus on their unique argparse + work body.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from price_space_llm.git import git_sha
from price_space_llm.signals import (
    StrictSignalEmitter,
    load_vocabulary,
    process_session,
)


@contextmanager
def script_session(
    *,
    run_kind: str,
    run_id: str,
    config_hash: str,
    data_hash: str,
    seed: int,
    logs_dir: Path,
) -> Iterator[tuple[StrictSignalEmitter, Path]]:
    """Yield `(emitter, sink_path)` inside a `process_session`.

    The emitter is bound to `logs_dir / run_id / signals.jsonl`.
    Callers emit through the emitter and the sink captures every
    signal to disk. `git_sha()` is called once and passed through to
    `process_session`.
    """
    sink_path = logs_dir / run_id / "signals.jsonl"
    emitter = StrictSignalEmitter(load_vocabulary(), jsonl_sink=sink_path)
    with process_session(
        run_kind=run_kind,
        config_hash=config_hash,
        git_sha=git_sha(),
        data_hash=data_hash,
        seed=seed,
        run_id=run_id,
        emitter=emitter,
    ):
        yield emitter, sink_path

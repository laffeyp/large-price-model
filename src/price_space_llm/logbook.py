"""Append-only experiments logbook per tech-arch §13.

One row per training run. `scripts/register_run.py` appends via `append_run`.
The CSV lives at `experiments/logbook.csv`; header written on first append.

Row schema per tech-arch §13 (verbatim column list):

    date, run_id, branch, git_sha, notes, target, model_size, context_len,
    patch_size, head_type, n_buckets, train_loss, val_nll, val_ece, val_brier,
    val_rps, val_dir_acc, held_out_sharpe, held_out_sharpe_se, lambda_risk,
    alpha_mag_weight, touched_test

Every column is a plain scalar; the CSV opens in any spreadsheet.
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, fields
from pathlib import Path

DEFAULT_LOGBOOK_PATH = Path("experiments/logbook.csv")


@dataclass(slots=True, frozen=True, kw_only=True)
class LogbookEntry:
    """One row of experiments/logbook.csv."""

    date: str  # YYYY-MM-DD
    run_id: str
    branch: str
    git_sha: str
    notes: str
    target: str  # e.g. "SPY"
    model_size: str  # xs/sm/md/lg/custom
    context_len: int
    patch_size: int
    head_type: str  # categorical / quantile / linear / target_only
    n_buckets: int
    train_loss: float
    val_nll: float
    val_ece: float
    val_brier: float
    val_rps: float
    val_dir_acc: float
    held_out_sharpe: float
    held_out_sharpe_se: float
    lambda_risk: float
    alpha_mag_weight: float
    touched_test: bool


def _header() -> list[str]:
    """Column order = dataclass field order = tech-arch §13 order."""
    return [f.name for f in fields(LogbookEntry)]


def append_run(entry: LogbookEntry, path: Path = DEFAULT_LOGBOOK_PATH) -> None:
    """Append `entry` to the CSV. Writes the header row if the file is empty
    or missing. Never rewrites existing rows; log is strictly append-only.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    file_is_new = not path.exists() or path.stat().st_size == 0
    with path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_header())
        if file_is_new:
            writer.writeheader()
        writer.writerow(asdict(entry))


def read_logbook(path: Path = DEFAULT_LOGBOOK_PATH) -> list[dict[str, str]]:
    """Read every row as a dict[str, str]. Empty file → empty list."""
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader)


__all__ = [
    "DEFAULT_LOGBOOK_PATH",
    "LogbookEntry",
    "append_run",
    "read_logbook",
]

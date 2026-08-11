# Sprint 015 — ruff RUF/ANN packs + package version bump

---

```yaml
---
id: 015
status: closed
phase: 1
pass_kind: architecture
determinism_budget: n/a
---
```

---

## scope

Close the two remaining `reviews/full-review-round-1.md` punch-list items in the tooling axis:

- **§2.1** add `RUF` (ruff-specific rules) and `ANN` (missing annotations) to `pyproject.toml § tool.ruff.lint.select`. Fix any findings. `D` (docstrings) stays deferred until module-count grows.
- **§2.7** package `version` field is `0.1.0` (placeholder). Bump to `0.10.0` to reflect "post-Sprint-10 shape." Not tied to vocabulary version (that's `0.2` and lives at `signals/0.2.json`); the two version numbers are independent.

One file guaranteed modified (`pyproject.toml`); more if ANN/RUF surface findings that need code fixes.

---

## prerequisites

- Sprint 014 closed.

---

## context_files

- `reviews/full-review-round-1.md` §2.1 and §2.7
- `pyproject.toml`
- `src/price_space_llm/signals.py`
- `tests/test_signals.py`

---

## signal contract

### Emits

Test-time only.

### Consumes

- `signals/0.2.json` (unchanged).

### Invariants

- All 29 existing tests pass.
- `uv run ruff check src tests` exit 0 under the extended rule set (RUF + ANN + existing E/F/I/UP/B/SIM/PT).
- `pyproject.toml § project.version` reads a value that matches the project's post-Sprint-10 shape (candidate: `0.10.0` or a dynamic scheme).

---

## artifact contract

### Files modified

- `pyproject.toml`:
  - `[tool.ruff.lint] select` extended with `"RUF"` and `"ANN"`.
  - `[project] version` bumped from `"0.1.0"` to `"0.10.0"`.
- `src/price_space_llm/signals.py` — if ANN/RUF surface annotation gaps, add them.
- `tests/test_signals.py` — same.

### Files created

None.

### Content assertions

- `pyproject.toml` `[tool.ruff.lint] select` includes `"RUF"` and `"ANN"`.
- `pyproject.toml` `[project] version` is `"0.10.0"` (or a dynamic scheme with a documented resolution).

### Command exit codes

- `uv sync --dev` exit 0.
- `uv run ruff check src tests` exit 0 with RUF + ANN active.
- `uv run ruff format --check src tests` exit 0.
- `uv run mypy src` exit 0.
- `uv run pytest tests/ -v` exit 0; 29 tests pass.
- `uv build` clean; wheel filename shows `0.10.0`.

---

## observation contract

Not applicable. `pass_kind: architecture`.

---

## done criteria

RUF + ANN active. Version reads `0.10.0`. 29 tests pass. All tools green.

---

## notes

**ANN scope.** `ANN001` (missing type annotation for function argument), `ANN201` (missing return annotation for public function), and friends. The wrapper module is already mostly annotated; ANN will surface any private helper that slipped through. Tests may need `-> None` returns added.

**RUF scope.** Ruff-specific rules covering `noqa` misuse (`RUF100` unused-noqa), mutable-class-attribute (`RUF012`), unnecessary iterable wrappers (`RUF013`), etc. Small codebase — few findings expected.

**Version scheme choice.** `0.10.0` is honest — ten sprints in, no public release. A dynamic scheme (`dynamic = ["version"]` reading from git tags via `hatch-vcs`) is cleaner but adds a build-time dep. Keep it simple this sprint; adopt dynamic when the first public release matters.

**Ignore rules — likely candidates.** `ANN401` (any-typed function arguments) may fire on `_check_str(v: Any)` etc. — `Any` is intentional for the type checkers. Ignore in `[tool.ruff.lint.per-file-ignores]` or downgrade selectively.

---

## plan-mode review checklist

- [x] Scope one paragraph, one concept (tooling extension + version).
- [x] One file guaranteed; more contingent on findings.
- [x] Signal contract vacuous.
- [x] Artifact contract gradable.
- [x] Determinism budget declared (n/a).

---

*Sprint 015. Tooling + version. Every full-review-round-1.md punch-list item addressed after this sprint.*

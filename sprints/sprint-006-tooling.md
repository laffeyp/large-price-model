# Sprint 006 — tooling (ruff, mypy, pytest strictness)

---

```yaml
---
id: 006
status: closed
phase: 1
pass_kind: architecture
---
```

---

## scope

Address `reviews/code-best-practices-round-1.md` §6. Add ruff for lint and format, mypy in strict mode for static type checking, and pytest strictness knobs (`--strict-markers`, `--strict-config`, `filterwarnings = ["error"]`, `xfail_strict = true`). Fix any findings the tools surface in existing code. One file modified: `pyproject.toml`. Possibly `src/price_space_llm/signals.py` and `tests/test_signals.py` if a finding needs a fix.

---

## prerequisites

- Sprint 005 closed.

---

## context_files

- `reviews/code-best-practices-round-1.md` (§6 tooling)
- `pyproject.toml`
- `src/price_space_llm/signals.py`
- `tests/test_signals.py`

---

## signal contract

### Emits

Test-time only.

### Consumes

- `signals/0.1.json` (unchanged).

### Invariants

- 18 tests continue to pass unchanged (or 18 remain green after any test-code fixes for lint/type warnings).
- `uv run ruff check src tests` exits 0.
- `uv run ruff format --check src tests` exits 0.
- `uv run mypy src` exits 0 (mypy on tests optional — pytest fixtures with dynamic types are noisy under strict mode; if tests fail cleanly under strict mypy, keep them in the scope; otherwise scope to `src` only).

---

## artifact contract

### Files modified

- `pyproject.toml` — add `ruff` and `mypy` to `[dependency-groups] dev`. Add `[tool.ruff]`, `[tool.ruff.lint]`, `[tool.mypy]`, `[[tool.mypy.overrides]]` for the `sdd` module (no upstream stubs), and pytest strictness knobs under `[tool.pytest.ini_options]`.
- `src/price_space_llm/signals.py` — apply fixes for whatever ruff / mypy surface.
- `tests/test_signals.py` — same, if in scope.

### Files created

None.

### Content assertions

- `pyproject.toml` `[dependency-groups] dev` includes `ruff` and `mypy`.
- `pyproject.toml` contains `[tool.ruff]` and `[tool.mypy]` sections.
- `pyproject.toml` `[tool.pytest.ini_options]` includes `addopts`, `filterwarnings`, `xfail_strict`.
- `pyproject.toml` contains a mypy override entry for `sdd` (no upstream stubs, so imports get ignored).

### Command exit codes

- `uv sync --dev` exit 0.
- `uv run ruff check src tests` exit 0.
- `uv run ruff format --check src tests` exit 0.
- `uv run mypy src` exit 0.
- `uv run pytest tests/ -v` exit 0; all 18 tests pass.
- `uv build` clean.

---

## observation contract

Not applicable. `pass_kind: architecture` — tooling adoption changes zero product behavior.

---

## done criteria

Ruff, mypy, and pytest strictness all run clean. 18 tests pass under the stricter pytest config.

---

## notes

**Ruff rule set.** Start with `E` (pycodestyle errors), `F` (Pyflakes), `I` (isort), `UP` (pyupgrade), `B` (bugbear), `SIM` (flake8-simplify), `PT` (flake8-pytest-style). These cover the common problem classes without configuring a large surface up front. Additional rule packs (`ANN`, `D`, `S`) can adopt in later sprints when their signal-to-noise pays back.

**Mypy scope.** `src` for sure. `tests` if pytest fixture types don't force too many `# type: ignore` comments. If tests scope creates noise, restrict `files = ["src/price_space_llm"]` and file a followup to write stubs for the noisy paths.

**Sdd module override.** `sdd.py` lives in `sdd-kit-2/lib/`. It has no upstream stub file. Mypy would flag every `from sdd import ...` as `Cannot find implementation or library stub`. Override:

```toml
[[tool.mypy.overrides]]
module = "sdd"
ignore_missing_imports = true
```

A followup sprint could write `sdd.pyi` if the kit's reference emitter grows.

**Pytest strictness.** `filterwarnings = ["error"]` turns Pydantic / library deprecation warnings into failures. Any DeprecationWarning from the current stack (Python 3.13, pytest 9.1.1, hatchling) needs a filter added; if the noise is real, back off to `["error", "ignore::PendingDeprecationWarning"]`.

**One-shot fix scope.** This sprint fixes whatever ruff and mypy surface in existing code. If the finding count exceeds a dozen non-trivial items, split — some findings warrant their own sprint (e.g. adding return-type annotations across a wide surface). Sprint card contract: report the count in the Signal Report; Architect calls scope adjustment there.

---

## plan-mode review checklist

- [ ] Scope one paragraph (tooling adoption + fixes for findings).
- [ ] One file guaranteed modified; two more contingent on findings.
- [ ] Signal contract vacuous.
- [ ] Artifact contract is gradable via four `uv run` commands.
- [ ] Sprint dispatches on Architect "go".

---

*Sprint 006. Tooling. Phase 1 Sprint 007 opens the MCP bridge mapping.*

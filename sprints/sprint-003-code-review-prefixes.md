# Sprint 003 — code-review pre-fixes (before more feature work)

---

```yaml
---
id: 003
status: closed
phase: 1
pass_kind: architecture
---
```

---

## scope

Address the four "Before Sprint 003" items from `reviews/code-best-practices-round-1.md`. One is a ship-blocker: the module-level `_VOCAB_PATH` walks three levels up from `signals.py`, which resolves under editable install but not under a wheel install (nothing under `site-packages/` walks up to a `signals/` directory). The other three are one-liners: delete a double-validate call, add `encoding="utf-8"` in two places, delete sprint narration from two docstrings.

Fix by moving vocabulary loading to `importlib.resources` against a package sub-resource `price_space_llm._vocab`. Keep `signals/0.1.json` at project root as the authoring source of truth; expose it inside the package via a symlink at `src/price_space_llm/_vocab/0.1.json`. Editable install reads the symlink; wheel install reads what hatchling force-includes at that path. One source of truth, no drift.

---

## prerequisites

- Sprint 002 closed.
- `reviews/code-best-practices-round-1.md` on file.

---

## context_files

- `reviews/code-best-practices-round-1.md` (findings §1, §3 double-validate, §3 encoding, §7)
- `src/price_space_llm/signals.py`
- `tests/test_signals.py`
- `pyproject.toml`
- `signals/0.1.json`
- `sdd-kit-2/AGENTS.md` § hard rule 7 (edit in place, preserve accreted detail via SEARCH/REPLACE)

---

## signal contract

### Emits

Test-time only. The existing seven tests continue to fire the same tag set with the same payloads.

### Consumes

- `signals/0.1.json` (via `price_space_llm._vocab` sub-resource; symlink under editable install).

### Invariants

- Every existing test passes unchanged.
- The vocabulary loads under both editable install (`uv sync`) AND a wheel install (`uv build` then `pip install dist/*.whl` in a fresh venv).
- No sprint numbers remain in docstrings.
- All file I/O uses explicit `encoding="utf-8"`.

---

## artifact contract

### Files created

- `src/price_space_llm/_vocab/__init__.py` (empty; makes `_vocab` a package for `importlib.resources`).
- `src/price_space_llm/_vocab/0.1.json` (symlink → `../../../signals/0.1.json`; hatchling follows symlinks at wheel-build time).

### Files modified

- `src/price_space_llm/signals.py` — replace path-walk vocabulary load with `importlib.resources`; delete `self._vocab.validate(tag, payload)` at the top of `emit()`; add `encoding="utf-8"` to the read-text call and the sink `open("a")` call; strip sprint numbers from module docstring.
- `tests/test_signals.py` — strip sprint numbers from module docstring; no test-logic changes.
- `pyproject.toml` — add `[tool.hatch.build.targets.wheel.force-include]` entry mapping `signals/0.1.json` → `price_space_llm/_vocab/0.1.json` so the wheel bundles the file at the packaged path.

### Content assertions

- `src/price_space_llm/signals.py` does not contain the substring `parents[2]` or `_VOCAB_PATH`.
- `src/price_space_llm/signals.py` imports from `importlib.resources`.
- `src/price_space_llm/signals.py` calls `self._vocab.validate` at most once inside `emit()` (delete the explicit pre-call).
- `src/price_space_llm/signals.py` passes `encoding="utf-8"` to every file-open call.
- `src/price_space_llm/signals.py` docstring does not contain the substring `Sprint 001` or `Sprint 002`.
- `tests/test_signals.py` docstring does not contain the substring `Sprint 001` or `Sprint 002`.
- `pyproject.toml` `[tool.hatch.build.targets.wheel.force-include]` block includes both `"sdd-kit-2/lib/sdd.py" = "sdd.py"` and `"signals/0.1.json" = "price_space_llm/_vocab/0.1.json"`.
- `src/price_space_llm/_vocab/0.1.json` resolves to the same file as `signals/0.1.json` (symlink target matches; both `sha256` of contents match).

### Command exit codes

- `uv sync --dev` exit 0.
- `uv run pytest tests/ -v` returns 0; all 7 tests pass unchanged.
- `uv build` produces `dist/price_space_llm-0.1.0-*.whl` (exit 0).
- Fresh-venv wheel install works: `python3 -m venv /tmp/psllm-wheel && /tmp/psllm-wheel/bin/pip install dist/price_space_llm-0.1.0-*.whl && /tmp/psllm-wheel/bin/python -c "from price_space_llm.signals import get_emitter; print(len(get_emitter()._vocab.tags()))"` prints `55` and returns 0. (If Sprint 003 keeps the module-level `emitter` for backwards compat, the check reads `emitter` instead of `get_emitter()`.)

---

## observation contract

Not applicable. `pass_kind: architecture` — this sprint changes internal loading discipline without changing product behavior. The dual contract (signal + artifact) plus the wheel-install exit-code check is the verification.

---

## done criteria

Wheel install works. Seven tests pass. No sprint numbers in code docstrings. No double-validate. All file I/O has `encoding="utf-8"`.

---

## notes

**Why symlink, not copy.** A copy risks drift. The kit's "no deletions" hard rule and the vocabulary-is-the-contract commitment both push toward a single authoritative file. A symlink at `src/price_space_llm/_vocab/0.1.json` → `../../../signals/0.1.json` gives editable install one file (resolved at read time), wheel install the same file (hatchling follows the symlink at package time), and preserves `signals/0.1.json` at project root as the naming convention every doc references.

**Windows symlink caveat.** Symlinks on Windows require admin rights or Developer Mode. If a Windows contributor arrives, a `scripts/sync_vocab.py` or `Makefile` target copies the file explicitly. Not this sprint's problem; note in a followup issue if it becomes one.

**Deferring §2 (typed-payload enforcement) and §4 (`get_emitter` factory) to Sprint 004.** Those are meatier — extracting enum/type constraints from the JSON at load time is a real design decision (does the validator become a small interpreter of the JSON's type strings?). Worth its own sprint card and plan-mode review. This sprint is the mechanical cleanup that unblocks distribution.

**Not touching §5 (test brittleness) yet.** Same reasoning — the exact-count assertion, the wall-clock threshold in the clock-reset test, and the fake-hex fixtures are all real but not blocking. They ride with the §2 typed-payload sprint since the fake-hex fixtures break under the same upgrade.

**Not touching §6 (tooling) yet.** ruff + mypy adoption is a separate sprint. Compound-cost, real payback, but not this sprint's concept.

**Not touching §7's second bullet (test docstring).** Wait — §7 covers both `signals.py` and `test_signals.py`. Both docstrings get stripped this sprint.

---

## plan-mode review checklist

- [ ] Scope one paragraph, one concept (code-review pre-fixes).
- [ ] Three modified files, two new files (one is a symlink; the __init__ is empty ceremony).
- [ ] Signal contract is vacuous (no new emit surfaces).
- [ ] Artifact contract is gradable; wheel-install check is the load-bearing verification.
- [ ] Sprint dispatches on Architect "go".

---

*Sprint 003. Four fixes from the code review. One ship-blocker + three one-liners. Sprint 004 tackles typed-payload enforcement; Sprint 005 adopts ruff + mypy.*

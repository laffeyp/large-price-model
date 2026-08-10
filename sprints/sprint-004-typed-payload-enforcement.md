# Sprint 004 — typed-payload enforcement + real-hex fixtures

---

```yaml
---
id: 004
status: closed
phase: 1
pass_kind: architecture
---
```

---

## scope

Extend `StrictSignalVocabulary.validate` to enforce the `typed_payload` type strings the vocabulary declares — enum membership, primitive types (`str`, `int`, `float`, `bool`), format types (`sha256`, `uuid`, `date_iso`, `datetime_utc`, `path`), and container types (`list<T>`, `dict<K,V>`). The current validator checks tag names and required-key presence and refuses unknown keys; it silently accepts `run_kind="banana"`, `config_hash="a"*64`, `seed="not an int"`, and every other type mismatch. The vocabulary session took five rounds to nail down the types; the code ignores them. This sprint closes that gap.

Along with the enforcement upgrade, replace the test suite's fake-hex fixtures (`"a" * 64`, `"b" * 40`) with real hex, and add per-type raise-path tests. Two files modified: `src/price_space_llm/signals.py` and `tests/test_signals.py`.

Range checks (Layer 7 `range` kind — e.g. `p_up ∈ [0, 1]`), cardinality checks, frozen-artifact checks, and cross-run `gate` checks are NOT in this sprint. Those are grading-time or aggregate-time concerns; this sprint is emit-time type enforcement. Range enforcement lands in a later sprint alongside the observation-contract graders.

---

## prerequisites

- Sprint 003 closed.
- `reviews/code-best-practices-round-1.md` on file (this sprint executes review §2 and §5).

---

## context_files

- `reviews/code-best-practices-round-1.md` (§2 typed-payload; §5 test fixtures)
- `src/price_space_llm/signals.py` (current `StrictSignalVocabulary.validate` implementation)
- `tests/test_signals.py` (current fixture constants and seven tests)
- `signals/0.1.json` (source of truth for every `typed_payload` type string)
- `signals/0.1-rationale.md` § Layer 2 (type vocabulary — `str`, `int`, `float`, `bool`, `sha256`, `path`, `date_iso`, `datetime_utc`, `uuid`, `enum<VALUES>`, `entity_ref<Layer-0-entity>`, `list<T>`, `dict<K,V>`)
- `sdd-kit-2/AGENTS.md` § hard rule 2 (vocabulary is the contract)
- `sdd-kit-2/grammar/PRINCIPLES.md` commitment 2 (schema enforced at the speaker's mouth)

---

## signal contract

### Emits

Test-time only. Existing seven tests continue firing; new per-type tests add roughly ten more raise-path exercises. No pipeline emission changes.

### Consumes

- `signals/0.1.json` (already loaded by `load_vocabulary`; `typed_payload` entries now parsed for their type strings).

### Invariants

- Every existing test continues to pass after fixtures are updated.
- Enum values outside the declared set raise `ValueError` at emit.
- `sha256` fields with non-hex characters or wrong length raise.
- `uuid` fields with malformed strings raise.
- `date_iso` fields not matching `YYYY-MM-DD` raise.
- `datetime_utc` fields not parseable as ISO-8601 UTC raise.
- Primitive type mismatches (`int` given a `str`, `bool` given an `int`) raise.
- `list<T>` and `dict<K,V>` element type mismatches raise.
- `entity_ref<X>` values are accepted as opaque `str` — cross-reference resolution is a Layer-8 report concern, not a Layer-2 emit-time check.
- `path` accepts both `str` and `pathlib.Path`.
- No range checks (Layer 7 `range` kind) added this sprint; those come with the observation-contract graders.

---

## artifact contract

### Files modified

- `src/price_space_llm/signals.py` — `StrictSignalVocabulary.__init__` parses each tag's `typed_payload` type strings into a lookup structure (per-field callable checkers, computed once at load). `validate` runs each field's checker after the existing required and extras checks. New module-level helpers: `_parse_type(type_str) -> Checker`, `_check_enum(values)`, `_check_sha256(value)`, `_check_uuid(value)`, `_check_datetime_utc(value)`, `_check_date_iso(value)`, `_check_list_of(inner)`, `_check_dict_of(k, v)`, `_TYPE_CHECKERS: dict[str, Checker]`.
- `tests/test_signals.py` — module-level `VALID_SESSION_INIT_PAYLOAD` uses real hex via `hashlib.sha256(...).hexdigest()` and a real 40-char hex for `git_sha`. Same fix for the two other fixture constants. New tests: `test_enum_value_outside_declared_set_raises`, `test_sha256_wrong_length_raises`, `test_sha256_non_hex_raises`, `test_uuid_malformed_raises`, `test_datetime_utc_malformed_raises`, `test_date_iso_malformed_raises`, `test_int_type_mismatch_raises`, `test_bool_type_mismatch_raises`, `test_list_element_type_mismatch_raises`.

### Files created

None.

### Content assertions

- `src/price_space_llm/signals.py` defines a `_parse_type(type_str)` function that returns a callable which raises `ValueError` on type mismatch.
- `src/price_space_llm/signals.py` `_TYPE_CHECKERS` covers `str`, `int`, `float`, `bool`, `sha256`, `uuid`, `date_iso`, `datetime_utc`, `path`.
- `src/price_space_llm/signals.py` `StrictSignalVocabulary.__init__` stores per-field checkers on the schema.
- `src/price_space_llm/signals.py` `StrictSignalVocabulary.validate` calls each field's checker on the emitted value.
- `tests/test_signals.py` `VALID_SESSION_INIT_PAYLOAD["config_hash"]` equals `hashlib.sha256(b"...").hexdigest()` (a real 64-char lowercase hex string).
- `tests/test_signals.py` `VALID_SESSION_INIT_PAYLOAD["git_sha"]` is a 40-char lowercase hex string.
- `tests/test_signals.py` contains at least nine new tests exercising the type-check raise paths.

### Command exit codes

- `uv sync --dev` exit 0.
- `uv run pytest tests/ -v` returns 0; all 16+ tests pass.
- `uv run python -c "from price_space_llm.signals import emitter; emitter.emit('SESSION_INIT', run_id='r', run_kind='banana', vocab_version='0.1', config_hash='a'*64, git_sha='b'*40, data_hash='c'*64, seed=1)"` returns non-zero; stderr names `run_kind` and the allowed enum values.
- `uv build` produces a wheel; fresh-venv install still reads `tag count: 55`.

---

## observation contract

Not applicable. `pass_kind: architecture` — no product behavior changes; validator becomes stricter. The dual contract plus the new per-type test set is the verification.

---

## done criteria

`emitter.emit("SESSION_INIT", run_kind="banana", ...)` raises. `emitter.emit("SESSION_INIT", config_hash="not_hex", ...)` raises. The nine or more new tests pass. The seven existing tests still pass with real-hex fixtures.

---

## notes

**Type-string parsing shape.** Parse each `typed_payload` entry's `type` field once at `load_vocabulary` time. Store a callable per field on the schema. `validate` calls the callable on the value. No parsing at emit time — costly and unnecessary.

**Enum parsing.** `enum<probe|align|calibrate|train|eval|simulate>` → split on `|` between the angle brackets, store as a `frozenset`, checker compares membership.

**`sha256` format.** 64 lowercase hex characters. Regex `^[0-9a-f]{64}$`. The vocabulary's rationale doc names this as the standard hex form; git SHAs use the same character set at length 40.

**`git_sha` type.** The vocabulary types `git_sha` as `str`, not `sha256` — because 40-char, not 64. A per-format `_check_git_sha` (40-char lowercase hex) is worth adding, but for this sprint the field is typed `str` in the vocabulary and gets the loose `str` check. Tighten in a followup sprint that adds a `git_sha` format type to the vocabulary (a v0.2 candidate).

**`entity_ref<X>` handling.** Accept as opaque `str`. FK resolution — verifying the referent exists — is a Layer-8 report concern, not a Layer-2 emit-time check. The vocabulary types the field; the emitter validates the type; the reader validates the referent. Three layers, three checks; each in its own place.

**`list<T>` and `dict<K,V>` parsing.** Split on the outer `<` and `>`, recurse on the inner type strings. Nested containers (`list<dict<str, int>>`) parse the same way. The vocabulary uses container types sparingly; a small recursive parser handles all present cases.

**Range constraints deferred.** Layer 7 `range` and `gate` constraints (e.g. `p_up ∈ [0, 1]`, `sharpe_point > 0.5`) are aggregate or grading-time concerns, not emit-time. The vocabulary declares them; the reader enforces them at report time. Adding them at emit would slow every emit for a check that fires once per run in a Signal Report. Later sprint.

**Fake-hex fixture rework.** The review's §5 names this coupling: once §2 lands, `"a" * 64` fails the sha256 check because it's not a proper hex string. It IS a proper hex string ('a' is a hex char) — the check accepts it. Fake hex passes format validation because format validation only cares about the character class and length. What DOES fail is `"not_a_hash"` (wrong length AND non-hex characters outside the class). Fixture rework is still worth doing (real hex reads honestly to a reviewer scanning the test suite), but the failure mode the review predicted does not materialize for this specific case.

**Backwards compatibility.** Module-level `emitter` continues to construct at import. The type checks are stricter than the current validation; any existing emit call site with type-wrong payload starts raising. No such call site exists yet in this project (only the seven tests, all updated in this sprint).

---

## plan-mode review checklist

- [ ] Scope one paragraph, one concept (type enforcement at emit time).
- [ ] Two modified files, no new files.
- [ ] Signal contract is vacuous (no new emit surfaces; existing set enforced more strictly).
- [ ] Artifact contract is gradable; per-type test coverage is the verification.
- [ ] Sprint dispatches on Architect "go".

---

*Sprint 004. Typed-payload enforcement. Sprint 005 does the smaller §3 finishes + §4 factory + §6 tooling.*

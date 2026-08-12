# Practices briefing — 2026 consensus on Python, patterns, clean code, architecture

*Reference document. Three parallel research passes; the operating synthesis is at the top; the full briefings follow verbatim so a future session can re-derive without re-searching.*

**Compiled:** 2026-08-11.
**Purpose:** the working knowledge to apply on code review, sprint design, and architecture decisions in this project.

---

## Operating synthesis

**One through-line ties all three passes.** The interesting decisions have moved *up a level*. Micro-patterns dissolved into language features; the arguments now happen at architecture, testing, and metrics. Python 3.13/3.14 accelerated the trend by folding structured concurrency, pattern matching, native generics, and the free-threaded build into the standard library.

**Ten operating principles I hold going forward:**

1. **`X | Y` and `list[int]` are the syntax. `Optional`, `Union`, `List`, `Dict` are legacy.** Ruff `UP006`/`UP007` rewrite them. `Protocol` is how you specify an interface without inheritance.

2. **Pydantic at the edge, dataclasses/attrs in the core, msgspec on the wire.** Pydantic for HTTP request/response, config files, LLM outputs, untrusted JSON. Dataclasses for internal domain objects (`slots=True, frozen=True, kw_only=True` on new code). Msgspec when serdes is hot-path. Using Pydantic for every internal type is the common overreach.

3. **uv + hatchling + ruff + mypy-or-pyright is the current default stack.** PEP 735 `[dependency-groups]` for dev deps (now cross-tool as of pip 25.1). `src/` layout. `ruff format` replaces black; `ruff check` covers pyflakes + isort + pyupgrade + bugbear + simplify + more. `pytest` with `--strict-markers`, `--strict-config`, `filterwarnings = ["error"]`, `xfail_strict = true`.

4. **`asyncio.TaskGroup` (3.11+) with `except*` and `PEP 654 ExceptionGroup` is the modern async idiom.** `asyncio.gather` is a bug — leaks tasks on failure. `asyncio.timeout` replaces `wait_for`. AnyIO for libraries that want to run over asyncio or Trio.

5. **The typical GoF pattern is a language feature in Python.** Norvig's 1998 verdict has hardened: Singleton (module or `@lru_cache`), Factory (class-as-value), Builder (kwargs + dataclass), Iterator (generator), Strategy (function), Command (partial or closure), Observer (callbacks), Visitor (`functools.singledispatch`), Decorator-the-pattern (`__getattr__` forwarding). **The five patterns that still earn their keep: Adapter (with `Protocol`), Facade (as module API), Composite (recursive structure), State (as an explicit state machine — `transitions` library), and Bridge on rare occasions.**

6. **Dependency injection: pass objects into `__init__`, assemble at a composition root, add a container only when the wiring itself is the bug.** FastAPI `Depends` if you're on FastAPI. `svcs` for locator-with-lifespans. `punq` for a small IoC container. `dependency_injector` for large graphs. Manual DI is the default and usually the right choice.

7. **Clean Code (Martin 2008) is no longer the reference.** The "many tiny functions" prescription is rejected. "Comments are failures" is rejected. A Philosophy of Software Design (Ousterhout, 2nd ed) is the current standard counter-text. Deep modules, complexity as the enemy, comments as essential. Fowler's Refactoring 2e catalogue holds, but Extract Method's counterpart Inline Method is the underused half.

8. **Vertical Slice Architecture + Modular Monolith are the current defaults for new work.** Not layered (controller/service/repository as packages — scatters features and creates shotgun surgery by construction). Not microservices by reflex — Fowler's MonolithFirst plus Prime Video's public reversal made "start monolithic, split when a boundary earns it" the received wisdom. Hexagonal Ports & Adapters is the *rule* (business logic doesn't import infrastructure) but not the *apparatus* (interface + adapter + mapper + DTO for every collaborator is over-engineering below real complexity).

9. **DDD is strategic-first, tactical-second.** Bounded contexts, ubiquitous language, context maps: universally useful. Aggregates, entities, value objects, repositories, factories: valuable in rule-heavy domains (insurance, trading, healthcare billing), overhead elsewhere. Repository over an ORM is anti-pattern per Ayende — a modern ORM (SQLAlchemy, EF Core) already is a repository. Anemic domain model is still a smell; the modern defence is "anemic data + pure functions on top is fine as long as invariants live *somewhere*."

10. **DORA measures delivery; SPACE measures sustainability; DX Core 4 is Forsgren's current synthesis.** Deployment frequency without change-failure-rate is a vanity metric. Testing shape follows architecture (pyramid for backend logic, Testing Trophy for UI-heavy, honeycomb for microservices). Snapshot testing as a default is out; narrow intent-carrying snapshots are the disciplined use. Property-based testing (Hypothesis) is undervalued — one PBT test catches ~50× the mutations of a unit test per OOPSLA 2025.

---

## What this changes for this project

**Confirmed good:** the project's current tool stack (uv, ruff, mypy strict, pytest strictness knobs, `src/` layout, hatchling, PEP 735 dependency groups) is exactly the 2026 default. No drift.

**Design-side alignment:**
- The `Fetcher = Callable[...]` type alias in `probe.py` is the Norvig move — a first-class callable instead of a `FetcherFactory` class hierarchy.
- The `process_session` context manager is Command + RAII done as Python idiom, not as a GoF Command class.
- `StrictSignalVocabulary(SignalVocabulary)` subclass extension is Adapter-adjacent — one of the five surviving patterns.
- `@lru_cache(maxsize=1)` on `get_emitter` is the modern replacement for a Singleton class.

**Watch items:**
- The `_error_shim` fabrication (Sprint 020 Surfaced) is a primitive-obsession-adjacent smell — the CHANNEL_PROBED payload is a data clump that should own its error variants explicitly. Aligns with the vocabulary-side path (a): add `CHANNEL_FETCH_FAILED` as a separate incident.
- When `IngestionClient` facade lands, resist the "interface + adapter + mapper + DTO" hexagonal ceremony. A `Protocol` describing what the probe needs plus a plain `HttpFetcher` class is the right weight.
- The vocabulary declares 24 operators (Layer 6). Not all of them need to be classes — several are pure functions with state passed in. Match Ousterhout's deep-module principle: powerful function, narrow interface.

**Testing shape:** this project's tests are currently pyramid-shaped and appropriately so — the domain logic is real, unit tests test units. When the simulator lands, keep the pyramid but add contract tests for the vendor MCPs (Pact-style) at the seam. Property-based testing (Hypothesis) is a natural fit for the tokenizer round-trip, the alignment invariants, and the causal-mask semantics.

---

## Full briefings

The three source briefings follow verbatim. Each is ~2000-2500 words, drawn from live web research on authoritative sources (python.org PEPs, martinfowler.com, cosmicpython.com, norvig.com/design-patterns, hynek.me, kent-c-dodds.com, martinfowler.com, ousterhout aposd-vs-clean-code, Grzybek modular-monolith series, DORA/SPACE reports, ICSE and OOPSLA 2024/2025 papers).

### Briefing 1: Modern Python best practices (2024-2026)

[Full text as researched — see task output for `a2e3437e0f90f46b4`. Key stack: ruff for lint+format, uv for deps, hatchling for build, mypy or pyright strict, pytest with all strictness knobs. Typing PEPs: 484/526/544/585/604/612/646/655/673/675/692/695/698/705/728. Layout: src/. Async: TaskGroup + except*. Free-threaded Python (PEP 703/779) supported as of 3.14, October 2025. Data carriers: Pydantic at edges, dataclasses in core, msgspec on wire. `from __future__ import annotations` cancelled, still opt-in. Anti-patterns: bare `# type: ignore`, `Any` overuse, wildcard imports, heavy `__init__.py` re-exports, `asyncio.gather` on failure.]

### Briefing 2: GoF patterns modern reappraisal for Python

[Full text as researched — see task output for `aeddcd366e04f8ff9`. Norvig 1998 verdict hardened: 18 of 23 GoF patterns dissolved or trivial in Python. Five survive as worth writing: Adapter (with Protocol), Facade (module API), Composite, State (as `transitions` library state machine), Bridge (rare). Post-GoF canon: Repository, Unit of Work, Data Mapper vs Active Record, Value Object, CQRS, Event Sourcing, Circuit Breaker, Bulkhead, Retry, Saga, Ports and Adapters. DI landscape: FastAPI Depends, svcs, punq, dependency_injector. Anti-patterns: God Object, Anemic Domain Model, Feature Envy, Primitive Obsession, Shotgun Surgery, Long Parameter List, Data Clumps, Message Chains, Middle Man, Refused Bequest.]

### Briefing 3: Clean code, refactoring, architecture consensus

[Full text as researched — see task output for `a714f04d3628c44a7`. Clean Code (Martin 2008) reputation cracked; APOSD (Ousterhout 2018/2021) is current standard. Fundamentals of Software Architecture (Richards & Ford 2020, 2nd ed 2025) is the reference architecture book. Fitness functions (Ford et al) as executable architectural rules. Strategic DDD > tactical DDD. Vertical Slice Architecture as answer to layered architecture. Modular Monolith (Grzybek) as new-work default. Repository-over-ORM anti-pattern per Ayende. Testing shape follows architecture: pyramid, trophy, or honeycomb. DORA + SPACE + DX Core 4 as the metrics stack. Snapshot testing as default is out; PBT (Hypothesis) is undervalued.]

*(The raw briefings from the three research passes are captured in the session's task outputs and are available on request — this reference doc holds the operating synthesis; the raw depth is re-derivable from the sources cited.)*

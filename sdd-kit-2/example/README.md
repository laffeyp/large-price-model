# example/ — `wordcount`, a worked sdd-kit-2 project

*A tiny Python CLI that walks a directory, counts words/lines/chars per file, and produces a JSON report. Three sprints. Demonstrates the kit's discipline end-to-end on a project small enough to read in one sitting.*

*This isn't a separate kit. It's an instantiation of `sdd-kit-2/` applied to a small problem. Read it alongside the kit when authoring your first sprint card in a new project — it's faster than abstracting from templates.*

---

## What this example shows

- A real `signals/0.1.json` with 8 tags across 3 categories.
- Three sprint cards (one architecture-band, two functional-band) showing the dual + observation contract pattern.
- A `BLACKBOARD.md` with real entries after sprint 003 closes — Decisions, Built entries, a Surfaced-for-review halt that resolved, a Sprint tail.
- A `KIT_DIARY.md` with two entries showing what worked and what didn't.
- A `WORKING_AGREEMENT.md` filled in with the canonical home registry, dependency policy, and build commands for this specific project.
- Source code (`src/wordcount/`) that uses `sdd-kit-2/lib/sdd.py` for typed signal emission.
- Tests (`tests/`) that use `assert_signal` patterns over confirmed-good captures.

The project is intentionally tiny so the kit's overhead is visible. In a real project of 30+ sprints, the discipline pays for itself; in three sprints, you can see the shape without the payoff blurring it.

---

## Running the example

```
cd example/
pip install -e ../lib/  # makes sdd.py importable; or just symlink
python -m wordcount /path/to/some/dir --signals-out=trace.jsonl
cat trace.jsonl | jq
```

Or run the tests:

```
pytest tests/
```

The tests exercise the assert_signal pattern (Section 1 technique #38 in TECHNIQUES.md): each test runs the CLI on a fixture directory, captures signals, asserts on them rather than on the JSON output alone.

---

## Reading order

1. `BLACKBOARD.md` — start here. The `## Decisions` section names what the project is. The `## Built` section shows what shipped, sprint by sprint.
2. `signals/0.1.json` — the locked vocabulary. 8 tags, 3 categories.
3. `WORKING_AGREEMENT.md` — project-specific overrides (canonical homes, dependencies, build commands).
4. `sprints/sprint-001-vocabulary-and-scaffold.md` through `sprint-003-cli-and-jsonl-sink.md` — read in order. Note how each sprint's `context_files` references the prior sprint's outputs.
5. `KIT_DIARY.md` — what the project's running of the kit surfaced.
6. `src/wordcount/` — the actual code, organized per the canonical home registry.

---

## What this example does NOT show

- An end-game project. Three sprints is the discipline's smallest interesting unit; production projects ship dozens.
- A full Rubber Duck Pass transcript. Sprint 002's close has a 3-observation Pass written into the Sprint tail entry; sprints 001 and 003 have one-line pass summaries. Pass discipline scales with sprint complexity.
- A vocabulary evolution. The example is small enough that `signals/0.1.json` covers it from sprint 1. A 30-sprint project would show `0.1` → `0.2` migration; this one doesn't.
- A UI sprint. `wordcount` is a CLI; the UI-class techniques in TECHNIQUES.md Section 2 don't apply.

---

*example/wordcount — sdd-kit-2 applied to a tiny problem. Three sprints. The shape of the discipline without the noise of a real project. Pattern-match from here.*

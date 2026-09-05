# Collab-eval v2 Implementation Plan

**Goal:** Deliver a working, offline-verifiable v2 evaluation pipeline, draft pilot bank, and evidence report without overwriting v1 or claiming human validation.

**Architecture:** Isolate v2 in `collab_eval/v2/`. Bind immutable runs to embedded task/config snapshots; collect evidence-backed judgments and human adjudications; aggregate at family level. Generate escaped, self-contained HTML and paired comparison reports. External API commands are explicit and bounded; this implementation uses only mock/offline runs.

**Tech stack:** Existing Python, PyYAML, pytest, standard library HTTP and HTML. Ruff/mypy are development checks only.

## Tasks and verification

1. Schema and judgments — create `schema.py`, `scoring.py`, `tests/test_v2_scoring.py`. First assert invalid evidence, missing criteria, reviewer disagreement, later-turn boundary violations and unapplied adjudications cannot silently pass. Implement strict loading and four-state resolution. Run targeted tests.
2. Pilot bank — create `scenarios/v2/` with 20 substantive draft families across five domains and four conditions. Include evidence IDs, required outcomes, explicit scope, distinct acceptable solutions, invalid examples. All human review fields remain pending. Add 100 labeled draft calibration cases with a regression subset; do not claim independent calibration.
3. Immutable runs — create `runner.py`, `tests/test_v2_runner.py`. Freeze task/config snapshots, hash identities, bound calls, preserve errors and resume only identical completed trials. Mock and explicit OpenAI-compatible HTTP transport use the same interface. Invalid or truncated outputs remain visible.
4. Aggregation — create `analysis.py`, `tests/test_v2_analysis.py`. Test hand-calculated macro rates, unresolved bounds, missing trials, duplicate rejection, pair compatibility, family-cluster bootstrap and zero/single-family uncertainty. Do not report equivalence from overlapping intervals.
5. CLI/report — create `cli.py`, `report.py`, `report_template.html`, `tests/test_v2_cli.py`. Add `v2` dispatcher while retaining v1. Commands: validate, plan, run, judge, adjudicate, report, compare, demo. Reports include trace evidence, applicability and calibration status. Escape untrusted data and test malicious transcripts.
6. Integration — update README and CI; keep historical files unchanged. Run v1/v2 pytest, Ruff, strict mypy, offline report builds and browser smoke tests. Inspect generated UI and full diff. Commit implementation on `codex/collab-eval-v2`.

## Acceptance boundary

Deliver working software and authored draft data. Independent human review, live paid experiments, public result publication, tool execution and scheduled monitoring remain the explicit later gates in the approved design. New judgments are never manufactured from old scores. Demonstrations are permanently labeled synthetic.

## Progress

- [x] Isolated worktree created; original uncommitted design edit preserved.
- [x] Schemas and four-state scoring
- [x] Draft bank and calibration cases
- [x] Immutable runner and explicit judging
- [x] Family-level analysis and comparison
- [x] Evidence report and CLI
- [x] Verification and review

## Verification outcome

- 52 pytest tests pass, including the original v1 suite.
- Ruff lint and format checks pass; strict mypy passes for all 8 v2 Python modules; Python compilation succeeds.
- Both banks validate; offline preview builds with 20 draft families and 80 conditions.
- Recomputed v1 results equal the committed data after removing the generation timestamp.
- Browser checks cover desktop, 390 px mobile (including expanded evidence without horizontal overflow), domain/status filters and search empty state.
- Specification review passed. Code review findings were fixed with regressions: evidence output collision, manifest mode forgery, duplicate judge identities, malformed API responses, and preservation of sealed raw judgments.
- Independent human calibration and live model trials remain pending; no external model API was called.

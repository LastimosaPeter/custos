# Custos Next — Validation Report

Validation date: 2026-09-27

## Repairs in this revision

- Fixed Assessment sub-navigation HTTP 500 errors caused by duplicate Flask function declarations for `admin_dashboard`, `admin_testing`, and `admin_questions`. The decorators had been attached to one-line stub functions that returned `None`; the real implementations are now the registered routes.
- Removed student-visible question `topic` text from the live exam interface so internal labels such as “Spot the Error - Semicolon” cannot reveal the answer strategy.
- Added persistent student **Flag for Review** state on assigned exam questions (`session_questions.marked_for_review`).
- Added `/api/question-review` for saving/removing review flags without changing answers or proctoring counts.
- Question Navigator now distinguishes Answered, Current, and Flagged items. The exam footer also reports the current flagged count.
- On the final item, Review returns the student to the first flagged item, then the first unanswered item, before falling back to the navigator.
- Corrected instructor chat alignment: student messages are incoming on the left in gray; instructor replies are on the right in blue. Student-side chat retains its self/outgoing presentation.
- Added iOS-style Back / Forward controls to the standard Custos header. The secure live-exam header is intentionally excluded.
- Bumped the PWA static cache to `custos-static-v098-next3` so installed clients refresh the changed CSS/JS.

## Validation

- Python syntax compilation: PASS (`app.py`, `db.py`, `workspace.py`, `code_runner.py`, `item_analysis.py`)
- JavaScript syntax: PASS (`exam.js`, `mobile_ui.js`, `sw.js`)
- Jinja template syntax: PASS — all 28 templates parsed
- Route static check: PASS — no Flask route-decorated function is left without a return path due to duplicate stub declarations
- SQLite fresh schema: PASS — `session_questions.marked_for_review` exists
- SQLite initialization smoke test: PASS

## Database migration

Existing SQLite/PostgreSQL installations are additive-migrated at startup. `marked_for_review INTEGER NOT NULL DEFAULT 0` is added to `session_questions` if missing. Existing answers, sessions, scores, proctoring events, and question-bank data are preserved.

# Custos Unified Assessments — Validation Report

Validation date: 2026-09-27

## Static validation

- Python syntax compilation: **PASS** (`app.py`, `db.py`, `workspace.py`, `item_analysis.py`, `code_runner.py`, `init_db.py`)
- Duplicate top-level Python function check in `app.py`: **PASS**
- JavaScript syntax: **PASS** for every file under `static/js/`
- Jinja syntax: **PASS** for all 36 HTML templates
- PWA cache key bumped to `custos-static-v098-next13-unified-assessments`

## Database validation

A fresh SQLite schema was initialized in an isolated validation database using lightweight dependency stubs.

- `assessments.deleted_at` created: **PASS**
- seeded Midterm/Post-test/Dry Run/Programming Lab retained: **PASS**
- soft-delete behavior (`active=0`, `deleted_at=<timestamp>`): **PASS**
- custom objective assessment item analysis with 5 submitted sessions: **PASS**
- assessment-specific delivery summary and weighted mean score: **PASS**

The production path remains PostgreSQL whenever `DATABASE_URL` is present; SQLite is still the local fallback.

## Unified assessment administration

Implemented across legacy and custom assessments:

- one Dashboard catalog for all non-deleted assessments
- assessment deletion from Dashboard and Workspace using safe soft-delete semantics
- Question Banks assessment selector includes custom tests, Midterm, Post-test, Dry Run, and Caudex labs
- Item Analysis selector includes every assessment; custom objective tests use the same item-analysis engine
- Caudex programming labs receive task-level analytics
- Testing is assessment-aware for Midterm, Post-test, Dry Run, and custom objective tests; Caudex uses its isolated preview
- Live Monitor supports assessment filtering and assessment-aware student labels
- Dashboard/Workspace provide consistent Question Bank, Item Analysis, Monitor, and Testing entry points where applicable
- message conversations can be hard-deleted without deleting the exam attempt, answers, or proctoring history

## UI validation

- Assessment Catalog status chips are fixed beside the expand `+` affordance
- Live Monitor attention is represented by the full card outline: green/clear, orange/watch, orange-red/high, red/locked
- Custom Test field labels are smaller and bold
- Mobile catalog and assessment selector layouts remain responsive

## Safety / history behavior

Assessment deletion is deliberately a **soft delete**. It removes the assessment from active administration and disables its delivery sets, while preserving historical attempts and analytics records. Message deletion is a **hard delete of the conversation rows only**, which is the storage-saving action requested; exam answers and security logs remain intact.

## Limitation

A live browser/Flask/PostgreSQL integration test was not run in this packaging container because the system Python lacks Flask/Werkzeug. PostgreSQL schema generation uses the same migration definitions and the project includes the required Flask, psycopg2, Gunicorn, and related runtime dependencies in `requirements.txt`.

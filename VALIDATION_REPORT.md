# Custos Next — UI/UX & Workspace Revision Validation

Validation date: 2026-09-27

## Static validation

- Python syntax compilation: **PASS** (`app.py`, `db.py`, `workspace.py`, `code_runner.py`, `item_analysis.py`, `init_db.py`)
- JavaScript syntax: **PASS** for all files under `static/js/`
- Jinja template parse: **PASS** — 28 templates
- Fresh SQLite schema creation with dependency stubs: **PASS** — 22 tables
- Migration from the previous Custos Next SQLite schema: **PASS**
- New `exam_sessions` fields verified: `first_name`, `last_name`, `monitor_done`
- New `coding_sessions` fields verified: `first_name`, `last_name`

## UI/UX changes validated structurally

- Single reusable instructor navigation macro across instructor pages
- Workspace promoted to the primary instructor destination
- Assessment tools grouped beneath one Assessment navigation menu
- Dedicated Messages center added
- Session chat replies use AJAX and no longer require a page reload
- Answer Audit and Proctoring Event Log use a two-column desktop layout
- Live Monitor supports Clear Lock and non-destructive Mark Done actions
- Live Monitor activity dot has fixed square dimensions / circular radius
- Custos-first header lockup followed by subject logo
- Compact IDE Custos logo treatment
- IDE public entry replaced by Coming Soon page while feature flag is off
- PWA icons regenerated on white backgrounds
- PWA cache version incremented to force updated shell assets
- iPad landscape desktop-like overrides included
- Installed-app status converted to green boxed treatment
- Theme icon uses emoji sun/moon pair

## IDE release safety

Public student IDE access defaults to disabled through:

```env
STUDENT_IDE_ENABLED=0
```

Direct public `/ide` entry redirects to the Coming Soon page. Instructor management and preview remain available. `render.yaml` explicitly keeps the feature disabled.

## Database compatibility

Custos remains dual-mode:

- PostgreSQL when `DATABASE_URL` is configured
- SQLite fallback for local development

The schema changes are additive and the old `student_name` field is retained for compatibility.

## Environment limitation

A full Flask HTTP integration test was not run in the packaging container because the system Python does not include Flask/Werkzeug. Python/Jinja/JavaScript syntax and SQLite schema/migration behavior were validated independently. Install `requirements.txt` in the project virtual environment for the normal local run.

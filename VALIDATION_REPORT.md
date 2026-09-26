# Custos PostgreSQL Compatibility Validation

Release: **Custos v0.98 · Scarabs**

## Changes validated

- Dual database mode: SQLite locally, PostgreSQL when `DATABASE_URL` is set.
- PostgreSQL driver dependency added (`psycopg2-binary`).
- SQLite `?` parameter markers are translated to PostgreSQL `%s` only inside the PostgreSQL compatibility wrapper.
- SQLite-only `INSERT OR IGNORE` replaced with portable `ON CONFLICT ... DO NOTHING`.
- New session IDs use `INSERT ... RETURNING id`, supported by PostgreSQL and modern SQLite.
- PostgreSQL schema replaces SQLite `AUTOINCREMENT` with `SERIAL`.
- Schema migration checks use `information_schema.columns` on PostgreSQL and `PRAGMA table_info` on SQLite.
- PostgreSQL initialization is protected with an advisory lock for multi-worker startup.
- `/health` checks both the web application and active database connection.
- `render.yaml` wires `DATABASE_URL` to a managed Render PostgreSQL database.

## Local fallback test

The revised database layer was initialized against a clean SQLite database using the compatibility code path:

- 17 assessment/dry-run batch records created
- 1 administrator record created
- 5 Midterm bonus placeholders created
- `INSERT ... RETURNING id` verified with SQLite fallback

## Static validation

- `app.py`, `db.py`, `item_analysis.py`, and `init_db.py` compile successfully.
- No private question-bank CSV, answer-key CSV, populated SQLite database, or generated test-set source is required by the deployment build.

## Production caution

A real PostgreSQL server was not available inside the packaging runtime, so the final network connection must be verified after Render provisions `custos-db`. The `/health` endpoint is included specifically for this deployment check.

## PWA / Mobile Exam Mode Validation

- Added `manifest.webmanifest` with standalone/fullscreen display fallback.
- Added 180 px Apple touch icon, 192/512 PWA icons, and 512 px maskable icon.
- Added root-scoped service worker route and static-only service-worker cache policy.
- Dynamic exam/API/admin/login pages are explicitly excluded from service-worker caching.
- Added iOS/iPadOS standalone detection via `navigator.standalone` and display-mode media query.
- Added Android/Chromium installed-app detection via display-mode media query.
- Installed-app mode is accepted as secure display mode while existing visibility/focus security monitoring remains enabled.
- Added mobile installed-app exam layout with off-canvas question navigator.
- Desktop browser exam/fullscreen behavior remains unchanged.
- Python source compilation: PASS.
- JavaScript syntax (`pwa.js`, `exam.js`, `sw.js`): PASS.
- PWA manifest JSON parse: PASS.
- 17 Jinja templates parse: PASS.
- Live Flask route smoke test was not run in the packaging environment because Flask is not installed there.

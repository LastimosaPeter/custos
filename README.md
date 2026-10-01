# Custos 1.6.0.h — Hercules

**Custos** is a PostgreSQL-ready multi-subject assessment platform designed around **Instructors → Subjects → Assessments → Attempts**. This build supports both **CSDC101 · Fundamentals of Programming** and **CSEC303 · Digital Image Processing**, while preserving the existing Workspace, Google Classroom integration, objective-exam workflow, and future programming-lab foundation.

## Instructor information architecture

The instructor header now uses one consistent hierarchy across Custos:

- **Workspace** — the primary management surface for subjects, assessments, instructors, and their settings.
- **Assessment** — a grouped menu containing Dashboard, Live Monitor, Item Analysis, Question Banks, and Testing.
- **Messages** — a central inbox for student exam chat with AJAX replies (no full-page refresh).
- **IDE** — instructor-only programming-lab configuration and preview while the feature is under development.

After instructor sign-in, Custos opens **Workspace** first.

## Student IDE release gate

The IDE code is included in the project, but public student access is **disabled by default**:

```env
STUDENT_IDE_ENABLED=0
```

The public Home navigation shows **IDE** as greyed/Coming Soon. Clicking it opens the Caution / Men at Work page. Direct public visits to `/ide` are also redirected there.

Instructor IDE management and instructor preview remain available. When the feature is ready for students, set `STUDENT_IDE_ENABLED=1` and configure an isolated production code runner before deployment.

## C++ execution

Production defaults to:

```env
CODE_RUNNER_BACKEND=disabled
```

For local development only, with `g++` installed:

```env
CODE_RUNNER_BACKEND=local
CODE_RUNNER_ALLOW_LOCAL=1
CXX=g++
```

For production, use an isolated Judge0-compatible service:

```env
CODE_RUNNER_BACKEND=judge0
JUDGE0_URL=https://your-isolated-runner.example.com
JUDGE0_CPP_LANGUAGE_ID=54
```

Do not enable direct local execution on a public Flask/Render service.

## Database

Custos uses PostgreSQL whenever `DATABASE_URL` is configured, and SQLite when it is blank. Database migrations are additive and preserve existing attempts; the portable build skips the full migration path on ordinary restarts once the current schema marker is present.

Student identity now stores separate `first_name` and `last_name` fields while retaining `student_name` for backwards compatibility with old attempts. Existing records are best-effort backfilled during migration.

Live Monitor also stores a non-destructive `monitor_done` state. **Mark Done** removes an attempt from Live Monitor without changing its answers, score, or submission state. If that student resumes the attempt, Custos automatically returns the attempt to Live Monitor.

## PWA / responsive behavior

- iOS/iPadOS and Android installed-app support
- white-background Custos PWA icons
- safe-area handling for camera/status bar and Home indicator
- iPad landscape stays close to the desktop layout
- installed-app status is shown as a green status box
- desktop fullscreen and installed-PWA secure exam modes remain supported

## Student identity

Student assessment sign-in now asks for:

- First Name
- Last Name
- Program
- Section
- ADNU email
- Session key

Live monitoring displays new identities as **Last Name, First Name** for quick scanning, with older attempts falling back to their saved full name.

## Local setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Set `SECRET_KEY` and `ADMIN_PASSWORD` in `.env`, then:

```powershell
python init_db.py
python app.py
```

## PostgreSQL / Render

`render.yaml` configures the web service and PostgreSQL connection. The included deployment configuration keeps:

```env
STUDENT_IDE_ENABLED=0
CODE_RUNNER_BACKEND=disabled
```

until you intentionally enable the student programming environment.

## GitHub safety

Never commit `.env`, databases, or private question banks. `.gitignore` excludes those files. The GitHub-ready package supplied with this revision does **not** contain the private question-bank CSVs.

## Current release

Custos v1.6.0.h · **Hercules** · *Dynastes hercules*

## September 27 layout refinement

The mobile/PWA header now renders the product and subject in one horizontal lockup (`Custos mark + Custos | subject logo`). Regular pages include a subtle footer fade behind the persistent course/institution marks, and the Home breadcrumb is centered to the same width as the Home content cards. PWA cache version was bumped so installed devices receive the update.

## Free-form Custom Assessments

Instructor → **Assessment → Dashboard** now shows every assessment across all subjects and includes a blank custom-test builder. New objective assessments no longer inherit the legacy 40-item Part I + 20-item Part II structure.

A custom assessment can define its own:

- title and free-text label (Quiz, Practice Test, Examination, etc.)
- duration and start/close window
- allowed sections (ZT11, ZT12, ZT13, ZS11)
- one shared student session key
- any number of multiple-choice questions
- per-question point values
- question and answer-choice shuffling
- optional question-pool limit
- score reveal behavior
- standard / strict / practice security label

Questions may be created manually or imported from CSV. Required CSV columns are:

```text
prompt, option_a, option_b, option_c, option_d, correct_option
```

Optional columns:

```text
item_number, topic, code, explanation, points
```

A sample orientation bank is included at `samples/custos_orientation_practice_test_10_items.csv`, and a blank browser-downloadable template is available at `static/samples/custom_assessment_template.csv`.

The legacy CSDC101 Midterm and Post-test dashboards continue to work unchanged and remain available from the unified Assessments dashboard.

## Unified assessment administration update

This build treats objective assessments as first-class assessment records across Dashboard, Question Banks, Item Analysis, Live Monitor, and Messages. Midterm/Post-test retain their existing specialized delivery rules but are surfaced alongside custom quizzes/practice tests instead of being isolated from the newer assessment model.

Additional instructor controls in this update:

- soft-delete assessments from Dashboard/Workspace while preserving historical attempts and analytics
- unified assessment picker in Question Banks and Item Analysis
- custom assessment item analysis using the same distractor/discrimination engine
- Caudex Programming Lab task analytics inside Item Analysis
- assessment filter in Live Monitor
- full-card attention borders in Live Monitor
- hard-delete stored chat messages for a student conversation without deleting the exam attempt
- compact/bold field labels in the Custom Test creator

Deleted assessments are hidden from active administration and their delivery batches are disabled. Existing submissions, answer data, proctor events, and scores remain available in the database for audit/history.

## Unified assessment administration

Custos now treats Midterm, Post-test, Dry Run, custom objective tests, and Caudex Programming Labs as assessment records visible from the same Dashboard. Question Banks, Item Analysis, Testing, and Live Monitor are assessment-aware rather than being limited to the original Midterm/Post-test pair.

Deleting an assessment from Dashboard or Workspace soft-deletes it: delivery is disabled and the assessment disappears from active administration, but historical attempts and analytics remain in PostgreSQL. Student-message conversations can be hard-deleted independently to reclaim message storage without deleting exam attempts, answers, or proctoring logs.

## Portable / performance build

This Hercules package is optimized to run from the same source tree on a classroom Windows/Linux laptop, Render, a generic Gunicorn/WSGI host, Docker, or a serverless Flask host backed by PostgreSQL.

Performance changes in this build:

- the 1920×1080 page background was reduced from roughly 2.7 MB PNG to a roughly 36 KB WebP asset
- static CSS/JS/images now use long-lived release caching instead of `no-store`
- the service worker uses cache-first delivery for release-versioned static assets instead of re-fetching cached files in the background
- the theme preference no longer requires a PostgreSQL query on every rendered page
- PostgreSQL uses a small connection pool on long-running servers; serverless/Vercel deployments default to no app-side pool unless explicitly enabled
- schema migration/seed work runs only for a new/upgraded database instead of on every process/cold start
- frequently used monitor/chat/session query paths have additional indexes
- student chat polling backs off when the chat is closed and pauses while the page is hidden
- instructor Messages and Live Monitor polling also backs off while their page is hidden
- JetBrains Mono is requested only on the Caudex IDE instead of every Custos page
- local `python app.py` uses Waitress by default, binds to `0.0.0.0`, and honors `PORT`, making the same build suitable for a classroom LAN server

For a local/LAN deployment, leave `DATABASE_URL` blank to use SQLite, set `SESSION_COOKIE_SECURE=0`, and run `python app.py` after configuring `.env`. Other devices on the same LAN can access the machine by its LAN IP and configured `PORT` if the operating-system firewall permits it.

For Render or another long-running PostgreSQL host, use `DATABASE_URL` and keep `DB_POOL_ENABLED=1`. `DB_POOL_MAX=8` is a reasonable starting point for the included one-worker/eight-thread Gunicorn configuration.

For Vercel/serverless deployment, use a real PostgreSQL `DATABASE_URL`; do not rely on local `exam.db` because serverless filesystems are not a persistent shared database. App-side PostgreSQL pooling defaults off when the `VERCEL` environment variable is present. If your database provider offers a pooled/serverless connection string, prefer that connection string.

`AUTO_INIT_DB=1` keeps new deployments self-initializing. A full migration is performed only when the schema marker changes. To deliberately rerun the migration/seed path once, set `FORCE_DB_INIT=1` for a deployment or run `python init_db.py`, then return `FORCE_DB_INIT` to `0`.


## Hercules browser Python workbench

CSEC303 PHANTOM-303 can run its editable notebook cells directly inside the exam toolkit using Pyodide. The runtime is lazy-loaded from the official jsDelivr Pyodide distribution on first use, so the first Python run is intentionally heavier than ordinary Custos pages.

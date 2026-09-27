# Custos Next

**Custos** is a PostgreSQL-ready secure assessment platform designed around **Instructors → Subjects → Assessments → Attempts**. The current CSDC101 objective-exam workflow remains supported while the Workspace provides the foundation for additional subjects, assessment types, instructors, and a future secure C++ Programming Lab.

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

Custos uses PostgreSQL whenever `DATABASE_URL` is configured, and SQLite when it is blank. Startup migrations are additive and preserve existing attempts.

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

Custos v0.98 · **Scarabs**

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

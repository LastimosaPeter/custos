# CSEC303 Integration — Custos 1.6.0.h Hercules r24

> **r24 update:** The application now uses the general Custos + CSDC101 + CSEC303 header outside course contexts, course-specific shells inside each assessment, Google-first student sign-in, a reusable database-backed Jupyter Workbench, Python syntax highlighting/completion, and the public CSEC303 Workbench Dry Run sample.

This build adds **CSEC303 · Digital Image Processing** beside CSDC101 while preserving the existing Google Classroom/instructor workflow in `custos-main`.

## Student access flow

Students sign in first, then land on **My Assessments**. Google Classroom assignments and saved attempts appear there automatically. An instructor-issued session key can be entered from My Assessments when needed; the sign-in page itself does not ask for a key. Custos still verifies that the key belongs to the selected subject.

## CSEC303 Laboratory Midterm

The database migration creates the CSEC303 subject and the assessment shell for:

- Assessment: `Case File PHANTOM-303 | Laboratory Midterm Examination`
- Duration: 3 days by default for the take-home build; a configured close time remains the hard deadline
- Security mode: `standard` / open-tool
- Score reveal: off by default
- Intended private bank: 20 items × 3 points = 60 points
- Student case kit: `/static/workbenches/csec303-midterm-laboratory-case-files/CSEC303_Midterm_Case_Kit.zip`

The session key is generated rather than hard-coded. View or regenerate it from the instructor assessment settings.

### Protecting the answer key on a public GitHub repository

The actual PHANTOM-303 question bank, correct answers, instructor metrics, and case-kit generator are stored under:

`private_banks/csec303_midterm/`

That directory is already ignored by `.gitignore`. Therefore `git add -A` will **not** publish the exam key/answers to GitHub.

For a local SQLite build, the private bank is present in this ZIP and is seeded automatically during database initialization.

For a production PostgreSQL database deployed from public GitHub/Vercel, seed the private bank from your own computer before releasing the assessment to students:

```bash
# Put the production DATABASE_URL in your local .env (do not commit .env), then:
python seed_csec303_midterm.py
```

The script prints the question count and current generated session key. Confirm that the Question Bank shows 20 items before opening the assessment.

## CSDC101 exam tools

CSDC101 assessment sessions now expose a persistent **Tools** modal containing:

- basic arithmetic calculator;
- persistent Scratch Notes; and
- a persistent Jam Board / working canvas.

Notes and board strokes are stored per exam attempt in PostgreSQL/SQLite and restored after refresh. These tools are available only for CSDC101 assessment sessions.

## Score exports

The assessment dashboard and assessment builder expose both:

- `.xlsx` — one worksheet per delivery/set where applicable; and
- `.csv` — a portable flat export with a `Set / Delivery` column.

Instructor testing sessions are excluded from real-student score exports.

## Branding

General pages use `Custos | CSDC101 logo + CSEC303 logo` and the neutral Custos background. Course-specific student and instructor pages switch to that course's logo, background, and light/dark watermark. The general Hercules beetle footer mark is suppressed inside a course context.

## Hercules r24 · generic Jupyter Workbench

- Release: **Custos v1.6.0.h · Hercules · _Dynastes hercules_**.
- Python notebook cells use CodeMirror syntax highlighting, line numbers, adjustable font sizing, and lightweight completion suggestions.
- Any custom assessment can accept a `.ipynb` or a ZIP containing one notebook plus supporting files.
- Uploaded notebooks/assets are stored in SQLite/PostgreSQL, which keeps the workflow compatible with local use, Render, and Vercel.
- PHANTOM-303 also ships a GitHub-safe static workbench package, while the private question bank remains ignored by Git.
- A public six-item CSEC303 Workbench Dry Run is included under `samples/csec303_workbench_dry_run/`.

## Canary r21 · Student Classroom & multi-day continuity

- Signed-in students have **My Assessments** at `/student`.
- Google Classroom-rostered assessments are listed automatically alongside previously started attempts.
- Student identity cookies are persistent for 7 days, while answers, current question position, notes, and attempt state remain server-side in the database.
- PHANTOM-303 defaults to a 3-day (4320-minute) attempt. A configured delivery close time is always the hard deadline.
- Instructors can independently enable **Reveal score** and **Reveal answers**. Answer review shows the student's submitted option, the correct answer, and the item explanation after submission.

## Canary r22 · navigation and assessment UX cleanup

- Home copy now presents Custos as one portal for CSDC101 and CSEC303 without course-branding language.
- Student and Instructor modes are visibly distinguished in the header.
- Instructor pages use the general `Custos | CSDC101 + CSEC303` header treatment.
- Student navigation follows `Home > Sign In > My Assessments` and exposes My Assessments in the main nav while signed in.
- Course watermarks are limited to course-specific student screens rather than general/instructor views.
- Session keys are visible text fields while being entered.
- Assessment Integrity Notice uses a full perimeter accent border.
- CSDC101 Calculator / Notes / Jam Board open as a persistent modal overlay rather than a side drawer.
- Exam code snippets have persistent A-/A+ font sizing controls.
- Result-page response review language is product-neutral and result actions have clearer spacing.

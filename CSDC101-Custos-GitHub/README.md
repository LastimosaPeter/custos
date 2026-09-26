# Custos v0.98 · Scarabs

**The Official Assessment Portal of CSDC101**

This is the **GitHub-safe deployment build** of Custos. It contains the Flask application, templates, static assets, security controls, instructor tools, question-bank editor/importer, live monitor, and deployment files.

## Important: no exam questions are included

This repository intentionally contains **no Midterm/Post-test question CSVs, answer keys, generated question source, populated SQLite database, or private test-set bundles**.

The public source initializes with empty Part I/Part II banks. After deployment:

1. Sign in to **Instructor View**.
2. Open **Question Banks**.
3. Use **Load Private Question Bank**.
4. Upload the private CSV from your secure local copy of Custos.
5. Configure the five Midterm bonus questions in the same page.
6. Regenerate session keys and configure assessment windows before opening an exam.

The uploaded CSV is parsed in memory and inserted into the database; Custos does not save the uploaded CSV file into the repository or application folder.

Expected private CSV columns:

```text
part,batch_slot,topic,prompt,code,option_a,option_b,option_c,option_d,correct_option,explanation
```

Each imported bank must contain at least **40 active Part I** and **20 active Part II** items.

## Local setup

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

macOS/Linux:

```bash
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Before starting, edit `.env` and replace both placeholder values for `SECRET_KEY` and `ADMIN_PASSWORD`.

Then:

```bash
python init_db.py
python app.py
```

## GitHub deployment

GitHub stores the source code; a Flask application still needs a Python web host such as Render, Railway, Fly.io, a VPS, or another WSGI-compatible service.

For a production host, set these environment variables in the host dashboard rather than committing a `.env` file:

```text
SECRET_KEY=<long random secret>
ADMIN_USERNAME=<instructor username>
ADMIN_PASSWORD=<strong private password>
ALLOWED_EMAIL_DOMAIN=adnu.edu.ph
APP_TIMEZONE=Asia/Manila
SESSION_COOKIE_SECURE=1
EXAM_DB_PATH=<persistent database path if using SQLite>
```

A generic WSGI start command is:

```bash
gunicorn app:app
```

If the host uses ephemeral storage, do **not** keep live exam records in an ephemeral SQLite file. Attach persistent storage or migrate the database to a persistent database service before live use.

## Repository hygiene

`.gitignore` excludes:

- `.env`
- SQLite databases
- Python caches
- private bank directories
- question-bank CSV exports
- answer-key CSVs
- test-set bundles
- generated question-bank source

Do not override those exclusions for a public repository.

## Private workflow

Keep your existing full local Custos package somewhere private. That private copy contains the assessment bank you authored. The GitHub build is only the deployable application shell. Upload the bank through the Instructor interface after the deployed database is ready.

## Security note

Custos logs browser/exam events and implements server-backed temporary/permanent attempt locks, but normal web browsers cannot physically disable a monitor or guarantee interception of every operating-system action. Veyon remains the instructor-side workstation monitoring layer.

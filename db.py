import os
import json
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv
from werkzeug.security import generate_password_hash

load_dotenv()
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
_db_setting = os.environ.get("EXAM_DB_PATH", "exam.db")
DB_PATH = _db_setting if os.path.isabs(_db_setting) else os.path.join(BASE_DIR, _db_setting)
DATABASE_ENGINE = "postgresql" if DATABASE_URL else "sqlite"

_tz_name = os.environ.get("APP_TIMEZONE", "Asia/Manila")
try:
    APP_TZ = ZoneInfo(_tz_name)
except ZoneInfoNotFoundError:
    if _tz_name == "Asia/Manila":
        APP_TZ = timezone(timedelta(hours=8), name="PHT")
    else:
        APP_TZ = timezone.utc

SESSION_KEY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
QUESTION_BANK_VERSION = "private-import"
DB_SCHEMA_VERSION = "1.0-goliathus-portable-r2-google"

# PostgreSQL connections are expensive when the database is on another host.
# Keep a small per-process pool so repeated API polls and answer saves can reuse
# already-open TLS/database connections. Disable with DB_POOL_ENABLED=0.
_default_pool_enabled = "0" if os.environ.get("VERCEL") else "1"
DB_POOL_ENABLED = os.environ.get("DB_POOL_ENABLED", _default_pool_enabled) == "1"
DB_POOL_MIN = max(1, int(os.environ.get("DB_POOL_MIN", "1") or 1))
DB_POOL_MAX = max(DB_POOL_MIN, int(os.environ.get("DB_POOL_MAX", "8") or 8))
_pg_pool = None
_pg_pool_lock = threading.Lock()
DEFAULT_BONUS_QUESTIONS = [
    (1, "Configure Before Use", "Configure Bonus Question 1 in Instructor → Question Banks.", "CHANGE_ME_1"),
    (2, "Configure Before Use", "Configure Bonus Question 2 in Instructor → Question Banks.", "CHANGE_ME_2"),
    (3, "Configure Before Use", "Configure Bonus Question 3 in Instructor → Question Banks.", "CHANGE_ME_3"),
    (4, "Configure Before Use", "Configure Bonus Question 4 in Instructor → Question Banks.", "CHANGE_ME_4"),
    (5, "Configure Before Use", "Configure Bonus Question 5 in Instructor → Question Banks.", "CHANGE_ME_5"),
]


def generate_session_key(assessment_type, section, batch_label):
    prefix = "PT" if assessment_type == "posttest" else "MT"
    section_no = "".join(ch for ch in str(section) if ch.isdigit()) or str(section)
    secret = "".join(secrets.choice(SESSION_KEY_ALPHABET) for _ in range(8))
    return f"{prefix}-{section_no}{batch_label.upper()}-{secret[:4]}-{secret[4:]}"


def unique_session_key(conn, assessment_type, section, batch_label):
    for _ in range(20):
        key = generate_session_key(assessment_type, section, batch_label)
        if not conn.execute("SELECT 1 FROM batches WHERE access_code=?", (key,)).fetchone():
            return key
    raise RuntimeError("Could not generate a unique session key")


SQLITE_SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS app_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS admins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slot INTEGER NOT NULL UNIQUE,
    section TEXT NOT NULL,
    batch_label TEXT NOT NULL,
    name TEXT NOT NULL,
    access_code TEXT NOT NULL UNIQUE,
    open_at TEXT,
    close_at TEXT,
    duration_minutes INTEGER NOT NULL DEFAULT 90,
    reveal_score INTEGER NOT NULL DEFAULT 1,
    active INTEGER NOT NULL DEFAULT 1,
    assessment_type TEXT NOT NULL DEFAULT 'midterm'
);

CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    part INTEGER NOT NULL CHECK(part IN (1,2)),
    batch_slot INTEGER NOT NULL,
    topic TEXT NOT NULL,
    prompt TEXT NOT NULL,
    code TEXT NOT NULL DEFAULT '',
    option_a TEXT NOT NULL,
    option_b TEXT NOT NULL,
    option_c TEXT NOT NULL,
    option_d TEXT NOT NULL,
    correct_option TEXT NOT NULL CHECK(correct_option IN ('A','B','C','D')),
    explanation TEXT NOT NULL DEFAULT '',
    points INTEGER NOT NULL DEFAULT 1,
    position INTEGER,
    active INTEGER NOT NULL DEFAULT 1,
    created_by TEXT NOT NULL DEFAULT 'builtin'
);

CREATE TABLE IF NOT EXISTS exam_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL,
    first_name TEXT,
    last_name TEXT,
    student_name TEXT,
    program TEXT,
    class_section TEXT,
    batch_id INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    submitted_at TEXT,
    status TEXT NOT NULL DEFAULT 'in_progress',
    part1_correct INTEGER NOT NULL DEFAULT 0,
    part1_score INTEGER NOT NULL DEFAULT 0,
    part2_correct INTEGER NOT NULL DEFAULT 0,
    part2_score INTEGER NOT NULL DEFAULT 0,
    bonus_correct INTEGER NOT NULL DEFAULT 0,
    bonus_score INTEGER NOT NULL DEFAULT 0,
    auto_total INTEGER NOT NULL DEFAULT 0,
    admin_part1_score REAL,
    admin_part2_score REAL,
    admin_bonus_score REAL,
    admin_total REAL,
    admin_note TEXT,
    flagged_count INTEGER NOT NULL DEFAULT 0,
    ip_address TEXT,
    user_agent TEXT,
    is_test INTEGER NOT NULL DEFAULT 0,
    test_label TEXT,
    untimed INTEGER NOT NULL DEFAULT 0,
    terms_accepted_at TEXT,
    violation_count INTEGER NOT NULL DEFAULT 0,
    security_locked INTEGER NOT NULL DEFAULT 0,
    temp_locked_until TEXT,
    pending_blackout INTEGER NOT NULL DEFAULT 0,
    monitor_done INTEGER NOT NULL DEFAULT 0,
    last_question_index INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(batch_id) REFERENCES batches(id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_one_session_per_email_batch
ON exam_sessions(email, batch_id);

CREATE TABLE IF NOT EXISTS session_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    question_id INTEGER NOT NULL,
    q_order INTEGER NOT NULL,
    option_order TEXT NOT NULL,
    selected_option TEXT,
    marked_for_review INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(session_id) REFERENCES exam_sessions(id) ON DELETE CASCADE,
    FOREIGN KEY(question_id) REFERENCES questions(id)
);

CREATE TABLE IF NOT EXISTS bonus_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    assessment_type TEXT NOT NULL DEFAULT 'midterm',
    position INTEGER NOT NULL,
    topic TEXT NOT NULL DEFAULT 'General Knowledge',
    prompt TEXT NOT NULL,
    accepted_answer TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    UNIQUE(assessment_type, position)
);

CREATE TABLE IF NOT EXISTS session_bonus_answers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    bonus_question_id INTEGER NOT NULL,
    q_order INTEGER NOT NULL,
    answer_text TEXT NOT NULL DEFAULT '',
    FOREIGN KEY(session_id) REFERENCES exam_sessions(id) ON DELETE CASCADE,
    FOREIGN KEY(bonus_question_id) REFERENCES bonus_questions(id),
    UNIQUE(session_id, bonus_question_id)
);

CREATE TABLE IF NOT EXISTS proctor_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    detail TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(session_id) REFERENCES exam_sessions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS exam_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    sender TEXT NOT NULL CHECK(sender IN ('student','instructor')),
    message TEXT NOT NULL,
    created_at TEXT NOT NULL,
    read_at TEXT,
    FOREIGN KEY(session_id) REFERENCES exam_sessions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_exam_messages_session ON exam_messages(session_id, id);

CREATE TABLE IF NOT EXISTS ui_preferences (
    preference_key TEXT PRIMARY KEY,
    theme TEXT NOT NULL CHECK(theme IN ('light','dark')),
    updated_at TEXT NOT NULL
);
"""


FUTURE_SCHEMA = """
CREATE TABLE IF NOT EXISTS subjects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    term TEXT NOT NULL DEFAULT '',
    school_year TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    UNIQUE(code, term, school_year)
);

CREATE TABLE IF NOT EXISTS instructors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_id INTEGER UNIQUE,
    display_name TEXT NOT NULL,
    email TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    FOREIGN KEY(admin_id) REFERENCES admins(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS subject_instructors (
    subject_id INTEGER NOT NULL,
    instructor_id INTEGER NOT NULL,
    role TEXT NOT NULL DEFAULT 'instructor',
    PRIMARY KEY(subject_id, instructor_id),
    FOREIGN KEY(subject_id) REFERENCES subjects(id) ON DELETE CASCADE,
    FOREIGN KEY(instructor_id) REFERENCES instructors(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS assessments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    assessment_type TEXT NOT NULL DEFAULT 'quiz',
    display_type TEXT NOT NULL DEFAULT 'Assessment',
    description TEXT NOT NULL DEFAULT '',
    duration_minutes INTEGER NOT NULL DEFAULT 60,
    start_at TEXT,
    end_at TEXT,
    access_code TEXT UNIQUE,
    max_attempts INTEGER NOT NULL DEFAULT 1,
    security_mode TEXT NOT NULL DEFAULT 'standard',
    reveal_score INTEGER NOT NULL DEFAULT 1,
    shuffle_questions INTEGER NOT NULL DEFAULT 1,
    shuffle_options INTEGER NOT NULL DEFAULT 1,
    allowed_sections TEXT NOT NULL DEFAULT '',
    question_limit INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    deleted_at TEXT,
    created_by_instructor_id INTEGER,
    created_at TEXT NOT NULL,
    FOREIGN KEY(subject_id) REFERENCES subjects(id) ON DELETE CASCADE,
    FOREIGN KEY(created_by_instructor_id) REFERENCES instructors(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS programming_labs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    assessment_id INTEGER NOT NULL UNIQUE,
    language TEXT NOT NULL DEFAULT 'cpp',
    title TEXT NOT NULL,
    instructions TEXT NOT NULL DEFAULT '',
    starter_code TEXT NOT NULL DEFAULT '',
    allow_custom_input INTEGER NOT NULL DEFAULT 1,
    runner_backend TEXT NOT NULL DEFAULT 'inherit',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    FOREIGN KEY(assessment_id) REFERENCES assessments(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS programming_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lab_id INTEGER NOT NULL,
    position INTEGER NOT NULL,
    title TEXT NOT NULL,
    prompt TEXT NOT NULL,
    starter_code TEXT NOT NULL DEFAULT '',
    points REAL NOT NULL DEFAULT 10,
    hidden_tests_json TEXT NOT NULL DEFAULT '[]',
    active INTEGER NOT NULL DEFAULT 1,
    UNIQUE(lab_id, position),
    FOREIGN KEY(lab_id) REFERENCES programming_labs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS coding_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lab_id INTEGER NOT NULL,
    email TEXT NOT NULL,
    first_name TEXT,
    last_name TEXT,
    student_name TEXT NOT NULL,
    program TEXT,
    class_section TEXT,
    started_at TEXT NOT NULL,
    submitted_at TEXT,
    status TEXT NOT NULL DEFAULT 'in_progress',
    current_task_id INTEGER,
    terms_accepted_at TEXT,
    violation_count INTEGER NOT NULL DEFAULT 0,
    security_locked INTEGER NOT NULL DEFAULT 0,
    temp_locked_until TEXT,
    pending_blackout INTEGER NOT NULL DEFAULT 0,
    flagged_count INTEGER NOT NULL DEFAULT 0,
    ip_address TEXT,
    user_agent TEXT,
    is_test INTEGER NOT NULL DEFAULT 0,
    total_score REAL NOT NULL DEFAULT 0,
    UNIQUE(email, lab_id),
    FOREIGN KEY(lab_id) REFERENCES programming_labs(id) ON DELETE CASCADE,
    FOREIGN KEY(current_task_id) REFERENCES programming_tasks(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS coding_task_progress (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    task_id INTEGER NOT NULL,
    source_code TEXT NOT NULL DEFAULT '',
    stdin_text TEXT NOT NULL DEFAULT '',
    last_output TEXT NOT NULL DEFAULT '',
    last_status TEXT NOT NULL DEFAULT 'not_run',
    run_count INTEGER NOT NULL DEFAULT 0,
    score REAL NOT NULL DEFAULT 0,
    submitted_at TEXT,
    last_saved_at TEXT,
    UNIQUE(session_id, task_id),
    FOREIGN KEY(session_id) REFERENCES coding_sessions(id) ON DELETE CASCADE,
    FOREIGN KEY(task_id) REFERENCES programming_tasks(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS coding_submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    task_id INTEGER NOT NULL,
    source_code TEXT NOT NULL,
    stdin_text TEXT NOT NULL DEFAULT '',
    stdout_text TEXT NOT NULL DEFAULT '',
    stderr_text TEXT NOT NULL DEFAULT '',
    compile_output TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    runtime_ms INTEGER,
    passed_count INTEGER NOT NULL DEFAULT 0,
    total_tests INTEGER NOT NULL DEFAULT 0,
    score REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY(session_id) REFERENCES coding_sessions(id) ON DELETE CASCADE,
    FOREIGN KEY(task_id) REFERENCES programming_tasks(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS coding_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    detail TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(session_id) REFERENCES coding_sessions(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_coding_events_session ON coding_events(session_id, id);

CREATE TABLE IF NOT EXISTS classroom_rosters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    assessment_id INTEGER NOT NULL,
    course_id TEXT NOT NULL,
    course_name TEXT NOT NULL DEFAULT '',
    course_section TEXT NOT NULL DEFAULT '',
    program TEXT NOT NULL,
    class_section TEXT NOT NULL,
    imported_by_admin_id INTEGER,
    imported_at TEXT NOT NULL,
    student_count INTEGER NOT NULL DEFAULT 0,
    UNIQUE(assessment_id, course_id),
    FOREIGN KEY(assessment_id) REFERENCES assessments(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS classroom_roster_students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    roster_id INTEGER NOT NULL,
    email TEXT NOT NULL,
    first_name TEXT NOT NULL DEFAULT '',
    last_name TEXT NOT NULL DEFAULT '',
    google_user_id TEXT NOT NULL DEFAULT '',
    UNIQUE(roster_id, email),
    FOREIGN KEY(roster_id) REFERENCES classroom_rosters(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_classroom_roster_students_email ON classroom_roster_students(email);
"""

# PostgreSQL uses SERIAL for auto-incrementing integer primary keys.
POSTGRES_SCHEMA = (
    (SQLITE_SCHEMA + FUTURE_SCHEMA).replace("PRAGMA foreign_keys = ON;", "")
    .replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
)


def _pg_sql(sql):
    """Translate the SQLite-style parameter marker used by Custos to psycopg2."""
    return sql.replace("?", "%s")


class PostgresConnection:
    """Compatibility wrapper with optional pooled connection return on close()."""

    def __init__(self, raw_connection, dict_cursor_factory, pool=None):
        self._conn = raw_connection
        self._dict_cursor_factory = dict_cursor_factory
        self._pool = pool

    def execute(self, sql, params=()):
        cur = self._conn.cursor(cursor_factory=self._dict_cursor_factory)
        cur.execute(_pg_sql(sql), tuple(params or ()))
        return cur

    def executemany(self, sql, seq_of_params):
        cur = self._conn.cursor(cursor_factory=self._dict_cursor_factory)
        cur.executemany(_pg_sql(sql), seq_of_params)
        return cur

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        raw = self._conn
        if raw is None:
            return
        self._conn = None
        # SELECTs also open transactions in psycopg2. Clear any transaction before
        # returning a connection to the pool so the next request receives a clean one.
        try:
            if not raw.closed:
                raw.rollback()
        except Exception:
            pass
        if self._pool is not None:
            try:
                self._pool.putconn(raw, close=bool(raw.closed))
                return
            except Exception:
                pass
        try:
            raw.close()
        except Exception:
            pass


def _postgres_url():
    url = DATABASE_URL
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url


def _get_postgres_pool():
    global _pg_pool
    if not DB_POOL_ENABLED:
        return None
    if _pg_pool is not None:
        return _pg_pool
    with _pg_pool_lock:
        if _pg_pool is None:
            try:
                from psycopg2.pool import ThreadedConnectionPool
            except ImportError as exc:
                raise RuntimeError(
                    "DATABASE_URL is set but psycopg2 is not installed. Run: pip install -r requirements.txt"
                ) from exc
            _pg_pool = ThreadedConnectionPool(
                DB_POOL_MIN,
                DB_POOL_MAX,
                dsn=_postgres_url(),
                connect_timeout=10,
                application_name="Custos",
            )
    return _pg_pool


def connect():
    """Connect to PostgreSQL when DATABASE_URL is set; otherwise use local SQLite."""
    if DATABASE_URL:
        try:
            import psycopg2
            from psycopg2.extras import DictCursor
        except ImportError as exc:
            raise RuntimeError(
                "DATABASE_URL is set but psycopg2 is not installed. Run: pip install -r requirements.txt"
            ) from exc
        pool = _get_postgres_pool()
        raw = pool.getconn() if pool is not None else psycopg2.connect(
            _postgres_url(), connect_timeout=10, application_name="Custos"
        )
        return PostgresConnection(raw, DictCursor, pool=pool)

    # WAL + a modest busy timeout makes the local SQLite mode much friendlier to
    # concurrent classroom traffic while retaining zero-configuration portability.
    conn = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
    except sqlite3.DatabaseError:
        pass
    return conn


def _table_names(conn):
    if DATABASE_ENGINE == "postgresql":
        rows = conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema()"
        ).fetchall()
        return {row[0] for row in rows}
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {row[0] for row in rows}


def _table_columns(conn, table_name):
    if DATABASE_ENGINE == "postgresql":
        rows = conn.execute(
            """SELECT column_name FROM information_schema.columns
               WHERE table_schema=current_schema() AND table_name=?""",
            (table_name,),
        ).fetchall()
        return {row[0] for row in rows}
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}


def _apply_schema(conn):
    if DATABASE_ENGINE == "sqlite":
        conn.executescript(SQLITE_SCHEMA + FUTURE_SCHEMA)
        return
    for statement in POSTGRES_SCHEMA.split(";"):
        statement = statement.strip()
        if statement:
            conn.execute(statement)
    conn.commit()


def migrate_schema(conn):
    admin_cols = _table_columns(conn, "admins")
    for name, definition in {
        "display_name": "TEXT",
        "email": "TEXT",
        "role": "TEXT NOT NULL DEFAULT 'owner'",
        "active": "INTEGER NOT NULL DEFAULT 1",
    }.items():
        if name not in admin_cols:
            conn.execute(f"ALTER TABLE admins ADD COLUMN {name} {definition}")

    session_question_cols = _table_columns(conn, "session_questions") if "session_questions" in _table_names(conn) else set()
    if session_question_cols and "marked_for_review" not in session_question_cols:
        conn.execute("ALTER TABLE session_questions ADD COLUMN marked_for_review INTEGER NOT NULL DEFAULT 0")

    session_cols = _table_columns(conn, "exam_sessions")
    session_additions = {
        "is_test": "INTEGER NOT NULL DEFAULT 0",
        "test_label": "TEXT",
        "untimed": "INTEGER NOT NULL DEFAULT 0",
        "first_name": "TEXT",
        "last_name": "TEXT",
        "student_name": "TEXT",
        "program": "TEXT",
        "class_section": "TEXT",
        "terms_accepted_at": "TEXT",
        "violation_count": "INTEGER NOT NULL DEFAULT 0",
        "security_locked": "INTEGER NOT NULL DEFAULT 0",
        "temp_locked_until": "TEXT",
        "pending_blackout": "INTEGER NOT NULL DEFAULT 0",
        "monitor_done": "INTEGER NOT NULL DEFAULT 0",
        "bonus_correct": "INTEGER NOT NULL DEFAULT 0",
        "bonus_score": "INTEGER NOT NULL DEFAULT 0",
        "admin_bonus_score": "REAL",
        "last_question_index": "INTEGER NOT NULL DEFAULT 0",
        "assessment_id": "INTEGER",
        "auth_method": "TEXT",
        "google_sub": "TEXT",
    }
    for name, definition in session_additions.items():
        if name not in session_cols:
            conn.execute(f"ALTER TABLE exam_sessions ADD COLUMN {name} {definition}")

    coding_cols = _table_columns(conn, "coding_sessions") if "coding_sessions" in _table_names(conn) else set()
    for name, definition in {
        "first_name": "TEXT",
        "last_name": "TEXT",
    }.items():
        if coding_cols and name not in coding_cols:
            conn.execute(f"ALTER TABLE coding_sessions ADD COLUMN {name} {definition}")

    # Best-effort compatibility for attempts created before First/Last Name were separate fields.
    for table in ("exam_sessions", "coding_sessions"):
        if table not in _table_names(conn):
            continue
        cols = _table_columns(conn, table)
        if not {"id", "student_name", "first_name", "last_name"}.issubset(cols):
            continue
        rows = conn.execute(
            f"SELECT id,student_name,first_name,last_name FROM {table} WHERE student_name IS NOT NULL"
        ).fetchall()
        for row in rows:
            if row["first_name"] and row["last_name"]:
                continue
            parts = str(row["student_name"] or "").strip().split()
            if not parts:
                continue
            first = row["first_name"] or (" ".join(parts[:-1]) if len(parts) > 1 else parts[0])
            last = row["last_name"] or (parts[-1] if len(parts) > 1 else "")
            conn.execute(f"UPDATE {table} SET first_name=?,last_name=? WHERE id=?", (first,last,row["id"]))

    question_cols = _table_columns(conn, "questions")
    if "active" not in question_cols:
        conn.execute("ALTER TABLE questions ADD COLUMN active INTEGER NOT NULL DEFAULT 1")
    if "created_by" not in question_cols:
        conn.execute("ALTER TABLE questions ADD COLUMN created_by TEXT NOT NULL DEFAULT 'builtin'")
    if "subject_id" not in question_cols:
        conn.execute("ALTER TABLE questions ADD COLUMN subject_id INTEGER")
    if "assessment_id" not in question_cols:
        conn.execute("ALTER TABLE questions ADD COLUMN assessment_id INTEGER")
    if "points" not in question_cols:
        conn.execute("ALTER TABLE questions ADD COLUMN points INTEGER NOT NULL DEFAULT 1")
    if "position" not in question_cols:
        conn.execute("ALTER TABLE questions ADD COLUMN position INTEGER")

    assessment_cols = _table_columns(conn, "assessments") if "assessments" in _table_names(conn) else set()
    for name, definition in {
        "display_type": "TEXT NOT NULL DEFAULT 'Assessment'",
        "reveal_score": "INTEGER NOT NULL DEFAULT 1",
        "shuffle_questions": "INTEGER NOT NULL DEFAULT 1",
        "shuffle_options": "INTEGER NOT NULL DEFAULT 1",
        "allowed_sections": "TEXT NOT NULL DEFAULT ''",
        "question_limit": "INTEGER NOT NULL DEFAULT 0",
        "deleted_at": "TEXT",
    }.items():
        if assessment_cols and name not in assessment_cols:
            conn.execute(f"ALTER TABLE assessments ADD COLUMN {name} {definition}")

    batch_cols = _table_columns(conn, "batches")
    if "assessment_type" not in batch_cols:
        conn.execute("ALTER TABLE batches ADD COLUMN assessment_type TEXT NOT NULL DEFAULT 'midterm'")
    if "subject_id" not in batch_cols:
        conn.execute("ALTER TABLE batches ADD COLUMN subject_id INTEGER")
    if "assessment_id" not in batch_cols:
        conn.execute("ALTER TABLE batches ADD COLUMN assessment_id INTEGER")
    conn.execute("UPDATE batches SET assessment_type='midterm' WHERE slot BETWEEN 1 AND 8")
    conn.commit()



def _future_access_code(prefix="LAB"):
    secret = "".join(secrets.choice(SESSION_KEY_ALPHABET) for _ in range(10))
    return f"{prefix}-{secret[:5]}-{secret[5:]}"


def _ensure_performance_indexes(conn):
    """Add indexes used by the live monitor, chat, scoring, and resume paths."""
    statements = [
        "CREATE INDEX IF NOT EXISTS idx_exam_sessions_active ON exam_sessions(status,is_test,monitor_done)",
        "CREATE INDEX IF NOT EXISTS idx_exam_sessions_batch ON exam_sessions(batch_id)",
        "CREATE INDEX IF NOT EXISTS idx_exam_sessions_assessment ON exam_sessions(assessment_id)",
        "CREATE INDEX IF NOT EXISTS idx_exam_sessions_email ON exam_sessions(email)",
        "CREATE INDEX IF NOT EXISTS idx_session_questions_session_order ON session_questions(session_id,q_order)",
        "CREATE INDEX IF NOT EXISTS idx_session_bonus_session ON session_bonus_answers(session_id,q_order)",
        "CREATE INDEX IF NOT EXISTS idx_proctor_events_session_id ON proctor_events(session_id,id)",
        "CREATE INDEX IF NOT EXISTS idx_exam_messages_unread ON exam_messages(session_id,sender,read_at,id)",
        "CREATE INDEX IF NOT EXISTS idx_coding_sessions_active ON coding_sessions(status,is_test)",
        "CREATE INDEX IF NOT EXISTS idx_coding_submissions_session ON coding_submissions(session_id,task_id)",
    ]
    for statement in statements:
        conn.execute(statement)


def _ensure_future_seed(conn, admin_username):
    now = iso_now()
    admin = conn.execute("SELECT id FROM admins WHERE username=?", (admin_username,)).fetchone()
    if admin:
        conn.execute(
            "UPDATE admins SET display_name=COALESCE(NULLIF(display_name,''),?), role=COALESCE(NULLIF(role,''),'owner'), active=1 WHERE id=?",
            (admin_username, admin["id"]),
        )
        conn.execute(
            """INSERT INTO instructors(admin_id,display_name,email,active,created_at)
               VALUES(?,?,NULL,1,?) ON CONFLICT(admin_id) DO NOTHING""",
            (admin["id"], admin_username, now),
        )
    conn.execute(
        """INSERT INTO subjects(code,name,term,school_year,active,created_at)
           VALUES('CSDC101','Fundamentals of Programming','1st Semester','2026-2027',1,?)
           ON CONFLICT(code,term,school_year) DO NOTHING""",
        (now,),
    )
    subject = conn.execute(
        "SELECT * FROM subjects WHERE code='CSDC101' AND term='1st Semester' AND school_year='2026-2027'"
    ).fetchone()
    instructor = conn.execute("SELECT * FROM instructors WHERE admin_id=?", (admin["id"],)).fetchone() if admin else None
    if subject and instructor:
        conn.execute(
            """INSERT INTO subject_instructors(subject_id,instructor_id,role) VALUES(?,?,'owner')
               ON CONFLICT(subject_id,instructor_id) DO NOTHING""",
            (subject["id"], instructor["id"]),
        )

    defaults = [
        ('csdc101-midterm','Midterm Examination','midterm','Current 50-point examination plus bonus.',90),
        ('csdc101-posttest','Monday Post-test','posttest','Post-test assessment family.',90),
        ('csdc101-dryrun','Public Dry Run','dryrun','Deployment rehearsal assessment.',90),
    ]
    for slug,title,atype,description,duration in defaults:
        conn.execute(
            """INSERT INTO assessments(subject_id,title,slug,assessment_type,description,duration_minutes,
                       max_attempts,security_mode,active,created_by_instructor_id,created_at)
               VALUES(?,?,?,?,?,?,1,'strict',1,?,?) ON CONFLICT(slug) DO NOTHING""",
            (subject["id"],title,slug,atype,description,duration,instructor["id"] if instructor else None,now),
        )
    for atype in ('midterm','posttest','dryrun'):
        assessment = conn.execute("SELECT id, access_code FROM assessments WHERE slug=?", (f"csdc101-{atype}",)).fetchone()
        if assessment:
            conn.execute("UPDATE batches SET subject_id=?, assessment_id=? WHERE assessment_type=?", (subject["id"],assessment["id"],atype))
            conn.execute("UPDATE questions SET subject_id=?, assessment_id=? WHERE batch_slot IN (SELECT slot FROM batches WHERE assessment_type=?)", (subject["id"],assessment["id"],atype))
            conn.execute("UPDATE exam_sessions SET assessment_id=? WHERE batch_id IN (SELECT id FROM batches WHERE assessment_type=?) AND assessment_id IS NULL", (assessment["id"],atype))
            # The public dry run uses one real student-facing batch. Keep its key visible in
            # the unified assessment catalog so instructors do not lose the entry key.
            if atype == 'dryrun':
                batch = conn.execute(
                    "SELECT id, access_code FROM batches WHERE assessment_type='dryrun' ORDER BY slot LIMIT 1"
                ).fetchone()
                if batch:
                    effective_key = assessment["access_code"] or batch["access_code"]
                    if effective_key:
                        conn.execute("UPDATE assessments SET access_code=? WHERE id=?", (effective_key, assessment["id"]))
                        conn.execute("UPDATE batches SET access_code=? WHERE id=?", (effective_key, batch["id"]))

    # Seed one extensible C++ Programming Lab without hard-coding a public GitHub secret.
    lab_assessment = conn.execute("SELECT * FROM assessments WHERE slug='csdc101-cpp-lab'").fetchone()
    if not lab_assessment:
        access = _future_access_code('CPP')
        cur = conn.execute(
            """INSERT INTO assessments(subject_id,title,slug,assessment_type,description,duration_minutes,
                       access_code,max_attempts,security_mode,active,created_by_instructor_id,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id""",
            (subject["id"],'C++ Programming Lab','csdc101-cpp-lab','programming_lab',
             'Secure browser-based C++ coding environment.',90,access,1,'strict',1,
             instructor["id"] if instructor else None,now),
        )
        lab_assessment_id = cur.fetchone()[0]
    else:
        lab_assessment_id = lab_assessment["id"]
    lab_starter = "#include <iostream>\nusing namespace std;\n\nint main() {\n    return 0;\n}\n"
    conn.execute(
        """INSERT INTO programming_labs(assessment_id,language,title,instructions,starter_code,allow_custom_input,active,created_at)
           VALUES(?, 'cpp', 'C++ Programming Lab', 'Write, run, test, and submit C++17 programs inside Custos.', ?, 1, 1, ?)
           ON CONFLICT(assessment_id) DO NOTHING""",
        (lab_assessment_id, lab_starter, now),
    )
    lab = conn.execute("SELECT id FROM programming_labs WHERE assessment_id=?", (lab_assessment_id,)).fetchone()
    if lab:
        tests = json.dumps([{"stdin":"2 3\n","expected":"5"},{"stdin":"10 -4\n","expected":"6"}])
        task_starter = "#include <iostream>\nusing namespace std;\n\nint main() {\n    int a, b;\n    cin >> a >> b;\n    cout << a + b;\n    return 0;\n}\n"
        conn.execute(
            """INSERT INTO programming_tasks(lab_id,position,title,prompt,starter_code,points,hidden_tests_json,active)
               VALUES(?,1,'Sum Two Integers','Read two integers and print their sum.',?,10,?,1)
               ON CONFLICT(lab_id,position) DO NOTHING""",
            (lab["id"], task_starter, tests),
        )

def init_db(admin_username="admin", admin_password="ChangeMe123!"):
    conn = connect()
    advisory_lock = False
    try:
        # Prevent concurrent Gunicorn workers from racing through first-time Postgres initialization.
        if DATABASE_ENGINE == "postgresql":
            conn.execute("SELECT pg_advisory_lock(2026092601)")
            advisory_lock = True

        _apply_schema(conn)
        migrate_schema(conn)
        _ensure_performance_indexes(conn)

        conn.execute(
            """INSERT INTO admins(username, password_hash) VALUES (?, ?)
               ON CONFLICT(username) DO UPDATE SET password_hash=excluded.password_hash""",
            (admin_username, generate_password_hash(admin_password)),
        )

        for section in range(1, 5):
            for batch_index, batch_label in enumerate(("A", "B")):
                slot = (section - 1) * 2 + batch_index + 1
                conn.execute(
                    """INSERT INTO batches(slot, section, batch_label, name, access_code, duration_minutes, assessment_type)
                       VALUES (?, ?, ?, ?, ?, 90, 'midterm')
                       ON CONFLICT(slot) DO NOTHING""",
                    (
                        slot,
                        f"Section {section}",
                        batch_label,
                        f"Midterm · Section {section} - Batch {batch_label}",
                        unique_session_key(conn, "midterm", f"Section {section}", batch_label),
                    ),
                )
                conn.execute("UPDATE batches SET assessment_type='midterm' WHERE slot=?", (slot,))

        for section in range(1, 5):
            for batch_index, batch_label in enumerate(("A", "B")):
                set_no = (section - 1) * 2 + batch_index + 1
                slot = 8 + set_no
                conn.execute(
                    """INSERT INTO batches(slot, section, batch_label, name, access_code, duration_minutes, assessment_type)
                       VALUES (?, ?, ?, ?, ?, 90, 'posttest')
                       ON CONFLICT(slot) DO NOTHING""",
                    (
                        slot,
                        f"Section {section}",
                        batch_label,
                        f"Post-test · Section {section} - Batch {batch_label}",
                        unique_session_key(conn, "posttest", f"Section {section}", batch_label),
                    ),
                )
                conn.execute("UPDATE batches SET assessment_type='posttest' WHERE slot=?", (slot,))

        conn.execute(
            """INSERT INTO batches(slot,section,batch_label,name,access_code,duration_minutes,reveal_score,active,assessment_type)
               VALUES(17,'DRY RUN','A','Custos Public Dry Run','CUSTOS-DRYRUN-GOLIATHUS',90,1,1,'dryrun')
               ON CONFLICT(slot) DO NOTHING"""
        )
        conn.execute(
            """UPDATE batches SET section='DRY RUN', batch_label='A', name='Custos Public Dry Run',
               assessment_type='dryrun', active=1 WHERE slot=17"""
        )

        legacy_rows = conn.execute(
            "SELECT id, section, batch_label, assessment_type, access_code FROM batches"
        ).fetchall()
        for row in legacy_rows:
            code = row["access_code"] or ""
            if code.startswith("CSDC101-S") or code.startswith("CSDC101-PT-S"):
                conn.execute(
                    "UPDATE batches SET access_code=? WHERE id=?",
                    (
                        unique_session_key(conn, row["assessment_type"], row["section"], row["batch_label"]),
                        row["id"],
                    ),
                )

        for position, topic, prompt, accepted_answer in DEFAULT_BONUS_QUESTIONS:
            conn.execute(
                """INSERT INTO bonus_questions(assessment_type,position,topic,prompt,accepted_answer,active)
                   VALUES('midterm',?,?,?,?,1)
                   ON CONFLICT(assessment_type,position) DO NOTHING""",
                (position, topic, prompt, accepted_answer),
            )

        _ensure_future_seed(conn, admin_username)
        conn.execute(
            """INSERT INTO app_meta(key,value) VALUES('schema_version',?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
            (DB_SCHEMA_VERSION,),
        )

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        if advisory_lock:
            try:
                conn.execute("SELECT pg_advisory_unlock(2026092601)")
                conn.commit()
            except Exception:
                pass
        conn.close()


def ensure_db_initialized(admin_username="admin", admin_password="ChangeMe123!", force=False):
    """Fast startup guard for long-running and serverless deployments.

    A full schema migration/seed is only run when the database is new, this build
    has a newer schema marker, or force=True. Normal cold starts perform one tiny
    metadata query and reuse that PostgreSQL connection through the pool.
    """
    if force:
        init_db(admin_username=admin_username, admin_password=admin_password)
        return True

    conn = None
    try:
        conn = connect()
        if DATABASE_ENGINE == "postgresql":
            exists = conn.execute(
                "SELECT 1 FROM information_schema.tables WHERE table_schema=current_schema() AND table_name='app_meta'"
            ).fetchone()
        else:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='app_meta'"
            ).fetchone()
        if not exists:
            if conn:
                conn.close()
                conn = None
            init_db(admin_username=admin_username, admin_password=admin_password)
            return True
        row = conn.execute("SELECT value FROM app_meta WHERE key='schema_version'").fetchone()
        current = row["value"] if row else None
        if current == DB_SCHEMA_VERSION:
            return False
    except Exception:
        # If the metadata probe fails because the database is only partially
        # initialized, fall back to the idempotent migration path below.
        pass
    finally:
        if conn is not None:
            conn.close()

    init_db(admin_username=admin_username, admin_password=admin_password)
    return True


def iso_now():
    return datetime.now(APP_TZ).isoformat(timespec="seconds")

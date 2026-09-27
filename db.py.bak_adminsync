import os
import secrets
import sqlite3
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
    active INTEGER NOT NULL DEFAULT 1,
    created_by TEXT NOT NULL DEFAULT 'builtin'
);

CREATE TABLE IF NOT EXISTS exam_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL,
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
"""

# PostgreSQL uses SERIAL for auto-incrementing integer primary keys.
POSTGRES_SCHEMA = (
    SQLITE_SCHEMA.replace("PRAGMA foreign_keys = ON;", "")
    .replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
)


def _pg_sql(sql):
    """Translate the SQLite-style parameter marker used by Custos to psycopg2."""
    return sql.replace("?", "%s")


class PostgresConnection:
    """Small compatibility wrapper so the existing Custos query layer works on Postgres."""

    def __init__(self, raw_connection, dict_cursor_factory):
        self._conn = raw_connection
        self._dict_cursor_factory = dict_cursor_factory

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
        self._conn.close()


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
        url = DATABASE_URL
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://"):]
        raw = psycopg2.connect(url, connect_timeout=10)
        return PostgresConnection(raw, DictCursor)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


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
        conn.executescript(SQLITE_SCHEMA)
        return
    for statement in POSTGRES_SCHEMA.split(";"):
        statement = statement.strip()
        if statement:
            conn.execute(statement)
    conn.commit()


def migrate_schema(conn):
    session_cols = _table_columns(conn, "exam_sessions")
    session_additions = {
        "is_test": "INTEGER NOT NULL DEFAULT 0",
        "test_label": "TEXT",
        "untimed": "INTEGER NOT NULL DEFAULT 0",
        "student_name": "TEXT",
        "program": "TEXT",
        "class_section": "TEXT",
        "terms_accepted_at": "TEXT",
        "violation_count": "INTEGER NOT NULL DEFAULT 0",
        "security_locked": "INTEGER NOT NULL DEFAULT 0",
        "temp_locked_until": "TEXT",
        "pending_blackout": "INTEGER NOT NULL DEFAULT 0",
        "bonus_correct": "INTEGER NOT NULL DEFAULT 0",
        "bonus_score": "INTEGER NOT NULL DEFAULT 0",
        "admin_bonus_score": "REAL",
    }
    for name, definition in session_additions.items():
        if name not in session_cols:
            conn.execute(f"ALTER TABLE exam_sessions ADD COLUMN {name} {definition}")

    question_cols = _table_columns(conn, "questions")
    if "active" not in question_cols:
        conn.execute("ALTER TABLE questions ADD COLUMN active INTEGER NOT NULL DEFAULT 1")
    if "created_by" not in question_cols:
        conn.execute("ALTER TABLE questions ADD COLUMN created_by TEXT NOT NULL DEFAULT 'builtin'")

    batch_cols = _table_columns(conn, "batches")
    if "assessment_type" not in batch_cols:
        conn.execute("ALTER TABLE batches ADD COLUMN assessment_type TEXT NOT NULL DEFAULT 'midterm'")
    conn.execute("UPDATE batches SET assessment_type='midterm' WHERE slot BETWEEN 1 AND 8")
    conn.commit()


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

        conn.execute(
            """INSERT INTO admins(username, password_hash) VALUES (?, ?)
               ON CONFLICT(username) DO NOTHING""",
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
               VALUES(17,'DRY RUN','A','Custos Public Dry Run','CUSTOS-DRYRUN-SCARABS',90,1,1,'dryrun')
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


def iso_now():
    return datetime.now(APP_TZ).isoformat(timespec="seconds")

"""Classroom-based instructors: who is an instructor, and what they can see.

Switched on with CLASSROOM_INSTRUCTORS=1 (requires GOOGLE_CLIENT_ID). Off, Custos
behaves exactly as before.

- Owners: emails in CUSTOS_OWNER_EMAILS. They sign in with Google, skip the
  Classroom check, and see everything (role 'owner').
- Instructors: anyone listed as a Teacher of at least one ACTIVE Google
  Classroom course. Checked at every instructor sign-in (Google access token
  with Classroom read scope); the account is created on first sign-in. Each
  course they teach becomes a Custos subject linked to them, and links to
  courses they no longer teach are removed.
- Scoping: an instructor sees only assessments of their linked subjects. This
  module's before_request guard is DEFAULT-DENY for instructors: an /admin
  endpoint is allowed only if it is a known list page (whose query is filtered
  with filter_rows) or every assessment it refers to (URL, query string or
  form) belongs to one of their subjects. Anything unknown is refused.
- The username/password login is hidden; /admin/login?password=1 remains as
  an owner-only emergency path.
"""
import os
import secrets

from flask import abort, g, jsonify, request, session
from werkzeug.security import generate_password_hash

from db import connect, iso_now

CLASSROOM_INSTRUCTORS = os.getenv("CLASSROOM_INSTRUCTORS", "0") == "1" and bool(os.getenv("GOOGLE_CLIENT_ID", "").strip())
_OWNER_EMAILS_RAW = [e.strip().lower() for e in os.getenv("CUSTOS_OWNER_EMAILS", "").split(",") if e.strip()]

# /admin pages an instructor may open without an assessment reference; each of
# these filters what it shows with filter_rows()/visible_* below.
INSTRUCTOR_LIST_ENDPOINTS = {
    "admin_login", "admin_logout", "admin_dashboard", "nextgen.workspace",
    "admin_monitor", "admin_monitor_data", "google.monitor_not_started",
    "admin_messages", "admin_message_threads",
    "admin_questions", "admin_testing", "admin_analysis",
    "nextgen.assessment_add",
    "admin_testing_return",  # acts only on the instructor's own test attempt in their session
}
# Owner-only: instructor/subject management and Peter's built-in CSDC101 tools.
OWNER_ONLY_ENDPOINTS = {
    "nextgen.subject_add", "nextgen.subject_edit", "nextgen.instructor_add", "nextgen.instructor_edit",
    "admin_regenerate_all_keys", "export_session_keys", "export_questions", "import_private_questions",
    "admin_bonus_edit", "nextgen.admin_ide", "nextgen.admin_ide_lab", "nextgen.admin_ide_task_add",
    "nextgen.admin_ide_task_edit", "nextgen.admin_ide_preview", "nextgen.admin_ide_session",
    "nextgen.admin_ide_unlock",
}


def active():
    return CLASSROOM_INSTRUCTORS


def is_owner_email(email):
    from google_integration import canonical_email

    return canonical_email(email) in {canonical_email(e) for e in _OWNER_EMAILS_RAW}


def scoped():
    """True when the signed-in admin is a Classroom instructor (not an owner)."""
    return CLASSROOM_INSTRUCTORS and session.get("admin_id") and session.get("admin_role") != "owner"


def _instructor_id(conn):
    row = conn.execute("SELECT id FROM instructors WHERE admin_id=?", (session.get("admin_id"),)).fetchone()
    return row["id"] if row else None


def visible_subject_ids(conn):
    if "scope_subjects" in g:
        return g.scope_subjects
    iid = _instructor_id(conn)
    ids = {r["subject_id"] for r in conn.execute(
        "SELECT subject_id FROM subject_instructors WHERE instructor_id=?", (iid,)
    ).fetchall()} if iid else set()
    g.scope_subjects = ids
    return ids


def visible_assessment_ids(conn):
    if "scope_assessments" in g:
        return g.scope_assessments
    subjects = visible_subject_ids(conn)
    ids = set()
    if subjects:
        marks = ",".join("?" * len(subjects))
        ids = {r["id"] for r in conn.execute(
            f"SELECT id FROM assessments WHERE subject_id IN ({marks})", tuple(subjects)
        ).fetchall()}
    g.scope_assessments = ids
    return ids


def filter_rows(conn, rows, key="id", kind="assessment"):
    """Keep only rows the current admin may see. No-op for owners / feature off."""
    if not scoped():
        return rows
    allowed = visible_subject_ids(conn) if kind == "subject" else visible_assessment_ids(conn)
    return [r for r in rows if r[key] in allowed]


# ---------------------------------------------------------------- the guard

def _referenced_assessments(conn):
    """Every assessment id this request refers to, or None if it refers to a
    resource type the guard can't resolve (-> deny)."""
    refs = set()
    va = request.view_args or {}
    ep = request.endpoint or ""

    def one(sql, value):
        row = conn.execute(sql, (value,)).fetchone()
        refs.add(row[0] if row else -1)  # unknown id -> -1 (never visible)

    for name, value in va.items():
        if name == "assessment_id":
            refs.add(int(value))
        elif name == "batch_id":
            one("SELECT assessment_id FROM batches WHERE id=?", value)
        elif name == "sid":
            one("SELECT assessment_id FROM exam_sessions WHERE id=?", value)
        elif name in ("qid", "question_id"):
            one("SELECT assessment_id FROM questions WHERE id=?", value)
        elif name == "roster_id":
            continue  # always paired with assessment_id, and filtered by it
        else:
            return None  # e.g. subject_id/instructor_id/lab_id/<assessment> type: not resolvable here
    for src in (request.args, request.form):
        raw = src.get("assessment_id", "").strip()
        if raw:
            refs.add(int(raw) if raw.isdigit() else -1)
        raw = src.get("batch_id", "").strip()
        if raw:
            if raw.isdigit():
                one("SELECT assessment_id FROM batches WHERE id=?", int(raw))
            else:
                refs.add(-1)
        legacy = src.get("assessment", "").strip().lower()
        if legacy and ep == "admin_dashboard":
            one("SELECT id FROM assessments WHERE assessment_type=? AND deleted_at IS NULL ORDER BY id LIMIT 1", legacy)
        slot = src.get("batch_slot", "").strip()
        if slot:
            if slot.isdigit():
                one("SELECT assessment_id FROM batches WHERE slot=?", int(slot))
            else:
                refs.add(-1)
    raw = request.form.get("subject_id", "").strip()
    if raw:
        refs.add(("subject", int(raw) if raw.isdigit() else -1))
    return refs


def guard():
    """before_request: default-deny access control for Classroom instructors."""
    if not request.path.startswith("/admin") or not scoped():
        return None
    ep = request.endpoint or ""
    if ep in OWNER_ONLY_ENDPOINTS:
        abort(403, "Only a Custos owner can use this page.")
    conn = connect()
    try:
        refs = _referenced_assessments(conn)
        if refs is None:
            abort(403, "Not available to course instructors.")
        if not refs:
            if ep in INSTRUCTOR_LIST_ENDPOINTS:
                return None
            abort(403, "Not available to course instructors.")
        subjects = visible_subject_ids(conn)
        assessments = visible_assessment_ids(conn)
        for ref in refs:
            ok = (ref[1] in subjects) if isinstance(ref, tuple) else (ref in assessments)
            if not ok:
                abort(404)
    finally:
        conn.close()
    return None


# ---------------------------------------------------------------- sign-in

def sync_classroom_subjects(conn, instructor_id, courses):
    """Each taught course -> a subject linked to this instructor; drop links to
    Classroom-derived subjects for courses no longer taught."""
    keep = set()
    for c in courses:
        cid = str(c.get("id") or "")
        if not cid:
            continue
        row = conn.execute("SELECT id FROM subjects WHERE classroom_course_id=?", (cid,)).fetchone()
        name = (c.get("name") or "Google Classroom course")[:120]
        code = (c.get("section") or c.get("descriptionHeading") or name)[:40]
        if row:
            sid = row["id"]
            conn.execute("UPDATE subjects SET name=?, code=?, active=1 WHERE id=?", (name, code, sid))
        else:
            sid = conn.execute(
                """INSERT INTO subjects(code,name,term,school_year,active,created_at,classroom_course_id)
                   VALUES (?,?,'','',1,?,?) RETURNING id""",
                (code, name, iso_now(), cid),
            ).fetchone()[0]
        conn.execute(
            """INSERT INTO subject_instructors(subject_id,instructor_id,role) VALUES(?,?,'instructor')
               ON CONFLICT(subject_id,instructor_id) DO NOTHING""",
            (sid, instructor_id),
        )
        keep.add(sid)
    stale = conn.execute(
        """SELECT si.subject_id FROM subject_instructors si JOIN subjects s ON s.id=si.subject_id
           WHERE si.instructor_id=? AND s.classroom_course_id IS NOT NULL""",
        (instructor_id,),
    ).fetchall()
    for r in stale:
        if r["subject_id"] not in keep:
            conn.execute("DELETE FROM subject_instructors WHERE instructor_id=? AND subject_id=?",
                         (instructor_id, r["subject_id"]))
    return keep


def ensure_admin(conn, email, display_name, role):
    """Find the admin/instructor row for this Google email, creating it if needed."""
    from google_integration import canonical_email, email_variants

    email = canonical_email(email)
    variants = email_variants(email)
    marks = ",".join("?" * len(variants))
    admin = conn.execute(
        f"SELECT * FROM admins WHERE LOWER(COALESCE(email,'')) IN ({marks})", tuple(variants)
    ).fetchone()
    if admin is None:
        base = "".join(ch for ch in email.split("@", 1)[0].lower() if ch.isalnum() or ch in "._-")[:40] or "instructor"
        username, n = base, 1
        while conn.execute("SELECT 1 FROM admins WHERE username=?", (username,)).fetchone():
            n += 1
            username = f"{base}{n}"
        admin_id = conn.execute(
            """INSERT INTO admins(username,password_hash,display_name,email,role,active)
               VALUES (?,?,?,?,?,1) RETURNING id""",
            (username, generate_password_hash(secrets.token_urlsafe(48)), display_name, email, role),
        ).fetchone()[0]
        admin = conn.execute("SELECT * FROM admins WHERE id=?", (admin_id,)).fetchone()
    elif role == "owner" and admin["role"] != "owner":
        conn.execute("UPDATE admins SET role='owner' WHERE id=?", (admin["id"],))
        admin = conn.execute("SELECT * FROM admins WHERE id=?", (admin["id"],)).fetchone()
    inst = conn.execute("SELECT * FROM instructors WHERE admin_id=?", (admin["id"],)).fetchone()
    if inst is None:
        conn.execute(
            "INSERT INTO instructors(admin_id,display_name,email,active,created_at) VALUES (?,?,?,1,?)",
            (admin["id"], display_name, email, iso_now()),
        )
        inst = conn.execute("SELECT * FROM instructors WHERE admin_id=?", (admin["id"],)).fetchone()
    return admin, inst


def register(app):
    app.before_request(guard)
    app.jinja_env.globals.update(classroom_instructors=CLASSROOM_INSTRUCTORS)

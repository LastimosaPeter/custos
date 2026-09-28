from __future__ import annotations

import csv
import io
import json
import math
import os
import re
import secrets
from datetime import datetime, timedelta
from functools import wraps

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import generate_password_hash

from code_runner import grade_hidden_tests, run_cpp, runner_status
from db import APP_TZ, connect, iso_now

bp = Blueprint("nextgen", __name__)

ALLOWED_EMAIL_DOMAIN = os.getenv("ALLOWED_EMAIL_DOMAIN", "adnu.edu.ph").lower()
STUDENT_IDE_ENABLED = os.getenv("STUDENT_IDE_ENABLED", "0") == "1"
STUDENT_SECTIONS = {"ZT": {"11", "12", "13"}, "ZS": {"11"}}
TEMP_LOCK_SECONDS = 15
MAX_SECURITY_VIOLATIONS = 3
SECURITY_DEDUPE_SECONDS = 3


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin_id"):
            return redirect(url_for("admin_login"))
        return view(*args, **kwargs)
    return wrapped



def owner_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin_id"):
            return redirect(url_for("admin_login"))
        if session.get("admin_role", "owner") != "owner":
            abort(403, "Owner access required.")
        return view(*args, **kwargs)
    return wrapped


def ide_session_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        sid = session.get("coding_session_id")
        if not sid:
            return redirect(url_for("nextgen.ide_login"))
        if not STUDENT_IDE_ENABLED and not session.get("admin_id"):
            conn = connect()
            row = conn.execute("SELECT is_test FROM coding_sessions WHERE id=?", (sid,)).fetchone()
            conn.close()
            if not row or not row["is_test"]:
                session.pop("coding_session_id", None)
                return redirect(url_for("nextgen.ide_coming_soon"))
        return view(*args, **kwargs)
    return wrapped


def require_csrf():
    supplied = request.headers.get("X-CSRFToken") or request.form.get("csrf_token")
    expected = session.get("csrf_token", "")
    if not supplied or not expected or not secrets.compare_digest(supplied, expected):
        abort(400, "Invalid CSRF token")


def parse_iso(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=APP_TZ)
        return dt.astimezone(APP_TZ)
    except Exception:
        return None


def _current_instructor(conn):
    admin_id = session.get("admin_id")
    return conn.execute("SELECT * FROM instructors WHERE admin_id=?", (admin_id,)).fetchone()


def _make_access_code(prefix="ASSESS"):
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    value = "".join(secrets.choice(alphabet) for _ in range(10))
    return f"{prefix}-{value[:5]}-{value[5:]}"


def _slugify(value):
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").casefold()).strip("-")
    return slug or f"assessment-{secrets.token_hex(3)}"


def _identity(form):
    first_name = re.sub(r"\s+", " ", form.get("first_name", "").strip())
    last_name = re.sub(r"\s+", " ", form.get("last_name", "").strip())
    program = form.get("program", "").strip().upper()
    section = form.get("class_section", "").strip()
    email = form.get("email", "").strip().lower()
    if len(first_name) < 1 or len(first_name) > 60:
        return None, "Enter your first name."
    if len(last_name) < 1 or len(last_name) > 60:
        return None, "Enter your last name."
    name = f"{first_name} {last_name}".strip()
    if program not in STUDENT_SECTIONS or section not in STUDENT_SECTIONS[program]:
        return None, "Choose a valid program and section."
    email_re = rf"^[A-Za-z0-9._%+\-]+@{re.escape(ALLOWED_EMAIL_DOMAIN)}$"
    if not re.match(email_re, email):
        return None, f"Use your @{ALLOWED_EMAIL_DOMAIN} account."
    return (first_name, last_name, name, program, section, email), None


def _coding_security_state(row):
    now = datetime.now(APP_TZ)
    temp_until = parse_iso(row["temp_locked_until"])
    temp_remaining = 0
    if temp_until and temp_until > now:
        temp_remaining = max(0, math.ceil((temp_until - now).total_seconds()))
    return {
        "violation_count": int(row["violation_count"] or 0),
        "permanent": bool(row["security_locked"]),
        "pending": bool(row["pending_blackout"]),
        "temp_remaining": temp_remaining,
    }


def _coding_blocked(row):
    state = _coding_security_state(row)
    return state["permanent"] or state["pending"] or state["temp_remaining"] > 0, state


def _load_coding_session(conn, sid):
    return conn.execute(
        """SELECT cs.*, pl.title AS lab_title, pl.language, pl.instructions, pl.allow_custom_input,
                  a.title AS assessment_title, a.duration_minutes, a.security_mode, a.start_at, a.end_at,
                  s.code AS subject_code, s.name AS subject_name
           FROM coding_sessions cs
           JOIN programming_labs pl ON pl.id=cs.lab_id
           JOIN assessments a ON a.id=pl.assessment_id
           JOIN subjects s ON s.id=a.subject_id
           WHERE cs.id=?""",
        (sid,),
    ).fetchone()


def _coding_remaining(cs):
    if cs["is_test"]:
        return None
    started = parse_iso(cs["started_at"])
    if not started:
        return None
    deadline = started + timedelta(minutes=int(cs["duration_minutes"] or 90))
    return max(0, int((deadline - datetime.now(APP_TZ)).total_seconds()))


def _coding_log(conn, sid, event_type, detail=""):
    conn.execute(
        "INSERT INTO coding_events(session_id,event_type,detail,created_at) VALUES(?,?,?,?)",
        (sid, event_type, str(detail)[:1000], iso_now()),
    )


@bp.route("/admin/workspace")
@admin_required
def workspace():
    conn = connect()
    subjects = conn.execute(
        """SELECT s.*,
                  (SELECT COUNT(*) FROM assessments a WHERE a.subject_id=s.id AND a.deleted_at IS NULL) AS assessment_count,
                  (SELECT COUNT(*) FROM subject_instructors si WHERE si.subject_id=s.id) AS instructor_count
           FROM subjects s ORDER BY s.active DESC, s.code, s.school_year DESC"""
    ).fetchall()
    instructors = conn.execute(
        """SELECT i.*, a.username, a.role,
                  (SELECT COUNT(*) FROM subject_instructors si WHERE si.instructor_id=i.id) AS subject_count
           FROM instructors i LEFT JOIN admins a ON a.id=i.admin_id
           ORDER BY i.active DESC, i.display_name"""
    ).fetchall()
    assessments = conn.execute(
        """SELECT a.*, s.code AS subject_code,
                  CASE WHEN a.assessment_type='dryrun' THEN COALESCE(a.access_code,(SELECT b.access_code FROM batches b WHERE b.assessment_id=a.id ORDER BY b.id LIMIT 1)) ELSE a.access_code END AS effective_access_code,
                  (SELECT b.id FROM batches b WHERE b.assessment_id=a.id ORDER BY b.id LIMIT 1) AS delivery_batch_id,
                  (SELECT COUNT(*) FROM programming_labs pl WHERE pl.assessment_id=a.id) AS has_lab
           FROM assessments a JOIN subjects s ON s.id=a.subject_id
           WHERE a.deleted_at IS NULL
           ORDER BY a.active DESC, s.code, a.created_at DESC"""
    ).fetchall()
    conn.close()
    return render_template(
        "admin_workspace.html", subjects=subjects, instructors=instructors,
        assessments=assessments, runner=runner_status()
    )


@bp.post("/admin/workspace/subject/add")
@admin_required
def subject_add():
    require_csrf()
    code = request.form.get("code", "").strip().upper()
    name = request.form.get("name", "").strip()
    term = request.form.get("term", "").strip()
    school_year = request.form.get("school_year", "").strip()
    if not code or not name:
        flash("Subject code and name are required.", "error")
        return redirect(url_for("nextgen.workspace"))
    conn = connect()
    try:
        conn.execute(
            """INSERT INTO subjects(code,name,term,school_year,active,created_at)
               VALUES(?,?,?,?,1,?)""",
            (code, name, term, school_year, iso_now()),
        )
        instructor = _current_instructor(conn)
        subject = conn.execute(
            "SELECT id FROM subjects WHERE code=? AND term=? AND school_year=?",
            (code, term, school_year),
        ).fetchone()
        if instructor and subject:
            conn.execute(
                """INSERT INTO subject_instructors(subject_id,instructor_id,role) VALUES(?,?,'owner')
                   ON CONFLICT(subject_id,instructor_id) DO NOTHING""",
                (subject["id"], instructor["id"]),
            )
        conn.commit()
        flash(f"Subject {code} created.", "success")
    except Exception as exc:
        conn.rollback()
        flash(f"Could not create subject: {exc}", "error")
    finally:
        conn.close()
    return redirect(url_for("nextgen.workspace"))


@bp.post("/admin/workspace/subject/<int:subject_id>/edit")
@admin_required
def subject_edit(subject_id):
    require_csrf()
    code = request.form.get("code", "").strip().upper()
    name = request.form.get("name", "").strip()
    term = request.form.get("term", "").strip()
    school_year = request.form.get("school_year", "").strip()
    active = 1 if request.form.get("active") == "1" else 0
    if not code or not name:
        flash("Subject code and name are required.", "error")
        return redirect(url_for("nextgen.workspace"))
    conn = connect()
    try:
        conn.execute("UPDATE subjects SET code=?,name=?,term=?,school_year=?,active=? WHERE id=?", (code,name,term,school_year,active,subject_id))
        conn.commit(); flash(f"Subject {code} updated.", "success")
    except Exception as exc:
        conn.rollback(); flash(f"Could not update subject: {exc}", "error")
    finally:
        conn.close()
    return redirect(url_for("nextgen.workspace"))


@bp.post("/admin/workspace/instructor/add")
@owner_required
def instructor_add():
    require_csrf()
    username = request.form.get("username", "").strip()
    display_name = request.form.get("display_name", "").strip()
    email = request.form.get("email", "").strip().lower() or None
    password = request.form.get("temporary_password", "")
    subject_id = request.form.get("subject_id", "").strip()
    if len(username) < 3 or len(display_name) < 2 or len(password) < 10:
        flash("Use a username, display name, and a temporary password of at least 10 characters.", "error")
        return redirect(url_for("nextgen.workspace"))
    conn = connect()
    try:
        cur = conn.execute(
            """INSERT INTO admins(username,password_hash,display_name,email,role,active)
               VALUES(?,?,?,?, 'instructor',1) RETURNING id""",
            (username, generate_password_hash(password), display_name, email),
        )
        admin_id = cur.fetchone()[0]
        cur = conn.execute(
            """INSERT INTO instructors(admin_id,display_name,email,active,created_at)
               VALUES(?,?,?,?,?) RETURNING id""",
            (admin_id, display_name, email, 1, iso_now()),
        )
        instructor_id = cur.fetchone()[0]
        if subject_id.isdigit():
            conn.execute(
                """INSERT INTO subject_instructors(subject_id,instructor_id,role) VALUES(?,?,'instructor')
                   ON CONFLICT(subject_id,instructor_id) DO NOTHING""",
                (int(subject_id), instructor_id),
            )
        conn.commit()
        flash(f"Instructor account {username} created.", "success")
    except Exception as exc:
        conn.rollback()
        flash(f"Could not create instructor: {exc}", "error")
    finally:
        conn.close()
    return redirect(url_for("nextgen.workspace"))


@bp.post("/admin/workspace/instructor/<int:instructor_id>/edit")
@owner_required
def instructor_edit(instructor_id):
    require_csrf()
    display_name = request.form.get("display_name", "").strip()
    email = request.form.get("email", "").strip().lower() or None
    active = 1 if request.form.get("active") == "1" else 0
    new_password = request.form.get("new_password", "")
    if len(display_name) < 2:
        flash("Display name is required.", "error")
        return redirect(url_for("nextgen.workspace"))
    if new_password and len(new_password) < 10:
        flash("A replacement password must be at least 10 characters.", "error")
        return redirect(url_for("nextgen.workspace"))
    conn = connect()
    row = conn.execute("SELECT * FROM instructors WHERE id=?", (instructor_id,)).fetchone()
    if not row:
        conn.close(); abort(404)
    try:
        conn.execute("UPDATE instructors SET display_name=?,email=?,active=? WHERE id=?", (display_name,email,active,instructor_id))
        if row["admin_id"]:
            conn.execute("UPDATE admins SET display_name=?,email=?,active=? WHERE id=?", (display_name,email,active,row["admin_id"]))
            if new_password:
                conn.execute("UPDATE admins SET password_hash=? WHERE id=?", (generate_password_hash(new_password),row["admin_id"]))
        conn.commit(); flash("Instructor updated.", "success")
    except Exception as exc:
        conn.rollback(); flash(f"Could not update instructor: {exc}", "error")
    finally:
        try: conn.close()
        except Exception: pass
    return redirect(url_for("nextgen.workspace"))


def _next_custom_slot(conn):
    row = conn.execute("SELECT COALESCE(MAX(slot), 17) AS max_slot FROM batches").fetchone()
    return max(18, int(row["max_slot"] or 17) + 1)


def _ensure_custom_batch(conn, assessment):
    """Create/synchronize the one shared delivery batch used by a custom objective assessment."""
    batch = conn.execute("SELECT * FROM batches WHERE assessment_id=? ORDER BY id LIMIT 1", (assessment["id"],)).fetchone()
    if batch:
        conn.execute(
            """UPDATE batches SET name=?,access_code=?,duration_minutes=?,reveal_score=?,active=?,
                      open_at=?,close_at=?,assessment_type='custom',subject_id=? WHERE id=?""",
            (assessment["title"], assessment["access_code"], assessment["duration_minutes"],
             assessment["reveal_score"], assessment["active"], assessment["start_at"], assessment["end_at"],
             assessment["subject_id"], batch["id"]),
        )
        return conn.execute("SELECT * FROM batches WHERE id=?", (batch["id"],)).fetchone()
    slot = _next_custom_slot(conn)
    cur = conn.execute(
        """INSERT INTO batches(slot,section,batch_label,name,access_code,open_at,close_at,duration_minutes,
                   reveal_score,active,assessment_type,subject_id,assessment_id)
           VALUES(?, 'ALL', 'CUSTOM', ?, ?, ?, ?, ?, ?, ?, 'custom', ?, ?) RETURNING id""",
        (slot, assessment["title"], assessment["access_code"], assessment["start_at"], assessment["end_at"],
         assessment["duration_minutes"], assessment["reveal_score"], assessment["active"],
         assessment["subject_id"], assessment["id"]),
    )
    bid = cur.fetchone()[0]
    return conn.execute("SELECT * FROM batches WHERE id=?", (bid,)).fetchone()


def _normalize_allowed_sections(form):
    valid = ["ZT11", "ZT12", "ZT13", "ZS11"]
    selected = [code for code in valid if form.get(f"section_{code}") == "1"]
    return ",".join(selected)


@bp.post("/admin/workspace/assessment/add")
@admin_required
def assessment_add():
    """Create either a free-form objective assessment or a Programming Lab.

    Objective assessments deliberately do not inherit the old Midterm/Post-test 40+20 template.
    Their length is defined entirely by the active questions placed in their builder.
    """
    require_csrf()
    subject_id = request.form.get("subject_id", "")
    title = request.form.get("title", "").strip()
    requested_type = request.form.get("assessment_type", "custom").strip().lower()
    display_type = request.form.get("display_type", "").strip()[:40]
    description = request.form.get("description", "").strip()
    try:
        duration = max(1, min(480, int(request.form.get("duration_minutes", "30") or 30)))
    except ValueError:
        duration = 30
    security_mode = request.form.get("security_mode", "strict").strip().lower()
    if security_mode not in {"standard", "strict", "practice"}:
        security_mode = "strict"
    if not subject_id.isdigit() or not title:
        flash("Choose a subject and enter an assessment title.", "error")
        return redirect(url_for("admin_dashboard"))

    is_lab = requested_type == "programming_lab"
    assessment_type = "programming_lab" if is_lab else "custom"
    if not display_type:
        display_type = "Programming Lab" if is_lab else "Custom Assessment"
    allowed_sections = _normalize_allowed_sections(request.form)
    reveal_score = 1 if request.form.get("reveal_score") == "1" else 0
    shuffle_questions = 1 if request.form.get("shuffle_questions") == "1" else 0
    shuffle_options = 1 if request.form.get("shuffle_options") == "1" else 0

    conn = connect()
    assessment_id = None
    try:
        instructor = _current_instructor(conn)
        base_slug = _slugify(title)
        slug = base_slug
        n = 2
        while conn.execute("SELECT 1 FROM assessments WHERE slug=?", (slug,)).fetchone():
            slug = f"{base_slug}-{n}"
            n += 1
        access = _make_access_code("CPP" if is_lab else "TEST")
        cur = conn.execute(
            """INSERT INTO assessments(subject_id,title,slug,assessment_type,display_type,description,duration_minutes,
                       access_code,max_attempts,security_mode,reveal_score,shuffle_questions,shuffle_options,
                       allowed_sections,question_limit,active,created_by_instructor_id,created_at)
               VALUES(?,?,?,?,?,?,?,?,1,?,?,?,?,?,0,1,?,?) RETURNING id""",
            (int(subject_id), title, slug, assessment_type, display_type, description, duration, access,
             security_mode, reveal_score, shuffle_questions, shuffle_options, allowed_sections,
             instructor["id"] if instructor else None, iso_now()),
        )
        assessment_id = cur.fetchone()[0]
        if is_lab:
            conn.execute(
                """INSERT INTO programming_labs(assessment_id,language,title,instructions,starter_code,
                           allow_custom_input,active,created_at)
                   VALUES(?, 'cpp', ?, ?, '#include <iostream>\nusing namespace std;\n\nint main() {\n    return 0;\n}\n',1,1,?)""",
                (assessment_id, title, description or "Complete the programming tasks below.", iso_now()),
            )
        else:
            assessment = conn.execute("SELECT * FROM assessments WHERE id=?", (assessment_id,)).fetchone()
            _ensure_custom_batch(conn, assessment)
        conn.commit()
        flash(f"{display_type} created. Session key: {access}", "success")
    except Exception as exc:
        conn.rollback()
        flash(f"Could not create assessment: {exc}", "error")
    finally:
        conn.close()
    if assessment_id and not is_lab:
        return redirect(url_for("nextgen.custom_assessment", assessment_id=assessment_id))
    if assessment_id and is_lab:
        return redirect(url_for("nextgen.admin_ide"))
    return redirect(url_for("admin_dashboard"))


@bp.post("/admin/workspace/assessment/<int:assessment_id>/edit")
@admin_required
def assessment_edit(assessment_id):
    require_csrf()
    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    try:
        duration = max(1, min(480, int(request.form.get("duration_minutes", "60") or 60)))
    except ValueError:
        duration = 60
    security_mode = request.form.get("security_mode", "standard").strip().lower()
    active = 1 if request.form.get("active") == "1" else 0
    access_code = request.form.get("access_code", "").strip().upper() or None
    if not title:
        flash("Assessment title is required.", "error")
        return redirect(url_for("nextgen.workspace"))
    conn = connect()
    row = conn.execute("SELECT * FROM assessments WHERE id=?", (assessment_id,)).fetchone()
    if not row:
        conn.close(); abort(404)
    if row["assessment_type"] == "custom" and not access_code:
        access_code = row["access_code"] or _make_access_code("TEST")
    if row["assessment_type"] == "dryrun" and not access_code:
        delivery = conn.execute("SELECT access_code FROM batches WHERE assessment_id=? ORDER BY id LIMIT 1", (assessment_id,)).fetchone()
        access_code = row["access_code"] or (delivery["access_code"] if delivery else None) or _make_access_code("DRY")
    try:
        conn.execute("UPDATE assessments SET title=?,description=?,duration_minutes=?,security_mode=?,active=?,access_code=? WHERE id=?", (title,description,duration,security_mode,active,access_code,assessment_id))
        if row["assessment_type"] == "programming_lab":
            conn.execute("UPDATE programming_labs SET title=?,active=? WHERE assessment_id=?", (title,active,assessment_id))
        elif row["assessment_type"] == "custom":
            updated = conn.execute("SELECT * FROM assessments WHERE id=?", (assessment_id,)).fetchone()
            _ensure_custom_batch(conn, updated)
        elif row["assessment_type"] == "dryrun":
            conn.execute(
                "UPDATE batches SET name=?,access_code=?,duration_minutes=?,active=? WHERE assessment_id=?",
                (title, access_code, duration, active, assessment_id),
            )
        conn.commit(); flash("Assessment updated.", "success")
    except Exception as exc:
        conn.rollback(); flash(f"Could not update assessment: {exc}", "error")
    finally:
        try: conn.close()
        except Exception: pass
    if row["assessment_type"] == "custom":
        return redirect(url_for("nextgen.custom_assessment", assessment_id=assessment_id))
    return redirect(url_for("nextgen.workspace"))



@bp.post("/admin/workspace/assessment/<int:assessment_id>/delete")
@admin_required
def assessment_delete(assessment_id):
    """Soft-delete an assessment while preserving historical attempts and analytics data."""
    require_csrf()
    conn = connect()
    row = conn.execute("SELECT * FROM assessments WHERE id=? AND deleted_at IS NULL", (assessment_id,)).fetchone()
    if not row:
        conn.close(); abort(404)
    try:
        now = iso_now()
        conn.execute("UPDATE assessments SET active=0, deleted_at=? WHERE id=?", (now, assessment_id))
        conn.execute("UPDATE batches SET active=0 WHERE assessment_id=?", (assessment_id,))
        if row["assessment_type"] == "programming_lab":
            conn.execute("UPDATE programming_labs SET active=0 WHERE assessment_id=?", (assessment_id,))
        conn.commit()
        flash(f"{row['title']} was removed from active Custos assessments. Historical attempts were preserved.", "success")
    except Exception as exc:
        conn.rollback(); flash(f"Could not delete assessment: {exc}", "error")
    finally:
        conn.close()
    return redirect(url_for("admin_dashboard"))

def _custom_assessment_or_404(conn, assessment_id):
    row = conn.execute(
        """SELECT a.*,s.code AS subject_code,s.name AS subject_name
           FROM assessments a JOIN subjects s ON s.id=a.subject_id WHERE a.id=? AND a.deleted_at IS NULL""",
        (assessment_id,),
    ).fetchone()
    if not row or row["assessment_type"] != "custom":
        abort(404)
    return row


@bp.route("/admin/assessment/<int:assessment_id>")
@admin_required
def custom_assessment(assessment_id):
    conn = connect()
    assessment = _custom_assessment_or_404(conn, assessment_id)
    batch = _ensure_custom_batch(conn, assessment)
    conn.commit()
    questions = conn.execute(
        """SELECT * FROM questions WHERE assessment_id=? ORDER BY COALESCE(position,id),id""",
        (assessment_id,),
    ).fetchall()
    summary = conn.execute(
        """SELECT COUNT(*) AS attempts,
                  SUM(CASE WHEN status='submitted' THEN 1 ELSE 0 END) AS submitted,
                  AVG(CASE WHEN status='submitted' THEN auto_total END) AS avg_score
           FROM exam_sessions WHERE assessment_id=? AND COALESCE(is_test,0)=0""",
        (assessment_id,),
    ).fetchone()
    sessions = conn.execute(
        """SELECT * FROM exam_sessions WHERE assessment_id=? AND COALESCE(is_test,0)=0 ORDER BY id DESC LIMIT 50""",
        (assessment_id,),
    ).fetchall()
    active_questions = [q for q in questions if q["active"]]
    max_score = sum(int(q["points"] or 1) for q in active_questions)
    conn.close()
    from google_integration import rosters_for_assessment
    from app import STUDENT_SECTIONS

    conn = connect()
    rosters = rosters_for_assessment(conn, assessment_id)
    conn.close()
    return render_template(
        "admin_custom_assessment.html", assessment=assessment, batch=batch, questions=questions,
        summary=summary, sessions=sessions, active_count=len(active_questions), max_score=max_score,
        assessment_label=assessment["display_type"] or "Custom Assessment",
        rosters=rosters, student_sections={k: sorted(v) for k, v in STUDENT_SECTIONS.items()},
    )


@bp.post("/admin/assessment/<int:assessment_id>/settings")
@admin_required
def custom_assessment_settings(assessment_id):
    require_csrf()
    conn = connect()
    assessment = _custom_assessment_or_404(conn, assessment_id)
    title = request.form.get("title", "").strip()
    display_type = request.form.get("display_type", "Custom Assessment").strip()[:40] or "Custom Assessment"
    description = request.form.get("description", "").strip()
    try:
        duration = max(1, min(480, int(request.form.get("duration_minutes", "30") or 30)))
        question_limit = max(0, min(500, int(request.form.get("question_limit", "0") or 0)))
    except ValueError:
        conn.close(); flash("Duration and question limit must be numbers.", "error")
        return redirect(url_for("nextgen.custom_assessment", assessment_id=assessment_id))
    security_mode = request.form.get("security_mode", "strict")
    if security_mode not in {"standard", "strict", "practice"}: security_mode = "strict"
    reveal_score = 1 if request.form.get("reveal_score") == "1" else 0
    shuffle_questions = 1 if request.form.get("shuffle_questions") == "1" else 0
    shuffle_options = 1 if request.form.get("shuffle_options") == "1" else 0
    active = 1 if request.form.get("active") == "1" else 0
    allowed_sections = _normalize_allowed_sections(request.form)
    start_at = request.form.get("start_at", "").strip() or None
    end_at = request.form.get("end_at", "").strip() or None
    if not title:
        conn.close(); flash("Assessment title is required.", "error")
        return redirect(url_for("nextgen.custom_assessment", assessment_id=assessment_id))
    try:
        conn.execute(
            """UPDATE assessments SET title=?,display_type=?,description=?,duration_minutes=?,security_mode=?,
                      reveal_score=?,shuffle_questions=?,shuffle_options=?,allowed_sections=?,question_limit=?,
                      start_at=?,end_at=?,active=? WHERE id=?""",
            (title, display_type, description, duration, security_mode, reveal_score, shuffle_questions,
             shuffle_options, allowed_sections, question_limit, start_at, end_at, active, assessment_id),
        )
        updated = conn.execute("SELECT * FROM assessments WHERE id=?", (assessment_id,)).fetchone()
        _ensure_custom_batch(conn, updated)
        conn.commit(); flash("Assessment settings saved.", "success")
    except Exception as exc:
        conn.rollback(); flash(f"Could not save assessment settings: {exc}", "error")
    finally:
        conn.close()
    return redirect(url_for("nextgen.custom_assessment", assessment_id=assessment_id))


@bp.post("/admin/assessment/<int:assessment_id>/regenerate-key")
@admin_required
def custom_assessment_regenerate_key(assessment_id):
    require_csrf()
    conn = connect(); assessment = _custom_assessment_or_404(conn, assessment_id)
    try:
        access = _make_access_code("TEST")
        while conn.execute("SELECT 1 FROM assessments WHERE access_code=?", (access,)).fetchone():
            access = _make_access_code("TEST")
        conn.execute("UPDATE assessments SET access_code=? WHERE id=?", (access, assessment_id))
        updated = conn.execute("SELECT * FROM assessments WHERE id=?", (assessment_id,)).fetchone()
        _ensure_custom_batch(conn, updated)
        conn.commit(); flash(f"New session key generated: {access}", "success")
    except Exception as exc:
        conn.rollback(); flash(f"Could not regenerate key: {exc}", "error")
    finally: conn.close()
    return redirect(url_for("nextgen.custom_assessment", assessment_id=assessment_id))


def _custom_question_values(form):
    topic = re.sub(r"\s+", " ", form.get("topic", "General").strip())[:120] or "General"
    prompt = form.get("prompt", "").strip()[:2000]
    code = form.get("code", "").rstrip()[:8000]
    options = {letter: form.get(f"option_{letter.lower()}", "").strip()[:1200] for letter in "ABCD"}
    correct = form.get("correct_option", "").strip().upper()
    explanation = form.get("explanation", "").strip()[:2500]
    try: points = max(1, min(100, int(form.get("points", "1") or 1)))
    except ValueError: points = 1
    if not prompt or any(not value for value in options.values()):
        raise ValueError("Question and all four answer choices are required.")
    if len({value.casefold() for value in options.values()}) != 4:
        raise ValueError("All four answer choices must be different.")
    if correct not in {"A", "B", "C", "D"}:
        raise ValueError("Choose the correct answer.")
    return topic,prompt,code,options,correct,explanation,points


@bp.post("/admin/assessment/<int:assessment_id>/question/add")
@admin_required
def custom_question_add(assessment_id):
    require_csrf(); conn=connect(); assessment=_custom_assessment_or_404(conn,assessment_id)
    try:
        topic,prompt,code,options,correct,explanation,points=_custom_question_values(request.form)
        batch=_ensure_custom_batch(conn,assessment)
        row=conn.execute("SELECT COALESCE(MAX(position),0)+1 AS next_pos FROM questions WHERE assessment_id=?",(assessment_id,)).fetchone()
        position=int(row["next_pos"] or 1)
        conn.execute(
            """INSERT INTO questions(part,batch_slot,topic,prompt,code,option_a,option_b,option_c,option_d,
                       correct_option,explanation,points,position,active,created_by,subject_id,assessment_id)
               VALUES(1,?,?,?,?,?,?,?,?,?,?,?,?,1,'instructor',?,?)""",
            (batch["slot"],topic,prompt,code,options["A"],options["B"],options["C"],options["D"],correct,
             explanation,points,position,assessment["subject_id"],assessment_id),
        )
        conn.commit(); flash("Question added.","success")
    except Exception as exc:
        conn.rollback(); flash(f"Could not add question: {exc}","error")
    finally: conn.close()
    return redirect(url_for("nextgen.custom_assessment",assessment_id=assessment_id))


@bp.post("/admin/assessment/<int:assessment_id>/question/<int:question_id>/edit")
@admin_required
def custom_question_edit(assessment_id,question_id):
    require_csrf(); conn=connect(); _custom_assessment_or_404(conn,assessment_id)
    row=conn.execute("SELECT * FROM questions WHERE id=? AND assessment_id=?",(question_id,assessment_id)).fetchone()
    if not row: conn.close(); abort(404)
    try:
        topic,prompt,code,options,correct,explanation,points=_custom_question_values(request.form)
        active=1 if request.form.get("active")=="1" else 0
        conn.execute(
            """UPDATE questions SET topic=?,prompt=?,code=?,option_a=?,option_b=?,option_c=?,option_d=?,
                      correct_option=?,explanation=?,points=?,active=? WHERE id=?""",
            (topic,prompt,code,options["A"],options["B"],options["C"],options["D"],correct,explanation,points,active,question_id),
        )
        conn.commit(); flash("Question updated.","success")
    except Exception as exc:
        conn.rollback(); flash(f"Could not update question: {exc}","error")
    finally: conn.close()
    return redirect(url_for("nextgen.custom_assessment",assessment_id=assessment_id))


@bp.post("/admin/assessment/<int:assessment_id>/question/<int:question_id>/delete")
@admin_required
def custom_question_delete(assessment_id,question_id):
    require_csrf(); conn=connect(); _custom_assessment_or_404(conn,assessment_id)
    used=conn.execute("SELECT 1 FROM session_questions WHERE question_id=? LIMIT 1",(question_id,)).fetchone()
    if used:
        conn.execute("UPDATE questions SET active=0 WHERE id=? AND assessment_id=?",(question_id,assessment_id))
        conn.commit(); flash("Question has attempt history, so it was disabled instead of deleted.","success")
    else:
        conn.execute("DELETE FROM questions WHERE id=? AND assessment_id=?",(question_id,assessment_id)); conn.commit(); flash("Question deleted.","success")
    conn.close(); return redirect(url_for("nextgen.custom_assessment",assessment_id=assessment_id))


@bp.post("/admin/assessment/<int:assessment_id>/questions/import")
@admin_required
def custom_questions_import(assessment_id):
    require_csrf(); conn=connect(); assessment=_custom_assessment_or_404(conn,assessment_id)
    upload=request.files.get("question_csv")
    if not upload or not upload.filename:
        conn.close(); flash("Choose a CSV file first.","error"); return redirect(url_for("nextgen.custom_assessment",assessment_id=assessment_id))
    try:
        raw=upload.read().decode("utf-8-sig")
        reader=csv.DictReader(io.StringIO(raw))
        required={"prompt","option_a","option_b","option_c","option_d","correct_option"}
        if not reader.fieldnames:
            raise ValueError("The CSV is missing a header row.")
        reader.fieldnames=[str(h or "").strip() for h in reader.fieldnames]
        if not required.issubset(set(reader.fieldnames)):
            raise ValueError("CSV needs prompt, option_a, option_b, option_c, option_d, and correct_option columns.")
        rows=list(reader)
        if not rows: raise ValueError("The CSV contains no questions.")
        if len(rows)>500: raise ValueError("A single import is limited to 500 questions.")
        replace_existing=request.form.get("replace_existing")=="1"
        existing_sessions=conn.execute("SELECT 1 FROM exam_sessions WHERE assessment_id=? LIMIT 1",(assessment_id,)).fetchone()
        if replace_existing and existing_sessions:
            raise ValueError("Existing questions cannot be replaced after student attempts exist. Import as additional questions instead.")
        if replace_existing:
            conn.execute("DELETE FROM questions WHERE assessment_id=?",(assessment_id,))
        batch=_ensure_custom_batch(conn,assessment)
        start=conn.execute("SELECT COALESCE(MAX(position),0) AS max_pos FROM questions WHERE assessment_id=?",(assessment_id,)).fetchone()["max_pos"] or 0
        imported=0
        for offset,row in enumerate(rows,1):
            form={k:(v or "") for k,v in row.items()}
            topic=re.sub(r"\s+"," ",form.get("topic","General").strip())[:120] or "General"
            prompt=form.get("prompt","").strip()[:2000]
            code=form.get("code","").rstrip()[:8000]
            options={L:form.get(f"option_{L.lower()}","").strip()[:1200] for L in "ABCD"}
            correct=form.get("correct_option","").strip().upper()
            explanation=form.get("explanation","").strip()[:2500]
            try: points=max(1,min(100,int(form.get("points","1") or 1)))
            except ValueError: points=1
            if not prompt or any(not v for v in options.values()) or len({v.casefold() for v in options.values()})!=4 or correct not in {"A","B","C","D"}:
                raise ValueError(f"Row {offset+1}: invalid prompt, choices, or answer key.")
            try: position=int(form.get("item_number","") or (start+offset))
            except ValueError: position=start+offset
            conn.execute(
                """INSERT INTO questions(part,batch_slot,topic,prompt,code,option_a,option_b,option_c,option_d,
                           correct_option,explanation,points,position,active,created_by,subject_id,assessment_id)
                   VALUES(1,?,?,?,?,?,?,?,?,?,?,?,?,1,'csv-import',?,?)""",
                (batch["slot"],topic,prompt,code,options["A"],options["B"],options["C"],options["D"],correct,
                 explanation,points,position,assessment["subject_id"],assessment_id),
            )
            imported+=1
        conn.commit(); flash(f"Imported {imported} questions.","success")
    except Exception as exc:
        conn.rollback(); flash(f"Could not import questions: {exc}","error")
    finally: conn.close()
    return redirect(url_for("nextgen.custom_assessment",assessment_id=assessment_id))


@bp.route("/admin/ide")
@admin_required
def admin_ide():
    conn = connect()
    labs = conn.execute(
        """SELECT pl.*, a.title AS assessment_title, a.access_code, a.duration_minutes, a.active AS assessment_active,
                  s.code AS subject_code,
                  (SELECT COUNT(*) FROM programming_tasks pt WHERE pt.lab_id=pl.id AND pt.active=1) AS task_count,
                  (SELECT COUNT(*) FROM coding_sessions cs WHERE cs.lab_id=pl.id AND cs.status='in_progress') AS active_sessions
           FROM programming_labs pl JOIN assessments a ON a.id=pl.assessment_id
           JOIN subjects s ON s.id=a.subject_id ORDER BY s.code, a.title"""
    ).fetchall()
    sessions = conn.execute(
        """SELECT cs.*, pl.title AS lab_title, a.title AS assessment_title,
                  (SELECT COUNT(*) FROM coding_events ce WHERE ce.session_id=cs.id AND ce.event_type='security_violation') AS security_events
           FROM coding_sessions cs JOIN programming_labs pl ON pl.id=cs.lab_id
           JOIN assessments a ON a.id=pl.assessment_id ORDER BY cs.id DESC LIMIT 50"""
    ).fetchall()
    conn.close()
    return render_template("admin_ide.html", labs=labs, sessions=sessions, runner=runner_status())


@bp.route("/admin/ide/lab/<int:lab_id>", methods=["GET", "POST"])
@admin_required
def admin_ide_lab(lab_id):
    conn = connect()
    lab = conn.execute(
        """SELECT pl.*, a.title AS assessment_title, a.access_code, a.duration_minutes, a.id AS assessment_id,
                  s.code AS subject_code FROM programming_labs pl
           JOIN assessments a ON a.id=pl.assessment_id JOIN subjects s ON s.id=a.subject_id WHERE pl.id=?""",
        (lab_id,),
    ).fetchone()
    if not lab:
        conn.close(); abort(404)
    if request.method == "POST":
        require_csrf()
        title = request.form.get("title", "").strip()
        instructions = request.form.get("instructions", "").strip()
        duration = max(1, min(480, int(request.form.get("duration_minutes", "90") or 90)))
        access_code = request.form.get("access_code", "").strip().upper()
        conn.execute("UPDATE programming_labs SET title=?, instructions=? WHERE id=?", (title, instructions, lab_id))
        conn.execute("UPDATE assessments SET title=?,duration_minutes=?,access_code=? WHERE id=?", (title, duration, access_code, lab["assessment_id"]))
        conn.commit()
        flash("Programming Lab updated.", "success")
        lab = conn.execute(
            """SELECT pl.*, a.title AS assessment_title, a.access_code, a.duration_minutes, a.id AS assessment_id,
                      s.code AS subject_code FROM programming_labs pl
               JOIN assessments a ON a.id=pl.assessment_id JOIN subjects s ON s.id=a.subject_id WHERE pl.id=?""",
            (lab_id,),
        ).fetchone()
    tasks = conn.execute("SELECT * FROM programming_tasks WHERE lab_id=? ORDER BY position,id", (lab_id,)).fetchall()
    conn.close()
    return render_template("admin_ide_lab.html", lab=lab, tasks=tasks, runner=runner_status())


@bp.post("/admin/ide/lab/<int:lab_id>/task/add")
@admin_required
def admin_ide_task_add(lab_id):
    require_csrf()
    title = request.form.get("title", "").strip()
    prompt = request.form.get("prompt", "").strip()
    starter = request.form.get("starter_code", "")
    points = float(request.form.get("points", "10") or 10)
    tests_text = request.form.get("hidden_tests_json", "[]").strip() or "[]"
    try:
        tests = json.loads(tests_text)
        if not isinstance(tests, list) or any(not isinstance(x, dict) or "expected" not in x for x in tests):
            raise ValueError
    except Exception:
        flash('Hidden tests must be JSON such as [{"stdin":"2 3\\n","expected":"5"}].', "error")
        return redirect(url_for("nextgen.admin_ide_lab", lab_id=lab_id))
    conn = connect()
    position = conn.execute("SELECT COALESCE(MAX(position),0)+1 FROM programming_tasks WHERE lab_id=?", (lab_id,)).fetchone()[0]
    conn.execute(
        """INSERT INTO programming_tasks(lab_id,position,title,prompt,starter_code,points,hidden_tests_json,active)
           VALUES(?,?,?,?,?,?,?,1)""",
        (lab_id, position, title, prompt, starter, points, json.dumps(tests)),
    )
    conn.commit(); conn.close()
    flash("Programming task added.", "success")
    return redirect(url_for("nextgen.admin_ide_lab", lab_id=lab_id))


@bp.post("/admin/ide/task/<int:task_id>/edit")
@admin_required
def admin_ide_task_edit(task_id):
    require_csrf()
    conn = connect()
    task = conn.execute("SELECT * FROM programming_tasks WHERE id=?", (task_id,)).fetchone()
    if not task:
        conn.close(); abort(404)
    tests_text = request.form.get("hidden_tests_json", "[]").strip() or "[]"
    try:
        tests = json.loads(tests_text)
        if not isinstance(tests, list): raise ValueError
    except Exception:
        conn.close(); flash("Hidden tests JSON is invalid.", "error")
        return redirect(url_for("nextgen.admin_ide_lab", lab_id=task["lab_id"]))
    conn.execute(
        """UPDATE programming_tasks SET title=?,prompt=?,starter_code=?,points=?,hidden_tests_json=?,active=? WHERE id=?""",
        (request.form.get("title", "").strip(), request.form.get("prompt", "").strip(),
         request.form.get("starter_code", ""), float(request.form.get("points", "10") or 10),
         json.dumps(tests), 1 if request.form.get("active") == "1" else 0, task_id),
    )
    conn.commit(); conn.close(); flash("Task updated.", "success")
    return redirect(url_for("nextgen.admin_ide_lab", lab_id=task["lab_id"]))


@bp.post("/admin/ide/session/<int:sid>/unlock")
@admin_required
def admin_ide_unlock(sid):
    require_csrf()
    conn = connect()
    conn.execute("UPDATE coding_sessions SET security_locked=0,temp_locked_until=NULL,pending_blackout=0 WHERE id=?", (sid,))
    _coding_log(conn, sid, "security_unlocked", f"Unlocked by instructor admin #{session.get('admin_id')}")
    conn.commit(); conn.close()
    flash("Coding session unlocked.", "success")
    return redirect(url_for("nextgen.admin_ide_session", sid=sid))


@bp.route("/admin/ide/session/<int:sid>")
@admin_required
def admin_ide_session(sid):
    conn = connect()
    cs = _load_coding_session(conn, sid)
    if not cs:
        conn.close(); abort(404)
    progress = conn.execute(
        """SELECT ctp.*, pt.position,pt.title,pt.points FROM coding_task_progress ctp
           JOIN programming_tasks pt ON pt.id=ctp.task_id WHERE ctp.session_id=? ORDER BY pt.position""",
        (sid,),
    ).fetchall()
    events = conn.execute("SELECT * FROM coding_events WHERE session_id=? ORDER BY id DESC LIMIT 100", (sid,)).fetchall()
    submissions = conn.execute("SELECT * FROM coding_submissions WHERE session_id=? ORDER BY id DESC LIMIT 100", (sid,)).fetchall()
    conn.close()
    return render_template("admin_ide_session.html", cs=cs, progress=progress, events=events, submissions=submissions)


@bp.post("/admin/ide/preview/<int:lab_id>")
@admin_required
def admin_ide_preview(lab_id):
    require_csrf()
    conn = connect()
    lab = conn.execute("SELECT * FROM programming_labs WHERE id=?", (lab_id,)).fetchone()
    if not lab:
        conn.close(); abort(404)
    email = "custos.ide.preview@test.only"
    existing = conn.execute("SELECT * FROM coding_sessions WHERE email=? AND lab_id=?", (email, lab_id)).fetchone()
    if existing:
        sid = existing["id"]
        conn.execute("UPDATE coding_sessions SET status='in_progress',security_locked=0,temp_locked_until=NULL,pending_blackout=0,is_test=1 WHERE id=?", (sid,))
    else:
        cur = conn.execute(
            """INSERT INTO coding_sessions(lab_id,email,first_name,last_name,student_name,program,class_section,started_at,status,
                       terms_accepted_at,is_test,ip_address,user_agent) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id""",
            (lab_id,email,"Instructor","Preview","Instructor IDE Preview","TEST","PREVIEW",iso_now(),"in_progress",iso_now(),1,request.remote_addr,request.headers.get("User-Agent", "")[:500]),
        )
        sid = cur.fetchone()[0]
        _seed_progress(conn, sid, lab_id)
    conn.commit(); conn.close()
    session["coding_session_id"] = sid
    return redirect(url_for("nextgen.ide_workspace"))


def _seed_progress(conn, sid, lab_id):
    tasks = conn.execute("SELECT * FROM programming_tasks WHERE lab_id=? AND active=1 ORDER BY position,id", (lab_id,)).fetchall()
    for task in tasks:
        source = task["starter_code"] or ""
        conn.execute(
            """INSERT INTO coding_task_progress(session_id,task_id,source_code,last_saved_at)
               VALUES(?,?,?,?) ON CONFLICT(session_id,task_id) DO NOTHING""",
            (sid, task["id"], source, iso_now()),
        )
    if tasks:
        conn.execute("UPDATE coding_sessions SET current_task_id=COALESCE(current_task_id,?) WHERE id=?", (tasks[0]["id"], sid))


@bp.get("/ide/coming-soon")
def ide_coming_soon():
    return render_template("ide_coming_soon.html")


@bp.route("/ide", methods=["GET", "POST"])
def ide_login():
    if not STUDENT_IDE_ENABLED and not session.get("admin_id"):
        return redirect(url_for("nextgen.ide_coming_soon"))
    if request.method == "POST":
        require_csrf()
        identity, error = _identity(request.form)
        if error:
            flash(error, "error"); return render_template("ide_login.html", domain=ALLOWED_EMAIL_DOMAIN)
        first_name, last_name, name, program, class_section, email = identity
        key = request.form.get("session_key", "").strip().upper()
        conn = connect()
        row = conn.execute(
            """SELECT a.*,pl.id AS lab_id,pl.title AS lab_title,s.code AS subject_code
               FROM assessments a JOIN programming_labs pl ON pl.assessment_id=a.id
               JOIN subjects s ON s.id=a.subject_id
               WHERE a.access_code=? AND a.active=1 AND pl.active=1""",
            (key,),
        ).fetchone()
        if not row:
            conn.close(); flash("Invalid Programming Lab session key.", "error")
            return render_template("ide_login.html", domain=ALLOWED_EMAIL_DOMAIN)
        start = parse_iso(row["start_at"]); end = parse_iso(row["end_at"]); now = datetime.now(APP_TZ)
        if start and now < start:
            conn.close(); flash("This Programming Lab is not open yet.", "error"); return render_template("ide_login.html", domain=ALLOWED_EMAIL_DOMAIN)
        if end and now > end:
            conn.close(); flash("This Programming Lab has closed.", "error"); return render_template("ide_login.html", domain=ALLOWED_EMAIL_DOMAIN)
        existing = conn.execute("SELECT * FROM coding_sessions WHERE email=? AND lab_id=?", (email,row["lab_id"])).fetchone()
        if existing and existing["status"] == "submitted":
            session["coding_session_id"] = existing["id"]
            conn.close(); return redirect(url_for("nextgen.ide_result"))
        if existing and existing["terms_accepted_at"]:
            conn.execute("UPDATE coding_sessions SET first_name=?,last_name=?,student_name=?,program=?,class_section=? WHERE id=?", (first_name,last_name,name,program,class_section,existing["id"]))
            conn.commit(); session["coding_session_id"] = existing["id"]; conn.close()
            return redirect(url_for("nextgen.ide_workspace"))
        session["pending_ide"] = {"first_name":first_name,"last_name":last_name,"student_name":name,"program":program,"class_section":class_section,"email":email,"lab_id":row["lab_id"],"access_code":key}
        conn.close(); return redirect(url_for("nextgen.ide_instructions"))
    return render_template("ide_login.html", domain=ALLOWED_EMAIL_DOMAIN)


@bp.get("/ide/instructions")
def ide_instructions():
    if not STUDENT_IDE_ENABLED and not session.get("admin_id"):
        return redirect(url_for("nextgen.ide_coming_soon"))
    pending = session.get("pending_ide")
    if not pending: return redirect(url_for("nextgen.ide_login"))
    conn = connect()
    lab = conn.execute(
        """SELECT pl.*,a.title AS assessment_title,a.duration_minutes,s.code AS subject_code,s.name AS subject_name
           FROM programming_labs pl JOIN assessments a ON a.id=pl.assessment_id
           JOIN subjects s ON s.id=a.subject_id WHERE pl.id=?""", (pending["lab_id"],)
    ).fetchone()
    conn.close()
    if not lab: return redirect(url_for("nextgen.ide_login"))
    return render_template("ide_instructions.html", lab=lab, pending=pending)


@bp.post("/ide/start")
def ide_start():
    if not STUDENT_IDE_ENABLED and not session.get("admin_id"):
        return redirect(url_for("nextgen.ide_coming_soon"))
    require_csrf()
    pending = session.get("pending_ide")
    if not pending or request.form.get("terms_accept") != "yes":
        flash("Accept the secure Programming Lab terms to continue.", "error")
        return redirect(url_for("nextgen.ide_instructions"))
    conn = connect()
    lab = conn.execute("SELECT * FROM programming_labs WHERE id=? AND active=1", (pending["lab_id"],)).fetchone()
    if not lab:
        conn.close(); return redirect(url_for("nextgen.ide_login"))
    existing = conn.execute("SELECT * FROM coding_sessions WHERE email=? AND lab_id=?", (pending["email"], lab["id"])).fetchone()
    if existing:
        sid = existing["id"]
        conn.execute("UPDATE coding_sessions SET terms_accepted_at=COALESCE(terms_accepted_at,?) WHERE id=?", (iso_now(),sid))
    else:
        cur = conn.execute(
            """INSERT INTO coding_sessions(lab_id,email,first_name,last_name,student_name,program,class_section,started_at,terms_accepted_at,
                       ip_address,user_agent) VALUES(?,?,?,?,?,?,?,?,?,?,?) RETURNING id""",
            (lab["id"],pending["email"],pending["first_name"],pending["last_name"],pending["student_name"],pending["program"],pending["class_section"],
             iso_now(),iso_now(),request.remote_addr,request.headers.get("User-Agent", "")[:500]),
        )
        sid = cur.fetchone()[0]
        _seed_progress(conn,sid,lab["id"])
        _coding_log(conn,sid,"lab_started","Student started the secure Programming Lab")
    conn.commit(); conn.close()
    session.pop("pending_ide",None); session["coding_session_id"] = sid
    return redirect(url_for("nextgen.ide_workspace"))


@bp.get("/ide/workspace")
@ide_session_required
def ide_workspace():
    sid = session["coding_session_id"]
    conn = connect(); cs = _load_coding_session(conn,sid)
    if not cs:
        conn.close(); session.pop("coding_session_id",None); return redirect(url_for("nextgen.ide_login"))
    if cs["status"] == "submitted":
        conn.close(); return redirect(url_for("nextgen.ide_result"))
    remaining = _coding_remaining(cs)
    if remaining is not None and remaining <= 0:
        conn.execute("UPDATE coding_sessions SET status='submitted',submitted_at=? WHERE id=?", (iso_now(),sid)); conn.commit(); conn.close()
        return redirect(url_for("nextgen.ide_result"))
    rows = conn.execute(
        """SELECT pt.*,ctp.source_code,ctp.stdin_text,ctp.last_output,ctp.last_status,ctp.run_count,ctp.score,ctp.submitted_at AS task_submitted_at
           FROM programming_tasks pt JOIN coding_task_progress ctp ON ctp.task_id=pt.id
           WHERE ctp.session_id=? AND pt.active=1 ORDER BY pt.position,pt.id""", (sid,)
    ).fetchall()
    security = _coding_security_state(cs); conn.close()
    return render_template("ide_workspace.html", cs=cs, tasks=rows, security=security, remaining=remaining, runner=runner_status())


@bp.post("/api/ide/save")
@ide_session_required
def ide_save():
    require_csrf(); sid=session["coding_session_id"]
    data=request.get_json(silent=True) or {}; task_id=int(data.get("task_id") or 0)
    source=str(data.get("source_code") or "")[:50000]; stdin=str(data.get("stdin_text") or "")[:10000]
    conn=connect(); cs=_load_coding_session(conn,sid)
    if not cs: conn.close(); return jsonify(ok=False),404
    blocked,state=_coding_blocked(cs)
    if blocked: conn.close(); return jsonify(ok=False,locked=True,**state),423
    row=conn.execute("SELECT 1 FROM coding_task_progress WHERE session_id=? AND task_id=?",(sid,task_id)).fetchone()
    if not row: conn.close(); return jsonify(ok=False,error="Task not assigned"),404
    conn.execute("UPDATE coding_task_progress SET source_code=?,stdin_text=?,last_saved_at=? WHERE session_id=? AND task_id=?",(source,stdin,iso_now(),sid,task_id))
    conn.execute("UPDATE coding_sessions SET current_task_id=? WHERE id=?",(task_id,sid)); conn.commit(); conn.close()
    return jsonify(ok=True,saved_at=iso_now())


@bp.post("/api/ide/run")
@ide_session_required
def ide_run():
    require_csrf(); sid=session["coding_session_id"]
    data=request.get_json(silent=True) or {}; task_id=int(data.get("task_id") or 0)
    source=str(data.get("source_code") or "")[:50000]; stdin=str(data.get("stdin_text") or "")[:10000]
    conn=connect(); cs=_load_coding_session(conn,sid)
    if not cs: conn.close(); return jsonify(ok=False),404
    blocked,state=_coding_blocked(cs)
    if blocked: conn.close(); return jsonify(ok=False,locked=True,**state),423
    progress=conn.execute("SELECT 1 FROM coding_task_progress WHERE session_id=? AND task_id=?",(sid,task_id)).fetchone()
    if not progress: conn.close(); return jsonify(ok=False,error="Task not assigned"),404
    conn.close()
    result=run_cpp(source,stdin)
    conn=connect()
    combined=result.stdout or result.stderr or result.compile_output
    conn.execute("""UPDATE coding_task_progress SET source_code=?,stdin_text=?,last_output=?,last_status=?,run_count=run_count+1,last_saved_at=? WHERE session_id=? AND task_id=?""",
                 (source,stdin,combined[:20000],result.status,iso_now(),sid,task_id))
    conn.execute("""INSERT INTO coding_submissions(session_id,task_id,source_code,stdin_text,stdout_text,stderr_text,compile_output,status,runtime_ms,created_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?)""",(sid,task_id,source,stdin,result.stdout,result.stderr,result.compile_output,result.status,result.runtime_ms,iso_now()))
    _coding_log(conn,sid,"code_run",f"Task {task_id}: {result.status}")
    conn.commit(); conn.close()
    return jsonify(ok=True,result=result.to_dict())


@bp.post("/api/ide/submit-task")
@ide_session_required
def ide_submit_task():
    require_csrf(); sid=session["coding_session_id"]
    data=request.get_json(silent=True) or {}; task_id=int(data.get("task_id") or 0); source=str(data.get("source_code") or "")[:50000]
    conn=connect(); cs=_load_coding_session(conn,sid)
    if not cs: conn.close(); return jsonify(ok=False),404
    blocked,state=_coding_blocked(cs)
    if blocked: conn.close(); return jsonify(ok=False,locked=True,**state),423
    task=conn.execute("SELECT * FROM programming_tasks WHERE id=? AND lab_id=? AND active=1",(task_id,cs["lab_id"])).fetchone()
    conn.close()
    if not task: return jsonify(ok=False,error="Task not found"),404
    try: tests=json.loads(task["hidden_tests_json"] or "[]")
    except Exception: tests=[]
    if not tests: return jsonify(ok=False,error="This task has no hidden tests configured."),409
    details,passed=grade_hidden_tests(source,tests); total=len(tests); score=round(float(task["points"])*(passed/total),2) if total else 0
    status="Accepted" if passed==total else "Partial" if passed else "Failed"
    conn=connect()
    conn.execute("""UPDATE coding_task_progress SET source_code=?,last_status=?,score=?,submitted_at=?,last_saved_at=? WHERE session_id=? AND task_id=?""",
                 (source,status,score,iso_now(),iso_now(),sid,task_id))
    conn.execute("""INSERT INTO coding_submissions(session_id,task_id,source_code,status,passed_count,total_tests,score,created_at)
                    VALUES(?,?,?,?,?,?,?,?)""",(sid,task_id,source,status,passed,total,score,iso_now()))
    total_score=conn.execute("SELECT COALESCE(SUM(score),0) FROM coding_task_progress WHERE session_id=?",(sid,)).fetchone()[0]
    conn.execute("UPDATE coding_sessions SET total_score=? WHERE id=?",(total_score,sid)); _coding_log(conn,sid,"task_submitted",f"Task {task_id}: {passed}/{total} tests, {score} points")
    conn.commit(); conn.close()
    return jsonify(ok=True,status=status,passed=passed,total=total,score=score,tests=details)


@bp.post("/ide/finish")
@ide_session_required
def ide_finish():
    require_csrf(); sid=session["coding_session_id"]
    conn=connect(); cs=_load_coding_session(conn,sid)
    if not cs: conn.close(); abort(404)
    blocked,state=_coding_blocked(cs)
    if blocked: conn.close(); flash("This coding session is security-locked.","error"); return redirect(url_for("nextgen.ide_workspace"))
    total=conn.execute("SELECT COALESCE(SUM(score),0) FROM coding_task_progress WHERE session_id=?",(sid,)).fetchone()[0]
    conn.execute("UPDATE coding_sessions SET status='submitted',submitted_at=?,total_score=? WHERE id=?",(iso_now(),total,sid)); _coding_log(conn,sid,"lab_submitted",f"Final score {total}")
    conn.commit(); conn.close(); return redirect(url_for("nextgen.ide_result"))


@bp.get("/ide/result")
@ide_session_required
def ide_result():
    sid=session["coding_session_id"]; conn=connect(); cs=_load_coding_session(conn,sid)
    if not cs: conn.close(); return redirect(url_for("nextgen.ide_login"))
    rows=conn.execute("""SELECT pt.position,pt.title,pt.points,ctp.score,ctp.last_status FROM coding_task_progress ctp
                         JOIN programming_tasks pt ON pt.id=ctp.task_id WHERE ctp.session_id=? ORDER BY pt.position""",(sid,)).fetchall()
    max_score=conn.execute("SELECT COALESCE(SUM(points),0) FROM programming_tasks WHERE lab_id=? AND active=1",(cs["lab_id"],)).fetchone()[0]
    conn.close(); return render_template("ide_result.html",cs=cs,rows=rows,max_score=max_score)


@bp.post("/api/ide/security-violation")
@ide_session_required
def ide_security_violation():
    require_csrf(); sid=session["coding_session_id"]; data=request.get_json(silent=True) or {}; source=str(data.get("source") or "focus_exit")[:80]
    conn=connect(); cs=_load_coding_session(conn,sid)
    if not cs: conn.close(); return jsonify(ok=False),404
    state=_coding_security_state(cs)
    if state["permanent"]: conn.close(); return jsonify(ok=True,**state)
    cutoff=(datetime.now(APP_TZ)-timedelta(seconds=SECURITY_DEDUPE_SECONDS)).isoformat(timespec="seconds")
    duplicate=conn.execute("SELECT 1 FROM coding_events WHERE session_id=? AND event_type='security_violation' AND created_at>=? ORDER BY id DESC LIMIT 1",(sid,cutoff)).fetchone()
    if duplicate: conn.close(); return jsonify(ok=True,**state)
    count=int(cs["violation_count"] or 0)+1; permanent=count>=MAX_SECURITY_VIOLATIONS
    conn.execute("UPDATE coding_sessions SET violation_count=?,security_locked=?,pending_blackout=? WHERE id=?",(count,1 if permanent else 0,0 if permanent else 1,sid))
    _coding_log(conn,sid,"security_violation",f"Violation {count}: {source}")
    if permanent: _coding_log(conn,sid,"security_lock_permanent","Maximum security violations reached")
    conn.commit(); cs=_load_coding_session(conn,sid); state=_coding_security_state(cs); conn.close()
    return jsonify(ok=True,**state)


@bp.post("/api/ide/security-start-lock")
@ide_session_required
def ide_security_start_lock():
    require_csrf(); sid=session["coding_session_id"]; conn=connect(); cs=_load_coding_session(conn,sid)
    if not cs: conn.close(); return jsonify(ok=False),404
    state=_coding_security_state(cs)
    if state["permanent"] or not state["pending"]: conn.close(); return jsonify(ok=True,**state)
    until=(datetime.now(APP_TZ)+timedelta(seconds=TEMP_LOCK_SECONDS)).isoformat(timespec="seconds")
    conn.execute("UPDATE coding_sessions SET pending_blackout=0,temp_locked_until=? WHERE id=?",(until,sid)); _coding_log(conn,sid,"security_blackout_started",f"{TEMP_LOCK_SECONDS}-second coding lock")
    conn.commit(); cs=_load_coding_session(conn,sid); state=_coding_security_state(cs); conn.close(); return jsonify(ok=True,**state)


@bp.get("/api/ide/security-status")
@ide_session_required
def ide_security_status():
    sid=session["coding_session_id"]; conn=connect(); cs=_load_coding_session(conn,sid)
    if not cs: conn.close(); return jsonify(ok=False),404
    state=_coding_security_state(cs)
    if not state["pending"] and not state["permanent"] and state["temp_remaining"]<=0 and cs["temp_locked_until"]:
        conn.execute("UPDATE coding_sessions SET temp_locked_until=NULL WHERE id=?",(sid,)); conn.commit()
    conn.close(); return jsonify(ok=True,**state)


@bp.post("/api/ide/event")
@ide_session_required
def ide_event():
    require_csrf(); sid=session["coding_session_id"]; data=request.get_json(silent=True) or {}
    event=str(data.get("type") or "event")[:80]; detail=str(data.get("detail") or "")[:1000]
    conn=connect(); _coding_log(conn,sid,event,detail)
    if event in {"blocked_shortcut","contextmenu","inactivity"}:
        conn.execute("UPDATE coding_sessions SET flagged_count=flagged_count+1 WHERE id=?",(sid,))
    conn.commit(); conn.close(); return jsonify(ok=True)


@bp.get("/ide/logout")
def ide_logout():
    session.pop("coding_session_id",None); session.pop("pending_ide",None)
    return redirect(url_for("nextgen.ide_login"))


def register(app):
    app.register_blueprint(bp)

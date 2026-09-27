from __future__ import annotations

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
                  (SELECT COUNT(*) FROM assessments a WHERE a.subject_id=s.id) AS assessment_count,
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
                  (SELECT COUNT(*) FROM programming_labs pl WHERE pl.assessment_id=a.id) AS has_lab
           FROM assessments a JOIN subjects s ON s.id=a.subject_id
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


@bp.post("/admin/workspace/assessment/add")
@admin_required
def assessment_add():
    require_csrf()
    subject_id = request.form.get("subject_id", "")
    title = request.form.get("title", "").strip()
    assessment_type = request.form.get("assessment_type", "quiz").strip().lower()
    description = request.form.get("description", "").strip()
    duration = max(1, min(480, int(request.form.get("duration_minutes", "60") or 60)))
    security_mode = request.form.get("security_mode", "standard")
    if not subject_id.isdigit() or not title:
        flash("Choose a subject and enter an assessment title.", "error")
        return redirect(url_for("nextgen.workspace"))
    conn = connect()
    try:
        instructor = _current_instructor(conn)
        base_slug = _slugify(title)
        slug = base_slug
        n = 2
        while conn.execute("SELECT 1 FROM assessments WHERE slug=?", (slug,)).fetchone():
            slug = f"{base_slug}-{n}"
            n += 1
        access = _make_access_code("CPP" if assessment_type == "programming_lab" else "ASSESS")
        cur = conn.execute(
            """INSERT INTO assessments(subject_id,title,slug,assessment_type,description,duration_minutes,
                       access_code,max_attempts,security_mode,active,created_by_instructor_id,created_at)
               VALUES(?,?,?,?,?,?,?,1,?,1,?,?) RETURNING id""",
            (int(subject_id), title, slug, assessment_type, description, duration, access,
             security_mode, instructor["id"] if instructor else None, iso_now()),
        )
        assessment_id = cur.fetchone()[0]
        if assessment_type == "programming_lab":
            conn.execute(
                """INSERT INTO programming_labs(assessment_id,language,title,instructions,starter_code,
                           allow_custom_input,active,created_at)
                   VALUES(?, 'cpp', ?, ?, '#include <iostream>\\nusing namespace std;\\n\\nint main() {\\n    return 0;\\n}\\n',1,1,?)""",
                (assessment_id, title, description or "Complete the programming tasks below.", iso_now()),
            )
        conn.commit()
        flash(f"Assessment created. Session key: {access}", "success")
    except Exception as exc:
        conn.rollback()
        flash(f"Could not create assessment: {exc}", "error")
    finally:
        conn.close()
    return redirect(url_for("nextgen.workspace"))


@bp.post("/admin/workspace/assessment/<int:assessment_id>/edit")
@admin_required
def assessment_edit(assessment_id):
    require_csrf()
    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    duration = max(1, min(480, int(request.form.get("duration_minutes", "60") or 60)))
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
    try:
        conn.execute("UPDATE assessments SET title=?,description=?,duration_minutes=?,security_mode=?,active=?,access_code=? WHERE id=?", (title,description,duration,security_mode,active,access_code,assessment_id))
        if row["assessment_type"] == "programming_lab":
            conn.execute("UPDATE programming_labs SET title=?,active=? WHERE assessment_id=?", (title,active,assessment_id))
        conn.commit(); flash("Assessment updated.", "success")
    except Exception as exc:
        conn.rollback(); flash(f"Could not update assessment: {exc}", "error")
    finally:
        try: conn.close()
        except Exception: pass
    return redirect(url_for("nextgen.workspace"))


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

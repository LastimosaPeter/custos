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
import re
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
    "nextgen.admin_ide_unlock", "google.owner_view_all_toggle",
}


def active():
    return CLASSROOM_INSTRUCTORS


def is_owner_email(email):
    from google_integration import canonical_email

    return canonical_email(email) in {canonical_email(e) for e in _OWNER_EMAILS_RAW}


def scoped():
    """Access control: True when the signed-in admin is a Classroom instructor (not an owner).
    Instructors are refused anything outside their own courses."""
    return CLASSROOM_INSTRUCTORS and session.get("admin_id") and session.get("admin_authenticated") is True and session.get("admin_role") != "owner"


def is_owner():
    return bool(session.get("admin_id")) and session.get("admin_authenticated") is True and session.get("admin_role", "owner") == "owner"


def owner_view_all():
    return CLASSROOM_INSTRUCTORS and is_owner() and bool(session.get("owner_view_all"))


def list_scoped():
    """What lists show: everyone sees only their own courses' subjects, assessments
    and attempts - owners too - unless an owner switched on "Show all". Owners
    still aren't *refused* other pages (that's scoped(), instructors only)."""
    return CLASSROOM_INSTRUCTORS and bool(session.get("admin_id")) and session.get("admin_authenticated") is True and not owner_view_all()


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
    """Keep only rows the current admin's lists should show (see list_scoped)."""
    if not list_scoped():
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
        elif name == "course_id":
            refs.add(("course", str(value)))
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
            if isinstance(ref, tuple) and ref[0] == "course":
                ok = ref[1] in taught_course_ids(conn)
            elif isinstance(ref, tuple):
                ok = ref[1] in subjects
            else:
                ok = ref in assessments
            if not ok:
                abort(404)
    finally:
        conn.close()
    return None


def taught_course_ids(conn):
    iid = _instructor_id(conn)
    return {r["course_id"] for r in conn.execute(
        "SELECT course_id FROM instructor_courses WHERE instructor_id=?", (iid,)).fetchall()} if iid else set()


def courses_for_admin(conn):
    """Classroom courses the signed-in admin may edit: owners all, instructors theirs."""
    rows = conn.execute(
        """SELECT cc.course_id, cc.course_name, cc.program, cc.class_section, cc.manual, cc.archived,
                  s.id AS subject_id, s.code, s.name AS subject_title, s.term, s.school_year
           FROM classroom_courses cc JOIN subjects s ON s.id=cc.subject_id
           ORDER BY s.school_year DESC, s.term, s.code, cc.program, cc.class_section, cc.course_name"""
    ).fetchall()
    if scoped():
        mine = taught_course_ids(conn)
        rows = [r for r in rows if r["course_id"] in mine]
    return rows


SECTION_RE = re.compile(r"^\s*([A-Za-z]{1,4})\s*-?\s*(\d{1,3})\s*(?:[Aa][MFmf])?\s*$")


class CourseEditError(ValueError):
    pass


def _validated_details(form):
    """(school_year, term, code, title, program, class_section) or CourseEditError."""
    year_raw = str(form.get("school_year", "")).strip()
    m = re.fullmatch(r"((?:19|20)\d{2})(?:\s*-\s*((?:19|20)\d{2}))?", year_raw)
    if not m or (m.group(2) and int(m.group(2)) != int(m.group(1)) + 1):
        raise CourseEditError("Academic year must look like 2026-2027.")
    school_year = f"{m.group(1)}-{int(m.group(1)) + 1}"
    term = str(form.get("term", "")).strip()
    if term not in TERM_LABELS.values():
        raise CourseEditError("Choose the semester.")
    code = re.sub(r"\s+", "", str(form.get("code", ""))).upper()
    if not re.fullmatch(r"[A-Z0-9._-]{2,20}", code):
        raise CourseEditError("Subject code should look like CSDC100.")
    title = " ".join(str(form.get("title", "")).split())[:120] or code
    sm = SECTION_RE.match(str(form.get("section", "")))
    if not sm:
        raise CourseEditError("Section should look like ZC11.")
    program, class_section = sm.group(1).upper(), sm.group(2)
    return school_year, term, code, title, program, class_section


def edit_course(conn, course_id, form):
    """Apply a teacher/owner edit of one Classroom course's details (see module docs)."""
    school_year, term, code, title, program, class_section = _validated_details(form)
    course = conn.execute("SELECT * FROM classroom_courses WHERE course_id=?", (course_id,)).fetchone()
    if not course:
        raise CourseEditError("Unknown Google Classroom course.")
    old_sid = course["subject_id"]
    target = conn.execute("SELECT id FROM subjects WHERE code=? AND term=? AND school_year=?",
                          (code, term, school_year)).fetchone()
    shared = conn.execute("SELECT COUNT(*) FROM classroom_courses WHERE subject_id=? AND course_id<>?",
                          (old_sid, course_id)).fetchone()[0]
    if target is None or target["id"] == old_sid:
        if shared == 0 or (target and target["id"] == old_sid):
            # This course's own subject (or unchanged key): rename in place, keeps its assessments.
            conn.execute("UPDATE subjects SET code=?, term=?, school_year=?, name=? WHERE id=?",
                         (code, term, school_year, title, old_sid))
            new_sid = old_sid
        else:
            new_sid = conn.execute(
                "INSERT INTO subjects(code,name,term,school_year,active,created_at) VALUES (?,?,?,?,1,?) RETURNING id",
                (code, title, term, school_year, iso_now()),
            ).fetchone()[0]
    else:
        new_sid = target["id"]
        conn.execute("UPDATE subjects SET name=? WHERE id=?", (title, new_sid))
    if new_sid != old_sid:
        # Teachers of the old subject follow the course.
        conn.execute("""INSERT INTO subject_instructors(subject_id,instructor_id,role)
                        SELECT ?, instructor_id, role FROM subject_instructors WHERE subject_id=?
                        ON CONFLICT(subject_id,instructor_id) DO NOTHING""", (new_sid, old_sid))
        if shared == 0:
            # The old subject only existed for this course: move its assessments, retire it.
            conn.execute("UPDATE questions SET subject_id=? WHERE assessment_id IN (SELECT id FROM assessments WHERE subject_id=?)",
                         (new_sid, old_sid))
            conn.execute("UPDATE assessments SET subject_id=? WHERE subject_id=?", (new_sid, old_sid))
            conn.execute("UPDATE batches SET subject_id=? WHERE subject_id=?", (new_sid, old_sid))
            conn.execute("DELETE FROM subject_instructors WHERE subject_id=?", (old_sid,))
            conn.execute("UPDATE subjects SET active=0 WHERE id=?", (old_sid,))
    conn.execute(
        """UPDATE classroom_courses SET subject_id=?, program=?, class_section=?, manual=1, updated_at=?
           WHERE course_id=?""", (new_sid, program, class_section, iso_now(), course_id))
    # Rosters already imported from this course follow the new section.
    conn.execute("UPDATE classroom_rosters SET program=?, class_section=? WHERE course_id=?",
                 (program, class_section, course_id))
    return new_sid


def set_course_archived(conn, course_id, archived):
    """Archive instead of delete: the class leaves the list; nothing else changes."""
    conn.execute("UPDATE classroom_courses SET archived=?, updated_at=? WHERE course_id=?",
                 (1 if archived else 0, iso_now(), course_id))


PAGE_SIZES = (10, 25, 50, 100)
NEEDS_DETAILS = "needs-details"


def class_listing(conn, args):
    """One page of the classes the signed-in admin may manage, filtered in SQL
    by academic year + semester (default: the latest one) - never the whole list.
    args: year ("2026-2027" or "needs-details"), term, archived ("1"), size, page."""
    _TERMS = list(TERM_LABELS.values())
    where, params = ["cc.archived=?"], [1 if args.get("archived") == "1" else 0]
    if list_scoped():
        where.append("cc.course_id IN (SELECT course_id FROM instructor_courses WHERE instructor_id=?)")
        params.append(_instructor_id(conn) or -1)
    base = "FROM classroom_courses cc JOIN subjects s ON s.id=cc.subject_id WHERE " + " AND ".join(where)

    dated = conn.execute(
        f"""SELECT s.school_year, s.term, COUNT(*) AS n {base} AND s.school_year<>'' AND s.term IN ({",".join("?" * len(_TERMS))})
            GROUP BY s.school_year, s.term""", (*params, *_TERMS)).fetchall()
    undated = conn.execute(
        f"""SELECT COUNT(*) {base} AND (s.school_year='' OR s.term NOT IN ({",".join("?" * len(_TERMS))}))""",
        (*params, *_TERMS)).fetchone()[0]
    semesters = sorted(((r["school_year"], r["term"]) for r in dated),
                       key=lambda yt: (yt[0][:4], _TERMS.index(yt[1])), reverse=True)
    years = sorted({y for y, _ in semesters}, reverse=True)

    year, term = str(args.get("year", "")), str(args.get("term", ""))
    if year == NEEDS_DETAILS and undated:
        term = ""
    elif (year, term) not in semesters:
        # Unknown/missing choice (or a year without that semester): newest term of
        # the chosen year, else the latest semester overall.
        in_year = [t for y, t in semesters if y == year]
        if in_year:
            term = max(in_year, key=_TERMS.index)
        elif semesters:
            year, term = semesters[0]
        elif undated:
            year, term = NEEDS_DETAILS, ""
        else:
            year, term = "", ""

    size = int(args.get("size")) if str(args.get("size", "")).isdigit() and int(args.get("size")) in PAGE_SIZES else PAGE_SIZES[0]
    page = max(1, int(args.get("page")) if str(args.get("page", "")).isdigit() else 1)
    if year == NEEDS_DETAILS:
        cond, cparams = f" AND (s.school_year='' OR s.term NOT IN ({','.join('?' * len(_TERMS))}))", list(_TERMS)
    else:
        cond, cparams = " AND s.school_year=? AND s.term=?", [year, term]
    total = conn.execute(f"SELECT COUNT(*) {base}{cond}", (*params, *cparams)).fetchone()[0] if year else 0
    pages = max(1, -(-total // size))
    page = min(page, pages)
    rows = conn.execute(
        f"""SELECT cc.course_id, cc.course_name, cc.program, cc.class_section, cc.manual, cc.archived,
                   s.id AS subject_id, s.code, s.name AS subject_title, s.term, s.school_year
            {base}{cond} ORDER BY s.code, cc.program, cc.class_section, cc.course_name LIMIT ? OFFSET ?""",
        (*params, *cparams, size, (page - 1) * size)).fetchall() if year else []
    archived_count = conn.execute(
        "SELECT COUNT(*) FROM classroom_courses cc WHERE cc.archived=1"
        + (" AND cc.course_id IN (SELECT course_id FROM instructor_courses WHERE instructor_id=?)" if list_scoped() else ""),
        ((_instructor_id(conn) or -1,) if list_scoped() else ())).fetchone()[0]
    return rows, {
        "years": years, "terms": _TERMS, "year": year, "term": term, "undated": undated,
        "size": size, "sizes": PAGE_SIZES, "page": page, "pages": pages, "total": total,
        "archived": args.get("archived") == "1", "archived_count": archived_count,
        "latest": semesters[0] if semesters else None,
    }


def subject_listing(conn, args):
    """One page of the Workspace Subjects list, filtered in SQL by academic year
    + semester (default: the latest) and by ownership (list_scoped). Own query
    params so it doesn't clash with the class list: sy, st, ss (size), sp (page)."""
    terms = list(TERM_LABELS.values())
    marks = ",".join("?" * len(terms))
    where, params = ["1=1"], []
    if list_scoped():
        subj = sorted(visible_subject_ids(conn)) or [-1]
        where.append(f"s.id IN ({','.join('?' * len(subj))})")
        params.extend(subj)
    base = "FROM subjects s WHERE " + " AND ".join(where)
    dated = conn.execute(f"SELECT DISTINCT s.school_year, s.term {base} AND s.school_year<>'' AND s.term IN ({marks})",
                         (*params, *terms)).fetchall()
    undated = conn.execute(f"SELECT COUNT(*) {base} AND (s.school_year='' OR s.term NOT IN ({marks}))",
                           (*params, *terms)).fetchone()[0]
    semesters = sorted(((r["school_year"], r["term"]) for r in dated),
                       key=lambda yt: (yt[0][:4], terms.index(yt[1])), reverse=True)
    year, term = str(args.get("sy", "")), str(args.get("st", ""))
    if year == NEEDS_DETAILS and undated:
        term = ""
    elif (year, term) not in semesters:
        in_year = [t for y, t in semesters if y == year]
        if in_year:
            term = max(in_year, key=terms.index)
        elif semesters:
            year, term = semesters[0]
        elif undated:
            year, term = NEEDS_DETAILS, ""
        else:
            year, term = "", ""
    size = int(args.get("ss")) if str(args.get("ss", "")).isdigit() and int(args.get("ss")) in PAGE_SIZES else PAGE_SIZES[0]
    page = max(1, int(args.get("sp")) if str(args.get("sp", "")).isdigit() else 1)
    if year == NEEDS_DETAILS:
        cond, cparams = f" AND (s.school_year='' OR s.term NOT IN ({marks}))", list(terms)
    else:
        cond, cparams = " AND s.school_year=? AND s.term=?", [year, term]
    total = conn.execute(f"SELECT COUNT(*) {base}{cond}", (*params, *cparams)).fetchone()[0] if year else 0
    all_total = conn.execute(f"SELECT COUNT(*) {base}", tuple(params)).fetchone()[0]
    pages = max(1, -(-total // size))
    page = min(page, pages)
    rows = conn.execute(
        f"""SELECT s.*,
                   (SELECT COUNT(*) FROM assessments a WHERE a.subject_id=s.id AND a.deleted_at IS NULL) AS assessment_count,
                   (SELECT COUNT(*) FROM subject_instructors si WHERE si.subject_id=s.id) AS instructor_count
            {base}{cond} ORDER BY s.active DESC, s.code, s.name LIMIT ? OFFSET ?""",
        (*params, *cparams, size, (page - 1) * size)).fetchall() if year else []
    return rows, {"years": sorted({y for y, _ in semesters}, reverse=True), "terms": terms, "year": year, "term": term,
                  "undated": undated, "size": size, "sizes": PAGE_SIZES, "page": page, "pages": pages, "total": total,
                  "all_total": all_total, "latest": semesters[0] if semesters else None}


# ---------------------------------------------------------------- sign-in

# ADNU Classroom naming: "2026-1 CSDC100.ZC11Am"
#   2026-1  -> school year 2026-2027, term 1 (1 = 1st sem, 2 = 2nd sem, 3 = intersession)
#   CSDC100 -> subject code;  ZC11 -> section (program ZC, section 11); Am/Af -> ignored
TERM_LABELS = {"1": "1st Semester", "2": "2nd Semester", "3": "Intersession"}
_COURSE_RE = re.compile(
    r"^\s*(?P<year>(?:19|20)\d{2})\s*[-.]\s*(?P<term>[123])\s+"
    r"(?P<code>[A-Za-z]{2,8}\s?\d{2,4}[A-Za-z]?)\s*[.\s_-]\s*"
    r"(?P<program>[A-Za-z]{1,4})\s*-?\s*(?P<section>\d{1,3})\s*(?:[Aa][MFmf])?\s*$"
)


def parse_course_name(*candidates):
    """Parse the first candidate matching the ADNU pattern, else None."""
    for text in candidates:
        m = _COURSE_RE.match(str(text or ""))
        if m:
            year = int(m.group("year"))
            return {
                "school_year": f"{year}-{year + 1}",
                "term": TERM_LABELS[m.group("term")],
                "code": m.group("code").replace(" ", "").upper(),
                "program": m.group("program").upper(),
                "class_section": str(int(m.group("section"))) if len(m.group("section")) > 2 else m.group("section"),
            }
    return None


def _subject_for_course(conn, course):
    """Find/create the subject for one Classroom course; returns (subject_id, parsed)."""
    cid = str(course.get("id"))
    name = (course.get("name") or "Google Classroom course")[:120]
    parsed = parse_course_name(name, f"{name} {course.get('section') or ''}".strip(), course.get("section"))
    mapped = conn.execute("SELECT subject_id, manual FROM classroom_courses WHERE course_id=?", (cid,)).fetchone()
    if mapped and mapped["manual"]:
        # Edited by hand in Custos: keep the teacher's details, only refresh the name.
        conn.execute("UPDATE classroom_courses SET course_name=?, updated_at=? WHERE course_id=?", (name, iso_now(), cid))
        return mapped["subject_id"]
    if parsed:
        title = (course.get("descriptionHeading") or parsed["code"])[:120]
        row = conn.execute("SELECT id FROM subjects WHERE code=? AND term=? AND school_year=?",
                           (parsed["code"], parsed["term"], parsed["school_year"])).fetchone()
        sid = row["id"] if row else conn.execute(
            """INSERT INTO subjects(code,name,term,school_year,active,created_at) VALUES (?,?,?,?,1,?) RETURNING id""",
            (parsed["code"], title, parsed["term"], parsed["school_year"], iso_now()),
        ).fetchone()[0]
    elif mapped:
        sid = mapped["subject_id"]
    else:
        # Name doesn't follow the pattern: one subject per course; codes must be
        # unique with blank term/year, so add " #n" if another course has it.
        base = (course.get("section") or course.get("descriptionHeading") or name)[:36]
        code, n = base, 1
        while conn.execute("SELECT 1 FROM subjects WHERE code=? AND term='' AND school_year=''", (code,)).fetchone():
            n += 1
            code = f"{base} #{n}"
        sid = conn.execute(
            """INSERT INTO subjects(code,name,term,school_year,active,created_at) VALUES (?,?,'','',1,?) RETURNING id""",
            (code, name, iso_now()),
        ).fetchone()[0]
    conn.execute(
        """INSERT INTO classroom_courses(course_id,subject_id,course_name,program,class_section,updated_at)
           VALUES (?,?,?,?,?,?)
           ON CONFLICT(course_id) DO UPDATE SET subject_id=excluded.subject_id, course_name=excluded.course_name,
             program=excluded.program, class_section=excluded.class_section, updated_at=excluded.updated_at""",
        (cid, sid, name, parsed["program"] if parsed else None, parsed["class_section"] if parsed else None, iso_now()),
    )
    return sid


def sync_classroom_subjects(conn, instructor_id, courses):
    """Each taught course -> its subject (school year + term + subject code),
    linked to this instructor; drop links to Classroom-derived subjects the
    instructor no longer teaches any course of."""
    keep = set()
    conn.execute("DELETE FROM instructor_courses WHERE instructor_id=?", (instructor_id,))
    for c in courses:
        if not c.get("id"):
            continue
        sid = _subject_for_course(conn, c)
        conn.execute("INSERT INTO instructor_courses(instructor_id,course_id) VALUES (?,?) ON CONFLICT DO NOTHING",
                     (instructor_id, str(c["id"])))
        conn.execute("UPDATE subjects SET active=1 WHERE id=?", (sid,))
        conn.execute(
            """INSERT INTO subject_instructors(subject_id,instructor_id,role) VALUES(?,?,'instructor')
               ON CONFLICT(subject_id,instructor_id) DO NOTHING""",
            (sid, instructor_id),
        )
        keep.add(sid)
    stale = conn.execute(
        """SELECT DISTINCT si.subject_id FROM subject_instructors si
           JOIN classroom_courses cc ON cc.subject_id=si.subject_id WHERE si.instructor_id=?""",
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
    app.jinja_env.globals.update(classroom_instructors=CLASSROOM_INSTRUCTORS, owner_view_all=owner_view_all)

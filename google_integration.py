"""Google sign-in and Google Classroom roster import for Custos.

Everything here is switched on by configuration only:

    GOOGLE_CLIENT_ID=<OAuth 2.0 Web client id>      # unset -> feature fully off
    GOOGLE_ALLOWED_DOMAINS=adnu.edu.ph,gbox.adnu.edu.ph   # student Google domains
    STUDENT_GOOGLE_LOGIN_REQUIRED=1                  # default 1 when a client id is set

Flows (Google Identity Services, popup mode - no redirect URI is needed):

- Students: "Sign in with Google" posts the ID token to /auth/google/student.
  The server verifies it (signature, audience, issuer, expiry, verified email,
  Workspace `hd` claim in GOOGLE_ALLOWED_DOMAINS) and keeps the verified
  identity in the signed session. The exam login then uses that email instead
  of a typed one.
- Instructors: /auth/google/admin signs in the Custos instructor/admin account
  whose email matches the verified Google email. Username + password keeps
  working.
- Classroom: on an assessment page the instructor grants a short-lived access
  token in the browser (read-only Classroom scopes). The server checks the
  token was issued to this client, lists the instructor's courses, and imports
  a course roster mapped to a Custos Program/Section. Tokens are never stored.
  When an assessment has at least one roster, only rostered students may start
  it, and their name and section come from the roster.
"""
import os
import re

import requests
from flask import Blueprint, abort, current_app, jsonify, request, session

from db import connect, iso_now

bp = Blueprint("google", __name__)

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "").strip()
_default_domains = os.getenv("ALLOWED_EMAIL_DOMAIN", "adnu.edu.ph")
GOOGLE_ALLOWED_DOMAINS = {
    d.strip().lower() for d in os.getenv("GOOGLE_ALLOWED_DOMAINS", _default_domains).split(",") if d.strip()
}
STUDENT_GOOGLE_LOGIN_REQUIRED = bool(GOOGLE_CLIENT_ID) and os.getenv("STUDENT_GOOGLE_LOGIN_REQUIRED", "1") == "1"

CLASSROOM_SCOPES = (
    "https://www.googleapis.com/auth/classroom.courses.readonly",
    "https://www.googleapis.com/auth/classroom.rosters.readonly",
    "https://www.googleapis.com/auth/classroom.profile.emails",
)
CLASSROOM_API = "https://classroom.googleapis.com/v1"
TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"
HTTP_TIMEOUT = 15


class GoogleAuthError(Exception):
    """A user-facing, deliberately generic sign-in failure."""


def google_enabled():
    return bool(GOOGLE_CLIENT_ID)


def _email_domain(email):
    return email.rsplit("@", 1)[-1].lower() if "@" in email else ""


def verify_id_token(credential):
    """Verify a Google Identity Services ID token and return its claims.

    Checks signature (Google's public keys), audience == our client id,
    issuer, expiry, and email_verified. Raises GoogleAuthError on any failure.
    """
    if not google_enabled():
        raise GoogleAuthError("Google sign-in is not configured.")
    if not credential or not isinstance(credential, str) or len(credential) > 4096:
        raise GoogleAuthError("Google sign-in failed. Please try again.")
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token

    try:
        claims = id_token.verify_oauth2_token(
            credential, google_requests.Request(), GOOGLE_CLIENT_ID, clock_skew_in_seconds=10
        )
    except Exception as exc:  # noqa: BLE001 - never leak verification details
        current_app.logger.info("Google ID token rejected: %s", type(exc).__name__)
        raise GoogleAuthError("Google sign-in failed. Please try again.") from None
    if claims.get("iss") not in ("accounts.google.com", "https://accounts.google.com"):
        raise GoogleAuthError("Google sign-in failed. Please try again.")
    email = str(claims.get("email", "")).strip().lower()
    if not email or not claims.get("email_verified"):
        raise GoogleAuthError("Your Google account email is not verified.")
    claims["email"] = email
    return claims


def verify_student_claims(claims):
    """Students must use a school Workspace account in GOOGLE_ALLOWED_DOMAINS."""
    domain = _email_domain(claims["email"])
    hosted_domain = str(claims.get("hd", "")).lower()
    if domain not in GOOGLE_ALLOWED_DOMAINS or hosted_domain not in GOOGLE_ALLOWED_DOMAINS:
        allowed = " or ".join(f"@{d}" for d in sorted(GOOGLE_ALLOWED_DOMAINS))
        raise GoogleAuthError(f"Use your school Google account ({allowed}).")


def google_student_identity():
    """The verified Google identity for the current student browser, or None."""
    ident = session.get("google_student")
    return ident if isinstance(ident, dict) and ident.get("email") else None


def google_profile_names(ident):
    """(first, last) from the verified Google profile, never empty."""
    first = " ".join(str(ident.get("given_name", "")).split())[:60]
    last = " ".join(str(ident.get("family_name", "")).split())[:60]
    if not first and not last:
        parts = " ".join(str(ident.get("name", "")).split()).rsplit(" ", 1)
        first, last = (parts[0], parts[1]) if len(parts) == 2 else (parts[0], "")
    if not first:
        first = ident["email"].split("@", 1)[0][:60]
    return first, last or "-"


def _require_csrf_header():
    supplied = request.headers.get("X-CSRFToken", "")
    expected = session.get("csrf_token", "")
    import secrets

    if not supplied or not expected or not secrets.compare_digest(supplied, expected):
        abort(400, "Invalid CSRF token")


# --------------------------------------------------------------------------
# Students
# --------------------------------------------------------------------------

@bp.post("/auth/google/student")
def student_google_signin():
    """Single Google entry point on the student page: an instructor's email
    goes straight to the Workspace; everyone else continues as a student."""
    _require_csrf_header()
    payload = request.get_json(silent=True) or {}
    try:
        claims = verify_id_token(payload.get("credential"))
    except GoogleAuthError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 401
    conn = connect()
    try:
        admin = find_admin_for_email(conn, claims["email"])
    finally:
        conn.close()
    if admin:
        return jsonify({"ok": True, "role": "instructor", "redirect": _sign_in_admin(admin)})
    try:
        verify_student_claims(claims)
    except GoogleAuthError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 401
    session["google_student"] = {
        "email": claims["email"],
        "sub": str(claims.get("sub", "")),
        "given_name": str(claims.get("given_name", ""))[:60],
        "family_name": str(claims.get("family_name", ""))[:60],
        "name": str(claims.get("name", ""))[:120],
    }
    return jsonify({"ok": True, "role": "student", "email": claims["email"]})


@bp.post("/auth/google/student/signout")
def student_google_signout():
    _require_csrf_header()
    for key in ("google_student", "pending_email", "pending_first_name", "pending_last_name",
                "pending_student_name", "pending_program", "pending_class_section",
                "pending_batch_id", "pending_session_key", "pending_google_sub"):
        session.pop(key, None)
    return jsonify({"ok": True})


# --------------------------------------------------------------------------
# Instructors
# --------------------------------------------------------------------------

def find_admin_for_email(conn, email):
    """An active Custos admin whose own email, or linked instructor email, matches."""
    row = conn.execute(
        "SELECT * FROM admins WHERE LOWER(COALESCE(email,''))=? AND COALESCE(active,1)=1", (email,)
    ).fetchone()
    if row:
        return row
    return conn.execute(
        """SELECT a.* FROM admins a JOIN instructors i ON i.admin_id=a.id
           WHERE LOWER(COALESCE(i.email,''))=? AND COALESCE(i.active,1)=1 AND COALESCE(a.active,1)=1""",
        (email,),
    ).fetchone()


@bp.post("/auth/google/admin")
def admin_google_signin():
    _require_csrf_header()
    payload = request.get_json(silent=True) or {}
    try:
        claims = verify_id_token(payload.get("credential"))
    except GoogleAuthError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 401
    conn = connect()
    try:
        admin = find_admin_for_email(conn, claims["email"])
    finally:
        conn.close()
    if not admin:
        return jsonify({"ok": False, "error": "No Custos instructor account uses this Google email."}), 403
    return jsonify({"ok": True, "redirect": _sign_in_admin(admin)})


def _sign_in_admin(admin):
    """Same session the password login creates; returns the Workspace URL."""
    from flask import url_for

    from app import csrf_token  # late import: app imports this module

    session.clear()
    session["admin_id"] = admin["id"]
    session["admin_role"] = admin["role"] if "role" in admin.keys() else "owner"
    session["admin_display_name"] = (admin["display_name"] if "display_name" in admin.keys() else None) or admin["username"]
    session["admin_auth_method"] = "google"
    csrf_token()
    return url_for("nextgen.workspace")


# --------------------------------------------------------------------------
# Classroom roster import
# --------------------------------------------------------------------------

def _require_admin():
    if not session.get("admin_id"):
        abort(401)


def _assessment_or_404(conn, assessment_id):
    row = conn.execute(
        "SELECT * FROM assessments WHERE id=? AND deleted_at IS NULL", (assessment_id,)
    ).fetchone()
    if not row:
        abort(404)
    return row


def _checked_access_token(payload):
    """Confirm the browser-supplied access token was issued to THIS client id
    with the roster scopes, so a token minted for another app can't be used."""
    token = str(payload.get("access_token", ""))
    if not token or len(token) > 4096:
        raise GoogleAuthError("Google Classroom authorization is missing. Click Connect again.")
    try:
        info = requests.get(TOKENINFO_URL, params={"access_token": token}, timeout=HTTP_TIMEOUT)
    except requests.RequestException:
        raise GoogleAuthError("Could not reach Google. Try again.") from None
    if info.status_code != 200:
        raise GoogleAuthError("Google Classroom authorization expired. Click Connect again.")
    data = info.json()
    if data.get("aud") != GOOGLE_CLIENT_ID and data.get("azp") != GOOGLE_CLIENT_ID:
        raise GoogleAuthError("Google Classroom authorization was not issued for Custos.")
    granted = set(str(data.get("scope", "")).split())
    if not set(CLASSROOM_SCOPES) <= granted:
        raise GoogleAuthError("Please allow all requested Google Classroom permissions and try again.")
    return token


def _classroom_get(token, path, params=None):
    items, page_token = [], None
    key = "courses" if path == "/courses" else "students"
    for _ in range(50):  # hard cap: 50 pages
        query = dict(params or {}, pageSize=100)
        if page_token:
            query["pageToken"] = page_token
        try:
            resp = requests.get(f"{CLASSROOM_API}{path}", params=query,
                                headers={"Authorization": f"Bearer {token}"}, timeout=HTTP_TIMEOUT)
        except requests.RequestException:
            raise GoogleAuthError("Could not reach Google Classroom. Try again.") from None
        if resp.status_code == 403:
            raise GoogleAuthError("Google Classroom refused access to this course.")
        if resp.status_code != 200:
            raise GoogleAuthError("Google Classroom request failed. Try again.")
        data = resp.json()
        items.extend(data.get(key, []))
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return items


def _section_choices():
    from app import STUDENT_SECTIONS

    return STUDENT_SECTIONS


@bp.post("/admin/assessment/<int:assessment_id>/classroom/courses")
def classroom_courses(assessment_id):
    _require_admin()
    _require_csrf_header()
    conn = connect()
    try:
        _assessment_or_404(conn, assessment_id)
    finally:
        conn.close()
    try:
        token = _checked_access_token(request.get_json(silent=True) or {})
        courses = _classroom_get(token, "/courses", {"teacherId": "me", "courseStates": "ACTIVE"})
    except GoogleAuthError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, "courses": [
        {"id": c.get("id"), "name": c.get("name", ""), "section": c.get("section", "")}
        for c in courses if c.get("id")
    ]})


@bp.post("/admin/assessment/<int:assessment_id>/classroom/import")
def classroom_import(assessment_id):
    _require_admin()
    _require_csrf_header()
    payload = request.get_json(silent=True) or {}
    course_id = str(payload.get("course_id", "")).strip()
    program = str(payload.get("program", "")).strip().upper()
    class_section = str(payload.get("class_section", "")).strip()
    sections = _section_choices()
    if not re.fullmatch(r"[0-9A-Za-z_-]{1,64}", course_id):
        return jsonify({"ok": False, "error": "Choose a Google Classroom course."}), 400
    if program not in sections or class_section not in sections[program]:
        return jsonify({"ok": False, "error": "Choose a valid Program and Section for this roster."}), 400
    try:
        token = _checked_access_token(payload)
        courses = {c.get("id"): c for c in _classroom_get(token, "/courses", {"teacherId": "me", "courseStates": "ACTIVE"})}
        if course_id not in courses:
            raise GoogleAuthError("That course isn't one of your active Google Classroom courses.")
        students = _classroom_get(token, f"/courses/{course_id}/students")
    except GoogleAuthError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    rows, skipped = {}, 0
    for s in students:
        profile = s.get("profile") or {}
        email = str(profile.get("emailAddress", "")).strip().lower()
        if not email or _email_domain(email) not in GOOGLE_ALLOWED_DOMAINS:
            skipped += 1
            continue
        name = profile.get("name") or {}
        rows[email] = (
            str(name.get("givenName", "")).strip()[:60],
            str(name.get("familyName", "")).strip()[:60],
            str(profile.get("id", s.get("userId", "")))[:64],
        )

    course = courses[course_id]
    now = iso_now()
    conn = connect()
    try:
        _assessment_or_404(conn, assessment_id)
        existing = conn.execute(
            "SELECT id FROM classroom_rosters WHERE assessment_id=? AND course_id=?", (assessment_id, course_id)
        ).fetchone()
        if existing:
            roster_id = existing["id"]
            conn.execute(
                """UPDATE classroom_rosters SET course_name=?, course_section=?, program=?, class_section=?,
                   imported_by_admin_id=?, imported_at=?, student_count=? WHERE id=?""",
                (course.get("name", "")[:200], course.get("section", "")[:120], program, class_section,
                 session.get("admin_id"), now, len(rows), roster_id),
            )
            conn.execute("DELETE FROM classroom_roster_students WHERE roster_id=?", (roster_id,))
        else:
            cur = conn.execute(
                """INSERT INTO classroom_rosters(assessment_id,course_id,course_name,course_section,program,
                   class_section,imported_by_admin_id,imported_at,student_count)
                   VALUES (?,?,?,?,?,?,?,?,?) RETURNING id""",
                (assessment_id, course_id, course.get("name", "")[:200], course.get("section", "")[:120],
                 program, class_section, session.get("admin_id"), now, len(rows)),
            )
            roster_id = cur.fetchone()[0]
        for email, (first, last, gid) in rows.items():
            conn.execute(
                """INSERT INTO classroom_roster_students(roster_id,email,first_name,last_name,google_user_id)
                   VALUES (?,?,?,?,?)""",
                (roster_id, email, first, last, gid),
            )
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True, "imported": len(rows), "skipped": skipped})


@bp.post("/admin/assessment/<int:assessment_id>/classroom/<int:roster_id>/delete")
def classroom_roster_delete(assessment_id, roster_id):
    _require_admin()
    _require_csrf_header()
    conn = connect()
    try:
        conn.execute("DELETE FROM classroom_roster_students WHERE roster_id IN "
                     "(SELECT id FROM classroom_rosters WHERE id=? AND assessment_id=?)", (roster_id, assessment_id))
        conn.execute("DELETE FROM classroom_rosters WHERE id=? AND assessment_id=?", (roster_id, assessment_id))
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True})


# --------------------------------------------------------------------------
# Helpers used by the exam login and templates
# --------------------------------------------------------------------------

def rosters_for_assessment(conn, assessment_id):
    if not assessment_id:
        return []
    return conn.execute(
        "SELECT * FROM classroom_rosters WHERE assessment_id=? ORDER BY imported_at DESC", (assessment_id,)
    ).fetchall()


def roster_entry(conn, assessment_id, email):
    """(has_roster, entry). entry has first_name/last_name/program/class_section
    when the email is on one of the assessment's Classroom rosters."""
    if not assessment_id:
        return False, None
    has = conn.execute("SELECT 1 FROM classroom_rosters WHERE assessment_id=? LIMIT 1", (assessment_id,)).fetchone()
    if not has:
        return False, None
    entry = conn.execute(
        """SELECT s.first_name, s.last_name, r.program, r.class_section
           FROM classroom_roster_students s JOIN classroom_rosters r ON r.id=s.roster_id
           WHERE r.assessment_id=? AND s.email=? ORDER BY r.imported_at DESC LIMIT 1""",
        (assessment_id, email),
    ).fetchone()
    return True, entry


def csp_additions():
    """Google Identity Services sources to allow when the feature is on."""
    if not google_enabled():
        return {}
    return {
        "script-src": "https://accounts.google.com/gsi/client",
        "style-src": "https://accounts.google.com/gsi/style",
        "frame-src": "https://accounts.google.com/gsi/",
        "connect-src": "https://accounts.google.com/gsi/",
    }


def register(app):
    app.register_blueprint(bp)

    @app.context_processor
    def _google_context():
        return {
            "google_enabled": google_enabled(),
            "google_client_id": GOOGLE_CLIENT_ID,
            "google_student": google_student_identity(),
            "google_student_required": STUDENT_GOOGLE_LOGIN_REQUIRED,
            "google_allowed_domains": sorted(GOOGLE_ALLOWED_DOMAINS),
            "classroom_scopes": " ".join(CLASSROOM_SCOPES),
        }

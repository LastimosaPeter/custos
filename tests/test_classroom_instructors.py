"""Classroom-instructor mode (instructor_scope.py): Google + Classroom teacher
check, owners, school-domain aliases, per-course scoping, default-deny guard.
Google is faked at the network edge (tokeninfo, userinfo, Classroom)."""
import pytest

from conftest import CLIENT_ID

import app as custos  # noqa: E402
import google_integration as gi  # noqa: E402
from db import connect, iso_now  # noqa: E402

SCOPE = "openid https://www.googleapis.com/auth/userinfo.email " + " ".join(gi.ALL_CLASSROOM_SCOPES)
# token -> (email, name, courses taught)
PEOPLE = {
    "tok-teacher-a": ("teach.a@adnu.edu.ph", "Teacher A", [{"id": "c101", "name": "CSDC100", "section": "ZT11"}]),
    "tok-teacher-b": ("teach.b@gbox.adnu.edu.ph", "Teacher B", [{"id": "c202", "name": "CSDC102", "section": "ZS11"}]),
    "tok-student": ("stud.x@gbox.adnu.edu.ph", "Student X", []),
    "tok-owner2-alias": ("owner.two@adnu.edu.ph", "Owner Two", []),       # listed as @gbox -> same person
    "tok-kurt-alias": ("teacher@gbox.adnu.edu.ph", "Owner One", []),       # existing admin, other domain
}


class R:
    def __init__(self, status, data):
        self.status_code, self._d = status, data

    def json(self):
        return self._d


@pytest.fixture
def google(monkeypatch):
    state = {"people": {k: [v[0], v[1], list(v[2])] for k, v in PEOPLE.items()}}

    def fake_get(url, params=None, headers=None, timeout=None):
        tok = (params or {}).get("access_token") or (headers or {}).get("Authorization", "").replace("Bearer ", "")
        person = state["people"].get(tok)
        if url == gi.TOKENINFO_URL:
            if not person:
                return R(400, {})
            return R(200, {"aud": CLIENT_ID, "azp": CLIENT_ID, "email": person[0], "email_verified": "true", "scope": SCOPE})
        if url == gi.USERINFO_URL:
            info = {"name": person[1], "email": person[0]}
            domain = person[0].rsplit("@", 1)[1]
            if domain.endswith("adnu.edu.ph"):
                info["hd"] = domain  # Google includes hd for Workspace accounts
            return R(200, info)
        if url.endswith("/courses"):
            return R(200, {"courses": person[2]})
        raise AssertionError(url)

    monkeypatch.setattr(gi.requests, "get", fake_get)
    return state


@pytest.fixture
def client():
    custos.app.config["TESTING"] = True
    with custos.app.test_client() as c:
        yield c


def csrf(c):
    c.get("/login")
    with c.session_transaction() as s:
        return s["csrf_token"]


def sign_in(c, token):
    return c.post("/auth/google/instructor", json={"access_token": token}, headers={"X-CSRFToken": csrf(c)})


def owner_login(c):
    t = csrf(c)
    r = c.post("/admin/login", data={"username": "admin", "password": "test-admin-password-123", "csrf_token": t})
    assert r.status_code == 302
    with c.session_transaction() as s:
        return s["csrf_token"]


def new_assessment(c, subject_id, title):
    with c.session_transaction() as s:
        t = s["csrf_token"]
    c.post("/admin/workspace/assessment/add", data={"csrf_token": t, "subject_id": str(subject_id), "title": title,
                                                    "assessment_type": "custom", "duration_minutes": "30"})
    conn = connect()
    row = conn.execute("SELECT id FROM assessments WHERE title=?", (title,)).fetchone()
    conn.close()
    return row["id"] if row else None


def subject_for(course_id):
    conn = connect()
    row = conn.execute("SELECT subject_id FROM classroom_courses WHERE course_id=?", (course_id,)).fetchone()
    conn.close()
    return row["subject_id"] if row else None


# ------------------------------------------------------------------ sign-in

def test_single_sign_in_everywhere(client):
    r = client.get("/admin/login")
    assert r.status_code == 302 and r.headers["Location"].endswith("/login")
    assert 'name="password"' in client.get("/admin/login?password=1").get_data(as_text=True)  # owner emergency
    login = client.get("/login").get_data(as_text=True)
    assert "Sign in to Custos" in login and "data-google-signin" in login and 'name="session_key"' not in login
    home = client.get("/").get_data(as_text=True)
    assert "Sign in with Google" in home and "Go to Instructor View" not in home
    assert ">Instructor View<" not in home and ">Sign in<" in home


def test_non_adnu_teacher_refused(client, google):
    google["people"]["tok-gmail-teacher"] = ["someone@gmail.com", "Gmail Teacher", [{"id": "c909", "name": "X"}]]
    r = sign_in(client, "tok-gmail-teacher")
    assert r.status_code == 401 and "school Google account" in r.get_json()["error"]


def test_classroom_teacher_becomes_instructor_with_course_subject(client, google):
    r = sign_in(client, "tok-teacher-a")
    body = r.get_json()
    assert r.status_code == 200 and body["role"] == "instructor" and body["courses"] == 1
    with client.session_transaction() as s:
        assert s["admin_role"] == "instructor" and s["admin_auth_method"] == "google"
    conn = connect()
    subj = conn.execute("SELECT s.* FROM subjects s JOIN classroom_courses cc ON cc.subject_id=s.id WHERE cc.course_id='c101'").fetchone()
    admin = conn.execute("SELECT * FROM admins WHERE email='teach.a@adnu.edu.ph'").fetchone()
    link = conn.execute("""SELECT 1 FROM subject_instructors si JOIN instructors i ON i.id=si.instructor_id
                           WHERE i.admin_id=? AND si.subject_id=?""", (admin["id"], subj["id"])).fetchone()
    conn.close()
    assert subj["name"] == "CSDC100" and subj["code"] == "ZT11" and admin["role"] == "instructor" and link


def test_non_teacher_is_refused_and_no_account_created(client, google):
    r = sign_in(client, "tok-student")
    assert r.status_code == 403 and "isn't a teacher" in r.get_json()["error"]
    conn = connect()
    assert conn.execute("SELECT COUNT(*) FROM admins WHERE email LIKE 'stud.x@%'").fetchone()[0] == 0
    conn.close()


def test_forged_or_foreign_token_refused(client, google):
    assert sign_in(client, "not-a-real-token").status_code == 401
    google["people"]["tok-foreign"] = ["teach.a@adnu.edu.ph", "A", [{"id": "c101"}]]
    orig = gi.requests.get

    def foreign(url, params=None, headers=None, timeout=None):
        if url == gi.TOKENINFO_URL:
            return R(200, {"aud": "other-app", "azp": "other-app", "email": "teach.a@adnu.edu.ph", "email_verified": "true", "scope": SCOPE})
        return orig(url, params=params, headers=headers, timeout=timeout)

    gi.requests.get = foreign
    try:
        assert sign_in(client, "tok-foreign").status_code == 401
    finally:
        gi.requests.get = orig


def test_owner_via_alias_domain_needs_no_course(client, google):
    r = sign_in(client, "tok-owner2-alias")  # configured as owner.two@gbox..., signs in as @adnu
    assert r.status_code == 200 and r.get_json()["role"] == "owner"
    conn = connect()
    rows = conn.execute("SELECT email, role FROM admins WHERE email LIKE 'owner.two@%'").fetchall()
    conn.close()
    assert [tuple(r) for r in rows] == [("owner.two@adnu.edu.ph", "owner")]


def test_existing_owner_matched_across_domains_no_duplicate(client, google):
    conn = connect()
    conn.execute("UPDATE admins SET email='teacher@adnu.edu.ph' WHERE username='admin'")
    conn.commit(); conn.close()
    r = sign_in(client, "tok-kurt-alias")  # teacher@gbox... == teacher@adnu...
    assert r.status_code == 200 and r.get_json()["role"] == "owner"
    conn = connect()
    assert conn.execute("SELECT COUNT(*) FROM admins WHERE email LIKE 'teacher@%'").fetchone()[0] == 1
    conn.close()


def test_password_login_is_owner_only(client, google):
    sign_in(client, "tok-teacher-a")  # ensures the instructor account exists
    conn = connect()
    from werkzeug.security import generate_password_hash
    conn.execute("UPDATE admins SET password_hash=? WHERE email='teach.a@adnu.edu.ph'", (generate_password_hash("instructor-pw-123"),))
    uname = conn.execute("SELECT username FROM admins WHERE email='teach.a@adnu.edu.ph'").fetchone()["username"]
    conn.commit(); conn.close()
    client.get("/admin/logout")
    t = csrf(client)
    client.post("/admin/login", data={"username": uname, "password": "instructor-pw-123", "csrf_token": t})
    with client.session_transaction() as s:
        assert "admin_id" not in s
    owner_login(client)


def test_student_page_sends_known_instructor_to_recheck(client, google, monkeypatch):
    sign_in(client, "tok-teacher-a")
    client.get("/admin/logout")
    from google.oauth2 import id_token
    monkeypatch.setattr(id_token, "verify_oauth2_token", lambda *a, **k: {
        "iss": "accounts.google.com", "aud": CLIENT_ID, "email": "teach.a@adnu.edu.ph", "email_verified": True,
        "hd": "adnu.edu.ph", "sub": "s-a"})
    t = csrf(client)
    r = client.post("/auth/google/student", json={"credential": "x"}, headers={"X-CSRFToken": t})
    assert r.get_json()["role"] == "instructor_check" and "redirect" not in r.get_json()
    with client.session_transaction() as s:
        assert "admin_id" not in s  # not signed in until the Classroom re-check
        assert s["google_student"]["known_instructor"] is True
    page = client.get("/login").get_data(as_text=True)
    assert "Continue to my courses" in page and "Take an assessment instead" in page


def test_student_sees_im_a_teacher_link(client, google, monkeypatch):
    from google.oauth2 import id_token
    monkeypatch.setattr(id_token, "verify_oauth2_token", lambda *a, **k: {
        "iss": "accounts.google.com", "aud": CLIENT_ID, "email": "pupil.z@gbox.adnu.edu.ph", "email_verified": True,
        "hd": "gbox.adnu.edu.ph", "sub": "s-z", "name": "Pupil Z"})
    t = csrf(client)
    assert client.post("/auth/google/student", json={"credential": "x"}, headers={"X-CSRFToken": t}).get_json()["role"] == "student"
    page = client.get("/login").get_data(as_text=True)
    assert "I&#39;m a teacher" in page or "I'm a teacher" in page
    assert 'name="session_key"' in page and "Continue to my courses" not in page


# ------------------------------------------------------------------ scoping

def test_instructors_see_only_their_own_courses(client, google):
    # Teacher B builds an assessment in their course
    sign_in(client, "tok-teacher-b")
    b_subject = subject_for("c202")
    b_id = new_assessment(client, b_subject, "B Quiz")
    assert b_id
    client.get("/admin/logout")

    # Teacher A builds one in theirs
    sign_in(client, "tok-teacher-a")
    a_subject = subject_for("c101")
    a_id = new_assessment(client, a_subject, "A Quiz")
    assert a_id
    # ...and cannot create one in B's course
    assert new_assessment(client, b_subject, "Sneaky") is None

    hub = client.get("/admin").get_data(as_text=True)
    ws = client.get("/admin/workspace").get_data(as_text=True)
    assert "A Quiz" in hub and "B Quiz" not in hub and "Midterm Examination" not in hub
    assert "A Quiz" in ws and "B Quiz" not in ws and "Add Subject" not in ws and "Add Instructor" not in ws
    assert "Subjects &amp; instructors come from Google Classroom" in ws

    # direct access to B's things is "not found"; A's own page works
    assert client.get(f"/admin/assessment/{a_id}").status_code == 200
    assert client.get(f"/admin/assessment/{b_id}").status_code == 404
    assert client.get(f"/admin/assessment/{b_id}/export-scores").status_code == 404
    assert client.get(f"/admin/questions?assessment_id={b_id}").status_code == 404
    assert client.get("/admin?assessment=midterm").status_code == 404  # Peter's built-ins belong to the owner

    # attempts: monitor + session detail are scoped
    conn = connect()
    batch_b = conn.execute("SELECT id FROM batches WHERE assessment_id=?", (b_id,)).fetchone()
    if batch_b is None:
        import workspace
        batch_b = workspace._ensure_custom_batch(conn, conn.execute("SELECT * FROM assessments WHERE id=?", (b_id,)).fetchone())
    sid_b = conn.execute("""INSERT INTO exam_sessions(email,batch_id,assessment_id,started_at,status,is_test)
                            VALUES ('kid@adnu.edu.ph',?,?,?,'in_progress',0) RETURNING id""", (batch_b["id"], b_id, iso_now())).fetchone()[0]
    conn.commit(); conn.close()
    assert all(s["assessment_id"] != b_id for s in client.get("/admin/monitor/data").get_json()["students"])
    assert client.get(f"/admin/session/{sid_b}").status_code == 404
    assert client.get("/admin/messages/threads").status_code == 200

    # owner-only and unknown pages are refused
    for path in ("/admin/ide", "/admin/export/session-keys.csv?assessment=midterm"):
        assert client.get(path).status_code == 403, path
    client.get("/login")  # refresh csrf
    with client.session_transaction() as s:
        tok = s["csrf_token"]
    assert client.post("/admin/workspace/subject/add", data={"csrf_token": tok, "code": "X", "name": "Y"}).status_code == 403
    assert client.post("/admin/questions/add", data={"csrf_token": tok}).status_code == 403

    # the owner still sees everything
    client.get("/admin/logout")
    owner_login(client)
    hub = client.get("/admin").get_data(as_text=True)
    assert "A Quiz" in hub and "B Quiz" in hub
    assert client.get(f"/admin/session/{sid_b}").status_code == 200


def test_course_no_longer_taught_loses_access(client, google):
    sign_in(client, "tok-teacher-a")
    client.get("/admin/logout")
    google["people"]["tok-teacher-a"][2] = [{"id": "c303", "name": "CSDC200", "section": "ZT12"}]  # new term
    sign_in(client, "tok-teacher-a")
    old, new = subject_for("c101"), subject_for("c303")
    conn = connect()
    links = {r["subject_id"] for r in conn.execute(
        """SELECT si.subject_id FROM subject_instructors si JOIN instructors i ON i.id=si.instructor_id
           JOIN admins a ON a.id=i.admin_id WHERE a.email='teach.a@adnu.edu.ph'""").fetchall()}
    a_quiz = conn.execute("SELECT id FROM assessments WHERE title='A Quiz'").fetchone()
    conn.close()
    assert new in links and old not in links
    if a_quiz:
        assert client.get(f"/admin/assessment/{a_quiz['id']}").status_code == 404
    client.get("/admin/logout")
    google["people"]["tok-teacher-a"][2] = []
    assert sign_in(client, "tok-teacher-a").status_code == 403


def test_classroom_mode_off_keeps_classic_admin():
    """Google on, CLASSROOM_INSTRUCTORS off: password login + Add Subject/Instructor unchanged.
    Separate process because settings are read at import time."""
    import os
    import subprocess
    import sys

    from conftest import ROOT, TMP

    env = dict(os.environ, CLASSROOM_INSTRUCTORS="0", EXAM_DB_PATH=os.path.join(TMP, "classic.db"))
    code = (
        "import app; c=app.app.test_client(); h=c.get('/admin/login').get_data(as_text=True);"
        "assert 'name=\"password\"' in h and 'data-google-instructor-signin' not in h;"
        "c.get('/admin/login')\n"
        "with c.session_transaction() as s: t=s['csrf_token']\n"
        "c.post('/admin/login', data={'username':'admin','password':'test-admin-password-123','csrf_token':t})\n"
        "w=c.get('/admin/workspace').get_data(as_text=True); assert 'Add Subject' in w and 'Add Instructor' in w\n"
        "assert c.post('/auth/google/instructor', json={}).status_code in (400, 404); print('CLASSIC_OK')"
    )
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    assert "CLASSIC_OK" in out.stdout, out.stderr[-2000:]


def test_courses_sharing_a_section_name_both_become_subjects(client, google):
    google["people"]["tok-teacher-c"] = ["teach.c@adnu.edu.ph", "Teacher C", [
        {"id": "c501", "name": "CSDC100", "section": "ZT11"},
        {"id": "c502", "name": "MIT 201", "section": "ZT11"},
        {"id": "c503", "name": "No section"},
    ]]
    r = sign_in(client, "tok-teacher-c")
    assert r.status_code == 200 and r.get_json()["courses"] == 3
    conn = connect()
    codes = sorted(row["code"] for row in conn.execute(
        """SELECT s.code FROM subjects s JOIN classroom_courses cc ON cc.subject_id=s.id
           WHERE cc.course_id IN ('c501','c502','c503')""").fetchall())
    conn.close()
    assert len(set(codes)) == 3 and codes[0].startswith("No section")
    # signing in again is stable (no new subjects, no errors)
    client.get("/admin/logout")
    assert sign_in(client, "tok-teacher-c").status_code == 200
    conn = connect()
    assert conn.execute("""SELECT COUNT(DISTINCT subject_id) FROM classroom_courses
                           WHERE course_id IN ('c501','c502','c503')""").fetchone()[0] == 3
    conn.close()



# ------------------------------------------------------------------ ADNU course names

import instructor_scope  # noqa: E402


@pytest.mark.parametrize("name,expected", [
    ("2026-1 CSDC100.ZC11Am", ("CSDC100", "1st Semester", "2026-2027", "ZC", "11")),
    ("2026-2 CSDC100.ZC12Af", ("CSDC100", "2nd Semester", "2026-2027", "ZC", "12")),
    ("2025-3 CSDC101.ZT11", ("CSDC101", "Intersession", "2025-2026", "ZT", "11")),
    ("2026.1 csdc 101 zt-12", ("CSDC101", "1st Semester", "2026-2027", "ZT", "12")),
    ("CSDC100", None),
    ("MIT 201 Research Methods", None),
])
def test_parse_adnu_course_names(name, expected):
    p = instructor_scope.parse_course_name(name)
    assert (None if p is None else (p["code"], p["term"], p["school_year"], p["program"], p["class_section"])) == expected


def test_sections_share_a_subject_per_year_and_term(client, google):
    google["people"]["tok-teacher-d"] = ["teach.d@adnu.edu.ph", "Teacher D", [
        {"id": "d1", "name": "2026-1 CSDC100.ZC11Am"},
        {"id": "d2", "name": "2026-1 CSDC100.ZC12Af"},
        {"id": "d3", "name": "2025-1 CSDC100.ZC11"},  # last year's ZC11: a different subject
    ]]
    r = sign_in(client, "tok-teacher-d")
    assert r.status_code == 200 and r.get_json()["courses"] == 2
    assert subject_for("d1") == subject_for("d2") != subject_for("d3")
    conn = connect()
    row = conn.execute("SELECT code, term, school_year FROM subjects WHERE id=?", (subject_for("d1"),)).fetchone()
    old = conn.execute("SELECT school_year FROM subjects WHERE id=?", (subject_for("d3"),)).fetchone()
    sec = conn.execute("SELECT program, class_section FROM classroom_courses WHERE course_id='d2'").fetchone()
    conn.close()
    assert tuple(row) == ("CSDC100", "1st Semester", "2026-2027") and old["school_year"] == "2025-2026"
    assert tuple(sec) == ("ZC", "12")


def test_roster_import_takes_section_from_course_name(client, google, monkeypatch):
    # Owner imports the roster of an ADNU-named course without choosing a section.
    owner_login(client)
    with client.session_transaction() as s:
        t = s["csrf_token"]
    conn = connect()
    aid = conn.execute("""INSERT INTO assessments(subject_id,title,slug,assessment_type,display_type,access_code,active,created_at)
                          VALUES ((SELECT id FROM subjects LIMIT 1),'ZC Quiz','zc-quiz','custom','Quiz','ZC-KEY-1',1,?) RETURNING id""",
                       (iso_now(),)).fetchone()[0]
    conn.commit(); conn.close()
    course = {"id": "zc11", "name": "2026-1 CSDC100.ZC11Am"}

    def fake_get(url, params=None, headers=None, timeout=None):
        if url == gi.TOKENINFO_URL:
            return R(200, {"aud": CLIENT_ID, "scope": SCOPE})
        if url.endswith("/courses"):
            return R(200, {"courses": [course]})
        return R(200, {"students": [{"userId": "z1", "profile": {"id": "z1", "emailAddress": "zc.kid@gbox.adnu.edu.ph",
                                                                  "name": {"givenName": "Zee", "familyName": "Cee"}}}]})
    monkeypatch.setattr(gi.requests, "get", fake_get)
    listed = client.post(f"/admin/assessment/{aid}/classroom/courses", json={"access_token": "t"}, headers={"X-CSRFToken": t}).get_json()
    assert listed["courses"][0]["custos_section"] == "ZC11"
    r = client.post(f"/admin/assessment/{aid}/classroom/import", json={"access_token": "t", "course_id": "zc11"},
                    headers={"X-CSRFToken": t}).get_json()
    assert r["ok"] and r["section"] == "ZC11" and r["imported"] == 1
    conn = connect()
    row = conn.execute("""SELECT r.program, r.class_section, s.email FROM classroom_rosters r
                          JOIN classroom_roster_students s ON s.roster_id=r.id WHERE r.assessment_id=?""", (aid,)).fetchone()
    conn.close()
    assert tuple(row) == ("ZC", "11", "zc.kid@adnu.edu.ph")  # gbox stored as the canonical adnu identity

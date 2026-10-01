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

def test_separate_student_and_instructor_sign_in(client):
    # Hercules: Student View and Instructor View are separate entry points.
    r = client.get("/admin/login")
    page = r.get_data(as_text=True)
    assert r.status_code == 200 and "data-google-instructor-signin" in page and "/auth/google/instructor" in page
    assert 'name="password"' not in page
    assert 'name="password"' in client.get("/admin/login?password=1").get_data(as_text=True)  # owner emergency
    login = client.get("/login").get_data(as_text=True)
    assert "Sign in to Custos" in login and "data-google-signin" in login and 'name="session_key"' not in login
    assert "Go to Instructor View" in login
    assert "/admin/login" in client.get("/").get_data(as_text=True)


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


def test_student_view_signs_known_instructor_in_as_student(client, google, monkeypatch):
    sign_in(client, "tok-teacher-a")
    client.get("/admin/logout")
    from google.oauth2 import id_token
    monkeypatch.setattr(id_token, "verify_oauth2_token", lambda *a, **k: {
        "iss": "accounts.google.com", "aud": CLIENT_ID, "email": "teach.a@adnu.edu.ph", "email_verified": True,
        "hd": "adnu.edu.ph", "sub": "s-a"})
    t = csrf(client)
    r = client.post("/auth/google/student", json={"credential": "x"}, headers={"X-CSRFToken": t})
    # Student View never grants instructor access; teachers use Instructor View.
    assert r.get_json()["role"] == "student" and r.get_json()["redirect"] == "/student"
    with client.session_transaction() as s:
        assert "admin_id" not in s
        assert s["google_student"]["known_instructor"] is False
    assert client.get("/login").headers["Location"].endswith("/student")


def test_student_lands_on_my_assessments(client, google, monkeypatch):
    from google.oauth2 import id_token
    monkeypatch.setattr(id_token, "verify_oauth2_token", lambda *a, **k: {
        "iss": "accounts.google.com", "aud": CLIENT_ID, "email": "pupil.z@gbox.adnu.edu.ph", "email_verified": True,
        "hd": "gbox.adnu.edu.ph", "sub": "s-z", "name": "Pupil Z"})
    t = csrf(client)
    assert client.post("/auth/google/student", json={"credential": "x"}, headers={"X-CSRFToken": t}).get_json()["role"] == "student"
    assert client.get("/login").headers["Location"].endswith("/student")
    dashboard = client.get("/student").get_data(as_text=True)
    assert "My Assessments" in dashboard and 'name="session_key"' in dashboard
    assert "Go to Instructor View" in client.get("/login?force=1").get_data(as_text=True)


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

    # an owner sees everything after confirming "Show all"
    client.get("/admin/logout")
    t = owner_login(client)
    client.post("/admin/view-all", data={"csrf_token": t, "mode": "all", "confirm": "oo"})
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
    ("2026-1 CSDC100.zc11am", ("CSDC100", "1st Semester", "2026-2027", "ZC", "11")),
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


# ------------------------------------------------------------------ editing class details

def _edit(client, course_id, **fields):
    with client.session_transaction() as s:
        t = s["csrf_token"]
    data = {"csrf_token": t, "school_year": "2026-2027", "term": "1st Semester", "code": "CSDC199",
            "title": "Special Topics", "section": "ZC21"}
    data.update(fields)
    return client.post(f"/admin/classroom/course/{course_id}/edit", data=data)


def _course(course_id):
    conn = connect()
    row = conn.execute("""SELECT cc.*, s.code, s.name AS title, s.term, s.school_year, s.active
                          FROM classroom_courses cc JOIN subjects s ON s.id=cc.subject_id WHERE cc.course_id=?""",
                       (course_id,)).fetchone()
    conn.close()
    return row


def test_teacher_edits_class_without_section_and_edit_sticks(client, google):
    google["people"]["tok-teacher-e"] = ["teach.e@adnu.edu.ph", "Teacher E", [{"id": "e1", "name": "Special Topics"}]]
    sign_in(client, "tok-teacher-e")
    before = _course("e1")
    assert before["school_year"] == "" and before["program"] is None
    page = client.get("/admin/workspace").get_data(as_text=True)
    assert "My Google Classroom classes" in page and "Special Topics" in page
    r = _edit(client, "e1", section="zc21am")
    assert r.status_code == 302
    after = _course("e1")
    assert after["subject_id"] == before["subject_id"]  # renamed in place
    assert (after["code"], after["title"], after["term"], after["school_year"], after["program"], after["class_section"], after["manual"]) == \
        ("CSDC199", "Special Topics", "1st Semester", "2026-2027", "ZC", "21", 1)
    client.get("/admin/logout")
    sign_in(client, "tok-teacher-e")  # next sign-in must not overwrite the edit
    again = _course("e1")
    assert (again["code"], again["program"], again["class_section"]) == ("CSDC199", "ZC", "21")


def test_bad_edits_are_rejected_without_changes(client, google):
    google["people"]["tok-teacher-f"] = ["teach.f@adnu.edu.ph", "Teacher F", [{"id": "f1", "name": "Elective"}]]
    sign_in(client, "tok-teacher-f")
    before = tuple(_course("f1"))
    for bad in ({"school_year": "26-27"}, {"school_year": "2026-2028"}, {"section": "Section A"},
                {"code": "C"}, {"term": "Summer"}):
        _edit(client, "f1", **bad)
        assert tuple(_course("f1")) == before, bad


def test_cannot_edit_a_course_you_do_not_teach(client, google):
    google["people"]["tok-teacher-g"] = ["teach.g@adnu.edu.ph", "Teacher G", [{"id": "g1", "name": "G class"}]]
    google["people"]["tok-teacher-h"] = ["teach.h@adnu.edu.ph", "Teacher H", [{"id": "h1", "name": "H class"}]]
    sign_in(client, "tok-teacher-g")
    client.get("/admin/logout")
    sign_in(client, "tok-teacher-h")
    assert _edit(client, "g1").status_code == 404
    assert "G class" not in client.get("/admin/workspace").get_data(as_text=True)
    client.get("/admin/logout")
    owner_login(client)  # owners can edit any class
    assert _edit(client, "g1", code="CSDC777", section="ZT31").status_code == 302
    assert _course("g1")["code"] == "CSDC777"


def test_merging_into_existing_subject_moves_assessments_and_rosters(client, google):
    google["people"]["tok-teacher-i"] = ["teach.i@adnu.edu.ph", "Teacher I", [
        {"id": "i1", "name": "2026-1 CSDC300.ZT11Am"}, {"id": "i2", "name": "Loose class"}]]
    sign_in(client, "tok-teacher-i")
    loose_subject = _course("i2")["subject_id"]
    quiz = new_assessment(client, loose_subject, "Loose Quiz")
    conn = connect()
    conn.execute("""INSERT INTO classroom_rosters(assessment_id,course_id,course_name,program,class_section,imported_at,student_count)
                    VALUES (?,?,?,?,?,?,0)""", (quiz, "i2", "Loose class", "ZT", "99", iso_now()))
    conn.commit(); conn.close()
    # Point the loose class at CSDC300 2026-1 (already exists from i1), section ZT12.
    _edit(client, "i2", code="CSDC300", title="Data Structures", section="ZT12")
    target = _course("i1")["subject_id"]
    conn = connect()
    moved = conn.execute("SELECT subject_id FROM assessments WHERE id=?", (quiz,)).fetchone()["subject_id"]
    old_active = conn.execute("SELECT active FROM subjects WHERE id=?", (loose_subject,)).fetchone()["active"]
    roster = conn.execute("SELECT program, class_section FROM classroom_rosters WHERE course_id='i2'").fetchone()
    conn.close()
    assert _course("i2")["subject_id"] == target and moved == target and old_active == 0
    assert tuple(roster) == ("ZT", "12")
    assert client.get(f"/admin/assessment/{quiz}").status_code == 200  # still theirs



def test_owner_can_sync_their_own_classroom_classes(client, google):
    google["people"]["tok-owner2-alias"][2] = [{"id": "o1", "name": "2026-2 CSDC100.ZC11Am"}]
    owner_login(client)
    page = client.get("/admin/workspace").get_data(as_text=True)
    assert "Sync my Google Classroom classes" in page and "accounts.google.com/gsi/client" in page
    r = sign_in(client, "tok-owner2-alias")  # the Sync button uses the same Classroom sign-in
    assert r.status_code == 200 and r.get_json()["role"] == "owner" and r.get_json()["courses"] == 1
    c = _course("o1")
    assert (c["code"], c["term"], c["school_year"], c["program"], c["class_section"]) == ("CSDC100", "2nd Semester", "2026-2027", "ZC", "11")
    assert "2026-2 CSDC100.ZC11Am" in client.get("/admin/workspace").get_data(as_text=True)


# ------------------------------------------------------------------ class list: semester filter, paging, archive

def _rows(html):
    return html.count('class="classroom-class-row"')


@pytest.fixture
def teacher_p(client, google):
    courses = [{"id": f"p5{n}", "name": f"2027-1 CSDC500.ZT{n}Am"} for n in range(11, 23)]  # 12 sections, latest term
    courses += [{"id": "p4a", "name": "2026-2 CSDC400.ZC11"}, {"id": "p4b", "name": "2026-2 CSDC400.ZC12Af"},
                {"id": "pold", "name": "Old seminar"}]
    google["people"]["tok-teacher-p"] = ["teach.p@adnu.edu.ph", "Teacher P", courses]
    assert sign_in(client, "tok-teacher-p").status_code == 200
    return client


def test_default_is_latest_semester_ten_per_page(teacher_p):
    html = teacher_p.get("/admin/workspace").get_data(as_text=True)
    assert "2027-2028 · 1st Semester (latest)" in html and "12 sections" in html
    assert _rows(html) == 10 and "Page 1 of 2" in html
    assert "<strong>CSDC500 ZT11</strong>" in html and "CSDC400" not in html.split("classroom-class-list")[1]
    for opt in ('value="2027-2028"', 'value="2026-2027"', "Needs details (1)", 'value="25"', 'value="100"'):
        assert opt in html
    page2 = teacher_p.get("/admin/workspace?year=2027-2028&term=1st+Semester&size=10&page=2").get_data(as_text=True)
    assert _rows(page2) == 2 and "Page 2 of 2" in page2


def test_page_sizes_and_other_semesters(teacher_p):
    assert _rows(teacher_p.get("/admin/workspace?size=25").get_data(as_text=True)) == 12
    assert _rows(teacher_p.get("/admin/workspace?size=13").get_data(as_text=True)) == 10  # only 10/25/50/100
    older = teacher_p.get("/admin/workspace?year=2026-2027&term=2nd+Semester").get_data(as_text=True)
    assert _rows(older) == 2 and "<strong>CSDC400 ZC11</strong>" in older and "<strong>CSDC400 ZC12</strong>" in older
    # a year without that semester falls back to that year's newest semester
    assert _rows(teacher_p.get("/admin/workspace?year=2026-2027&term=1st+Semester").get_data(as_text=True)) == 2
    todo = teacher_p.get("/admin/workspace?year=needs-details").get_data(as_text=True)
    assert _rows(todo) == 1 and "Old seminar" in todo


def test_archive_and_restore_keep_the_current_view(teacher_p):
    with teacher_p.session_transaction() as s:
        t = s["csrf_token"]
    back = "/admin/workspace?year=2026-2027&term=2nd+Semester"
    r = teacher_p.post("/admin/classroom/course/p4b/archive", data={"csrf_token": t, "back": back})
    assert r.status_code == 302 and r.headers["Location"].endswith(back + "#classroom-classes")
    assert _rows(teacher_p.get(back).get_data(as_text=True)) == 1
    archived = teacher_p.get(back + "&archived=1").get_data(as_text=True)
    assert _rows(archived) == 1 and "CSDC400 ZC12" in archived and "Restore" in archived
    conn = connect()
    assert conn.execute("SELECT COUNT(*) FROM classroom_courses WHERE course_id='p4b'").fetchone()[0] == 1  # not deleted
    conn.close()
    r = teacher_p.post("/admin/classroom/course/p4b/unarchive", data={"csrf_token": t, "back": "https://evil.example/x"})
    assert r.headers["Location"].endswith("/admin/workspace#classroom-classes")  # never leaves Custos
    assert _rows(teacher_p.get(back).get_data(as_text=True)) == 2


def test_other_teacher_cannot_archive(teacher_p, google):
    teacher_p.get("/admin/logout")
    google["people"]["tok-teacher-q"] = ["teach.q@adnu.edu.ph", "Teacher Q", [{"id": "q1", "name": "2027-1 CSDC900.ZT11"}]]
    sign_in(teacher_p, "tok-teacher-q")
    with teacher_p.session_transaction() as s:
        t = s["csrf_token"]
    assert teacher_p.post("/admin/classroom/course/p4a/archive", data={"csrf_token": t}).status_code == 404
    html = teacher_p.get("/admin/workspace").get_data(as_text=True)
    assert _rows(html) == 1 and "CSDC900 ZT11" in html and "CSDC500" not in html



# ------------------------------------------------------------------ owners: only mine by default, "Show all" on confirm

def test_owners_see_only_their_own_until_show_all(client, google):
    google["people"]["tok-teacher-r"] = ["teach.r@adnu.edu.ph", "Teacher R", [{"id": "r1", "name": "2027-2 CSDC777.ZT11"}]]
    sign_in(client, "tok-teacher-r")
    r_quiz = new_assessment(client, subject_for("r1"), "R Private Quiz")
    client.get("/admin/logout")
    google["people"]["tok-owner2-alias"][2] = [{"id": "o7", "name": "2027-2 CSDC888.ZC11"}]
    assert sign_in(client, "tok-owner2-alias").get_json()["role"] == "owner"
    own_quiz = new_assessment(client, subject_for("o7"), "Owner Two Quiz")
    assert r_quiz and own_quiz
    hub = client.get("/admin").get_data(as_text=True)
    ws = client.get("/admin/workspace?sy=2027-2028&st=2nd+Semester").get_data(as_text=True)
    assert "Owner Two Quiz" in hub and "R Private Quiz" not in hub
    assert "CSDC888" in ws and "CSDC777" not in ws
    # side button + modal, owners only
    assert "data-owner-view-all-open" in ws and "Sure ka dyan? Lalaki ang listahan." in ws
    with client.session_transaction() as s:
        t = s["csrf_token"]
    # without the modal's confirmation nothing changes
    assert client.post("/admin/view-all", data={"csrf_token": t, "mode": "all"}).status_code == 400
    r = client.post("/admin/view-all", data={"csrf_token": t, "mode": "all", "confirm": "oo", "back": "/admin"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/admin")
    hub = client.get("/admin").get_data(as_text=True)
    assert "R Private Quiz" in hub and "Owner Two Quiz" in hub and "Back to mine" in hub
    assert "CSDC777" in client.get("/admin/workspace?sy=2027-2028&st=2nd+Semester").get_data(as_text=True)
    client.post("/admin/view-all", data={"csrf_token": t, "mode": "mine", "back": "https://evil.example"})
    assert "R Private Quiz" not in client.get("/admin").get_data(as_text=True)


def test_instructors_cannot_show_all(client, google):
    google["people"]["tok-teacher-s"] = ["teach.s@adnu.edu.ph", "Teacher S", [{"id": "s1", "name": "2027-2 CSDC555.ZT11"}]]
    sign_in(client, "tok-teacher-s")
    ws = client.get("/admin/workspace").get_data(as_text=True)
    assert "data-owner-view-all-open" not in ws and "Sure ka dyan" not in ws
    with client.session_transaction() as s:
        t = s["csrf_token"]
    assert client.post("/admin/view-all", data={"csrf_token": t, "mode": "all", "confirm": "oo"}).status_code == 403
    with client.session_transaction() as s:
        assert not s.get("owner_view_all")


def test_subjects_list_latest_semester_and_paging(client, google):
    courses = [{"id": f"t{n}", "name": f"2028-1 CSDC{n}.ZT11"} for n in range(300, 312)]  # 12 subjects, latest term
    courses += [{"id": "told", "name": "2027-1 CSDC299.ZT11"}]
    google["people"]["tok-owner2-alias"][2] = courses  # the Subjects section is an owner tool
    assert sign_in(client, "tok-owner2-alias").get_json()["role"] == "owner"
    ws = client.get("/admin/workspace").get_data(as_text=True)
    subjects_block = ws.split("subject-filter-bar")[1].split("</section>")[0]
    assert "2028-2029 · 1st Semester (latest) · 12 subjects" in subjects_block and "Page 1 of 2" in subjects_block
    assert "CSDC300" in subjects_block and "CSDC299" not in subjects_block
    older = client.get("/admin/workspace?sy=2027-2028&st=1st+Semester").get_data(as_text=True).split("subject-filter-bar")[1]
    assert "CSDC299" in older.split("</section>")[0]
    assert "Page" not in client.get("/admin/workspace?ss=25").get_data(as_text=True).split("subject-filter-bar")[1].split("</section>")[0]

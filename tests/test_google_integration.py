"""Tests for Google sign-in + Google Classroom roster import (google_integration.py).

Google itself is mocked at the network edge only: google.oauth2's ID-token
verifier and the HTTP calls to tokeninfo/Classroom. Every Custos-side check
(domains, verified email, token audience/scopes, roster enforcement) runs for real.

Run:  pytest -q tests/test_google_integration.py
"""
import os
import re
import subprocess
import sys
import tempfile

import pytest

from conftest import CLIENT_ID, ROOT, TMP as _tmp  # noqa: E402  (settings live in conftest.py)

import app as custos  # noqa: E402
import google_integration as gi  # noqa: E402
from db import connect, iso_now  # noqa: E402

ACCESS_KEY = "CUSTOM-TEST-KEY1"
CLASSROOM_SCOPES = " ".join(gi.CLASSROOM_SCOPES)


# --------------------------------------------------------------------------- fixtures

@pytest.fixture(scope="module")
def assessment_id():
    import workspace

    conn = connect()
    sid = conn.execute(
        "INSERT INTO subjects(code,name,term,school_year,active,created_at) VALUES ('CSDC101','Test','1','2026',1,?) RETURNING id",
        (iso_now(),),
    ).fetchone()[0]
    aid = conn.execute(
        """INSERT INTO assessments(subject_id,title,slug,assessment_type,display_type,access_code,active,created_at)
           VALUES (?, 'Google Test Quiz', 'google-test-quiz', 'custom', 'Quiz', ?, 1, ?) RETURNING id""",
        (sid, ACCESS_KEY, iso_now()),
    ).fetchone()[0]
    assessment = conn.execute("SELECT * FROM assessments WHERE id=?", (aid,)).fetchone()
    batch = workspace._ensure_custom_batch(conn, assessment)
    conn.execute(
        """INSERT INTO questions(part,batch_slot,topic,prompt,code,option_a,option_b,option_c,option_d,
           correct_option,explanation,points,position,active,created_by,subject_id,assessment_id)
           VALUES (1,?, 'T', '2+2?', '', '3', '4', '5', '6', 'B', '', 1, 1, 1, 'instructor', ?, ?)""",
        (batch["slot"], sid, aid),
    )
    conn.execute("UPDATE admins SET email='teacher@adnu.edu.ph' WHERE username='admin'")
    conn.commit()
    conn.close()
    return aid


@pytest.fixture
def client():
    custos.app.config["TESTING"] = True
    with custos.app.test_client() as c:
        yield c


def _csrf(client):
    client.get("/login")
    with client.session_transaction() as s:
        return s["csrf_token"]


def _claims(email, hd=None, verified=True, **extra):
    c = {"iss": "https://accounts.google.com", "aud": CLIENT_ID, "email": email, "email_verified": verified,
         "sub": "sub-" + email.split("@")[0], "given_name": "Gina", "family_name": "Google", "name": "Gina Google"}
    if hd is not None:
        c["hd"] = hd
    c.update(extra)
    return c


@pytest.fixture
def google_token(monkeypatch):
    """Map fake credential strings to claims; anything else fails verification."""
    registry = {}

    def fake_verify(credential, request, audience, clock_skew_in_seconds=0):
        assert audience == CLIENT_ID
        if credential not in registry:
            raise ValueError("bad token")
        return dict(registry[credential])

    from google.oauth2 import id_token
    monkeypatch.setattr(id_token, "verify_oauth2_token", fake_verify)
    return registry


class FakeResp:
    def __init__(self, status, data):
        self.status_code, self._data = status, data

    def json(self):
        return self._data


@pytest.fixture
def google_api(monkeypatch):
    """Fake tokeninfo + Classroom. state is mutable per test."""
    state = {
        "tokeninfo": {"aud": CLIENT_ID, "azp": CLIENT_ID, "scope": CLASSROOM_SCOPES},
        "courses": [{"id": "111", "name": "CSDC101", "section": "ZT-11"}],
        "students": {"111": [
            {"userId": "u1", "profile": {"id": "u1", "emailAddress": "ana@gbox.adnu.edu.ph",
                                         "name": {"givenName": "Ana", "familyName": "Roster"}}},
            {"userId": "u2", "profile": {"id": "u2", "emailAddress": "ben@adnu.edu.ph",
                                         "name": {"givenName": "Ben", "familyName": "Roster"}}},
            {"userId": "u3", "profile": {"id": "u3", "emailAddress": "outsider@gmail.com",
                                         "name": {"givenName": "Out", "familyName": "Sider"}}},
        ]},
        "calls": [],
    }

    def fake_get(url, params=None, headers=None, timeout=None):
        state["calls"].append(url)
        if url == gi.TOKENINFO_URL:
            return FakeResp(200, state["tokeninfo"]) if params.get("access_token") == "good-token" else FakeResp(400, {})
        assert headers["Authorization"] == "Bearer good-token"
        if url.endswith("/courses"):
            return FakeResp(200, {"courses": state["courses"]})
        m = re.search(r"/courses/([^/]+)/students$", url)
        return FakeResp(200, {"students": state["students"].get(m.group(1), [])})

    monkeypatch.setattr(gi.requests, "get", fake_get)
    return state


def _student_signin(client, registry, email, hd):
    registry[f"cred-{email}"] = _claims(email, hd=hd)
    csrf = _csrf(client)
    return client.post("/auth/google/student", json={"credential": f"cred-{email}"}, headers={"X-CSRFToken": csrf})


def _admin_login(client):
    csrf = _csrf(client)
    r = client.post("/admin/login", data={"username": "admin", "password": "test-admin-password-123", "csrf_token": csrf})
    assert r.status_code == 302
    with client.session_transaction() as s:
        return s["csrf_token"]


def _exam_login(client, form=None):
    with client.session_transaction() as s:
        csrf = s["csrf_token"]
    data = {"csrf_token": csrf, "first_name": "Typed", "last_name": "Name", "program": "ZT",
            "class_section": "11", "session_key": ACCESS_KEY}
    data.update(form or {})
    return client.post("/login", data=data)


# --------------------------------------------------------------------------- pages / headers

def test_login_page_shows_google_button_and_hides_form(client):
    html = client.get("/login").get_data(as_text=True)
    assert "accounts.google.com/gsi/client" in html
    assert "data-google-signin" in html and CLIENT_ID in html
    assert 'name="session_key"' not in html  # form hidden until signed in
    assert 'name="email"' not in html


def test_csp_allows_google_identity_services_and_referrer_only_on_signin_pages(client):
    r = client.get("/login")
    csp = r.headers["Content-Security-Policy"]
    assert "https://accounts.google.com/gsi/client" in csp and "frame-src https://accounts.google.com/gsi/" in csp
    assert r.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert client.get("/").headers["Referrer-Policy"] == "no-referrer"


# --------------------------------------------------------------------------- student sign-in

def test_student_signin_requires_csrf(client, google_token):
    google_token["c"] = _claims("ana@adnu.edu.ph", hd="adnu.edu.ph")
    client.get("/login")
    assert client.post("/auth/google/student", json={"credential": "c"}).status_code == 400


@pytest.mark.parametrize("email,hd", [("ana@adnu.edu.ph", "adnu.edu.ph"), ("ana@gbox.adnu.edu.ph", "gbox.adnu.edu.ph")])
def test_student_signin_accepts_both_school_domains(client, google_token, email, hd):
    r = _student_signin(client, google_token, email, hd)
    canonical = email.replace("@gbox.adnu.edu.ph", "@adnu.edu.ph")  # one identity across aliased domains
    assert r.status_code == 200 and r.get_json()["email"] == canonical
    html = client.get("/login").get_data(as_text=True)
    assert canonical in html and 'name="session_key"' in html
    # identity comes from Google: no name/email/section fields to fill in
    for field in ('name="email"', 'name="first_name"', 'name="last_name"', 'name="program"'):
        assert field not in html


@pytest.mark.parametrize("email,hd", [
    ("someone@gmail.com", None),              # consumer account
    ("spoof@adnu.edu.ph", None),              # no Workspace hd claim
    ("x@evil.com", "adnu.edu.ph"),            # hd mismatch with email domain
    ("x@notadnu.edu.ph", "notadnu.edu.ph"),   # other Workspace domain
])
def test_student_signin_rejects_non_school_accounts(client, google_token, email, hd):
    r = _student_signin(client, google_token, email, hd)
    assert r.status_code == 401 and "school Google account" in r.get_json()["error"]
    with client.session_transaction() as s:
        assert "google_student" not in s


def test_student_signin_rejects_unverified_email_and_bad_token(client, google_token):
    google_token["unverified"] = _claims("ana@adnu.edu.ph", hd="adnu.edu.ph", verified=False)
    csrf = _csrf(client)
    assert client.post("/auth/google/student", json={"credential": "unverified"}, headers={"X-CSRFToken": csrf}).status_code == 401
    assert client.post("/auth/google/student", json={"credential": "forged"}, headers={"X-CSRFToken": csrf}).status_code == 401
    assert client.post("/auth/google/student", json={"credential": "x" * 5000}, headers={"X-CSRFToken": csrf}).status_code == 401


def test_exam_login_requires_google_when_required(client, assessment_id):
    _csrf(client)
    r = _exam_login(client, {"email": "typed@adnu.edu.ph"})
    assert r.status_code == 200 and "Sign in with your school Google account first" in r.get_data(as_text=True)


def test_typed_identity_is_ignored_and_google_profile_used(client, google_token, assessment_id):
    _student_signin(client, google_token, "cara@adnu.edu.ph", "adnu.edu.ph")
    r = _exam_login(client, {"email": "someone.else@adnu.edu.ph", "first_name": "Fake", "last_name": "Name"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/instructions")
    with client.session_transaction() as s:
        assert s["pending_email"] == "cara@adnu.edu.ph"
        assert s["pending_google_sub"] == "sub-cara"
        assert (s["pending_first_name"], s["pending_last_name"]) == ("Gina", "Google")


def test_no_roster_asks_for_section_only_after_key(client, google_token, assessment_id):
    _student_signin(client, google_token, "gus@adnu.edu.ph", "adnu.edu.ph")
    with client.session_transaction() as s:
        csrf = s["csrf_token"]
    r = client.post("/login", data={"csrf_token": csrf, "session_key": ACCESS_KEY})
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "linked to Google Classroom yet" in html
    assert 'name="program"' in html and f'value="{ACCESS_KEY}"' in html
    r = client.post("/login", data={"csrf_token": csrf, "session_key": ACCESS_KEY, "program": "ZS", "class_section": "11"})
    assert r.status_code == 302
    with client.session_transaction() as s:
        assert (s["pending_program"], s["pending_class_section"]) == ("ZS", "11")


def test_instructor_email_on_student_page_goes_to_workspace(client, google_token):
    google_token["t2"] = _claims("teacher@adnu.edu.ph", hd="adnu.edu.ph")
    csrf = _csrf(client)
    r = client.post("/auth/google/student", json={"credential": "t2"}, headers={"X-CSRFToken": csrf})
    body = r.get_json()
    assert r.status_code == 200 and body["role"] == "instructor" and body["redirect"].endswith("/admin/workspace")
    with client.session_transaction() as s:
        assert s["admin_id"] and "google_student" not in s


def test_start_records_google_auth_method(client, google_token, assessment_id):
    _student_signin(client, google_token, "dina@adnu.edu.ph", "adnu.edu.ph")
    _exam_login(client)
    with client.session_transaction() as s:
        csrf = s["csrf_token"]
    r = client.post("/start", data={"csrf_token": csrf, "terms_accept": "yes"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/exam")
    conn = connect()
    row = conn.execute("SELECT auth_method, google_sub FROM exam_sessions WHERE email='dina@adnu.edu.ph'").fetchone()
    conn.close()
    assert row["auth_method"] == "google" and row["google_sub"] == "sub-dina"


def test_start_rejected_if_google_identity_changed(client, google_token, assessment_id):
    _student_signin(client, google_token, "eve@adnu.edu.ph", "adnu.edu.ph")
    _exam_login(client)
    with client.session_transaction() as s:
        s["google_student"] = dict(s["google_student"], email="mallory@adnu.edu.ph")
        csrf = s["csrf_token"]
    r = client.post("/start", data={"csrf_token": csrf, "terms_accept": "yes"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/login")


def test_student_logout_forgets_google_identity(client, google_token):
    _student_signin(client, google_token, "fay@adnu.edu.ph", "adnu.edu.ph")
    client.get("/logout")
    with client.session_transaction() as s:
        assert "google_student" not in s


# --------------------------------------------------------------------------- instructor sign-in

def test_admin_google_signin_matches_account_email(client, google_token):
    google_token["t"] = _claims("teacher@adnu.edu.ph", hd="adnu.edu.ph")
    csrf = _csrf(client)
    r = client.post("/auth/google/admin", json={"credential": "t"}, headers={"X-CSRFToken": csrf})
    assert r.status_code == 200 and r.get_json()["redirect"].endswith("/admin/workspace")
    with client.session_transaction() as s:
        assert s["admin_id"] and s["admin_auth_method"] == "google"


def test_admin_google_signin_unknown_email_refused(client, google_token):
    google_token["u"] = _claims("stranger@adnu.edu.ph", hd="adnu.edu.ph")
    csrf = _csrf(client)
    r = client.post("/auth/google/admin", json={"credential": "u"}, headers={"X-CSRFToken": csrf})
    assert r.status_code == 403
    with client.session_transaction() as s:
        assert "admin_id" not in s


def test_admin_login_page_has_google_button(client):
    # Classroom-instructor mode (see conftest.py): one sign-in page for everyone
    r = client.get("/admin/login")
    assert r.status_code == 302 and r.headers["Location"].endswith("/login")
    assert "/auth/google/student" in client.get("/login").get_data(as_text=True)


# --------------------------------------------------------------------------- classroom

def test_classroom_endpoints_require_admin(client, assessment_id):
    csrf = _csrf(client)
    r = client.post(f"/admin/assessment/{assessment_id}/classroom/courses", json={"access_token": "good-token"},
                    headers={"X-CSRFToken": csrf})
    assert r.status_code == 401


def test_classroom_token_must_be_issued_to_custos(client, google_api, assessment_id):
    csrf = _admin_login(client)
    url = f"/admin/assessment/{assessment_id}/classroom/courses"
    google_api["tokeninfo"] = {"aud": "other-app", "azp": "other-app", "scope": CLASSROOM_SCOPES}
    r = client.post(url, json={"access_token": "good-token"}, headers={"X-CSRFToken": csrf})
    assert r.status_code == 400 and "not issued for Custos" in r.get_json()["error"]
    google_api["tokeninfo"] = {"aud": CLIENT_ID, "scope": gi.CLASSROOM_SCOPES[0]}
    r = client.post(url, json={"access_token": "good-token"}, headers={"X-CSRFToken": csrf})
    assert r.status_code == 400 and "permissions" in r.get_json()["error"]
    r = client.post(url, json={"access_token": "expired"}, headers={"X-CSRFToken": csrf})
    assert r.status_code == 400


def test_classroom_import_and_roster_enforcement(client, google_api, google_token, assessment_id):
    csrf = _admin_login(client)
    base = f"/admin/assessment/{assessment_id}/classroom"
    r = client.post(f"{base}/courses", json={"access_token": "good-token"}, headers={"X-CSRFToken": csrf})
    assert r.get_json()["courses"] == [{"id": "111", "name": "CSDC101", "section": "ZT-11"}]
    # invalid section mapping and foreign course are refused
    bad = client.post(f"{base}/import", json={"access_token": "good-token", "course_id": "111", "program": "ZS", "class_section": "13"},
                      headers={"X-CSRFToken": csrf})
    assert bad.status_code == 400
    bad = client.post(f"{base}/import", json={"access_token": "good-token", "course_id": "999", "program": "ZT", "class_section": "12"},
                      headers={"X-CSRFToken": csrf})
    assert bad.status_code == 400
    r = client.post(f"{base}/import", json={"access_token": "good-token", "course_id": "111", "program": "ZT", "class_section": "12"},
                    headers={"X-CSRFToken": csrf})
    assert r.get_json() == {"ok": True, "imported": 2, "skipped": 1}
    # re-import is idempotent (replaces the list, no duplicates)
    r = client.post(f"{base}/import", json={"access_token": "good-token", "course_id": "111", "program": "ZT", "class_section": "12"},
                    headers={"X-CSRFToken": csrf})
    assert r.get_json()["imported"] == 2
    conn = connect()
    assert conn.execute("SELECT COUNT(*) FROM classroom_roster_students").fetchone()[0] == 2
    conn.close()
    page = client.get(f"/admin/assessment/{assessment_id}").get_data(as_text=True)
    assert "Google Classroom" in page and "ZT12" in page and "Create assignment" in page

    # A rostered student types only the key; name + section come from the roster
    client.get("/admin/logout")
    _student_signin(client, google_token, "ana@gbox.adnu.edu.ph", "gbox.adnu.edu.ph")
    with client.session_transaction() as s:
        csrf = s["csrf_token"]
    r = client.post("/login", data={"csrf_token": csrf, "session_key": ACCESS_KEY})
    assert r.status_code == 302
    with client.session_transaction() as s:
        assert (s["pending_first_name"], s["pending_last_name"]) == ("Ana", "Roster")
        assert (s["pending_program"], s["pending_class_section"]) == ("ZT", "12")

    # A school account NOT on the roster is refused even with the right key
    client.get("/logout")
    _student_signin(client, google_token, "notlisted@adnu.edu.ph", "adnu.edu.ph")
    r = _exam_login(client)
    assert r.status_code == 200 and "isn&#39;t on the class list" in r.get_data(as_text=True)

    # Removing the roster lifts the restriction
    client.get("/logout")
    csrf = _admin_login(client)
    conn = connect()
    rid = conn.execute("SELECT id FROM classroom_rosters WHERE assessment_id=?", (assessment_id,)).fetchone()["id"]
    conn.close()
    assert client.post(f"{base}/{rid}/delete", headers={"X-CSRFToken": csrf}).get_json()["ok"]
    client.get("/admin/logout")
    _student_signin(client, google_token, "notlisted@adnu.edu.ph", "adnu.edu.ph")
    assert _exam_login(client).status_code == 302


# --------------------------------------------------------------------------- feature off

def test_feature_off_keeps_classic_form():
    """With no GOOGLE_CLIENT_ID, Custos behaves exactly as before (separate process
    because the configuration is read at import time)."""
    env = dict(os.environ, GOOGLE_CLIENT_ID="", EXAM_DB_PATH=os.path.join(_tmp, "off.db"))
    code = (
        "import app; c=app.app.test_client(); r=c.get('/login'); h=r.get_data(as_text=True);"
        "assert 'accounts.google.com' not in h and 'name=\"email\"' in h and 'name=\"session_key\"' in h, h[:300];"
        "assert 'accounts.google.com' not in r.headers['Content-Security-Policy'];"
        "assert 'frame-src' not in r.headers['Content-Security-Policy'];"
        "assert c.post('/auth/google/student', json={}).status_code in (400, 401);"
        "assert 'auth/google/admin' not in c.get('/admin/login').get_data(as_text=True); print('OFF_OK')"
    )
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    assert "OFF_OK" in out.stdout, out.stderr[-2000:]


# --------------------------------------------------------------------------- grade sync + monitor + invite

@pytest.fixture
def classroom_grades(monkeypatch, google_api):
    """Fake courseWork create/get and studentSubmissions list/patch on top of google_api."""
    state = {"coursework": {}, "patches": [], "next": 500}
    google_api["tokeninfo"] = {"aud": CLIENT_ID, "scope": " ".join(gi.ALL_CLASSROOM_SCOPES)}
    real_get = gi.requests.get

    def fake_get(url, params=None, headers=None, timeout=None):
        m = re.search(r"/courses/(\w+)/courseWork/(\w+)/studentSubmissions$", url)
        if m:
            subs = state["coursework"][m.group(2)]["subs"]
            return FakeResp(200, {"studentSubmissions": list(subs.values())})
        return real_get(url, params=params, headers=headers, timeout=timeout)

    def fake_request(method, url, params=None, json=None, headers=None, timeout=None):
        assert headers["Authorization"] == "Bearer good-token"
        m = re.search(r"/courses/(\w+)/courseWork(?:/(\w+))?(?:/studentSubmissions/([\w-]+))?$", url)
        course, cw, sub = m.groups()
        if method == "POST" and not cw:
            cid = str(state["next"]); state["next"] += 1
            subs = {u: {"id": f"sub-{u}", "userId": u} for u in ("u1", "u2")}  # only u1, u2 are in Classroom
            state["coursework"][cid] = {"body": json, "subs": subs}
            return FakeResp(200, {"id": cid, **json})
        if method == "GET" and cw and not sub:
            return FakeResp(200, {"id": cw}) if cw in state["coursework"] else FakeResp(404, {})
        if method == "PATCH" and sub:
            assert params == {"updateMask": "draftGrade,assignedGrade"}
            rec = next(s for s in state["coursework"][cw]["subs"].values() if s["id"] == sub)
            rec.update(json)
            state["patches"].append((sub, json["assignedGrade"]))
            return FakeResp(200, rec)
        raise AssertionError((method, url))

    monkeypatch.setattr(gi.requests, "get", fake_get)
    monkeypatch.setattr(gi.requests, "request", fake_request)
    return state


def _import_roster(client, csrf, assessment_id):
    r = client.post(f"/admin/assessment/{assessment_id}/classroom/import",
                    json={"access_token": "good-token", "course_id": "111", "program": "ZT", "class_section": "11"},
                    headers={"X-CSRFToken": csrf})
    assert r.get_json()["ok"]
    conn = connect()
    rid = conn.execute("SELECT id FROM classroom_rosters WHERE assessment_id=? AND course_id='111'", (assessment_id,)).fetchone()["id"]
    conn.close()
    return rid


def _submitted_attempt(assessment_id, email, auto_total, admin_total=None):
    email = gi.canonical_email(email)  # attempts always carry the canonical Google email
    conn = connect()
    batch = conn.execute("SELECT id FROM batches WHERE assessment_id=?", (assessment_id,)).fetchone()
    conn.execute("DELETE FROM exam_sessions WHERE email=? AND assessment_id=?", (email, assessment_id))
    conn.execute(
        """INSERT INTO exam_sessions(email,batch_id,assessment_id,started_at,status,auto_total,admin_total,is_test)
           VALUES (?,?,?,?, 'submitted', ?, ?, 0)""",
        (email, batch["id"], assessment_id, iso_now(), auto_total, admin_total),
    )
    conn.commit()
    conn.close()


def test_grade_sync_creates_assignment_and_sends_scores(client, classroom_grades, google_api, assessment_id):
    csrf = _admin_login(client)
    rid = _import_roster(client, csrf, assessment_id)
    _submitted_attempt(assessment_id, "ana@gbox.adnu.edu.ph", 1)
    _submitted_attempt(assessment_id, "ben@adnu.edu.ph", 0, admin_total=0.5)  # instructor-adjusted wins
    url = f"/admin/assessment/{assessment_id}/classroom/{rid}/sync"

    # a token without the grading scope is refused
    google_api["tokeninfo"] = {"aud": CLIENT_ID, "scope": CLASSROOM_SCOPES}
    assert client.post(url, json={"access_token": "good-token"}, headers={"X-CSRFToken": csrf}).status_code == 400
    google_api["tokeninfo"] = {"aud": CLIENT_ID, "scope": " ".join(gi.ALL_CLASSROOM_SCOPES)}
    assert client.post(url, json={"access_token": "good-token", "max_points": "0"}, headers={"X-CSRFToken": csrf}).status_code == 400

    r = client.post(url, json={"access_token": "good-token", "max_points": "1"}, headers={"X-CSRFToken": csrf})
    d = r.get_json()
    assert d["ok"] and d["created_assignment"] and d["sent"] == 2 and d["not_submitted"] == 0
    (cw_id, cw), = classroom_grades["coursework"].items()
    assert cw["body"]["title"] == "Google Test Quiz" and cw["body"]["maxPoints"] == 1.0 and cw["body"]["state"] == "PUBLISHED"
    assert sorted(classroom_grades["patches"]) == [("sub-u1", 1.0), ("sub-u2", 0.5)]

    # second run: nothing changed, nothing re-sent, same assignment reused
    d = client.post(url, json={"access_token": "good-token"}, headers={"X-CSRFToken": csrf}).get_json()
    assert d["unchanged"] == 2 and d["sent"] == 0 and not d["created_assignment"]
    conn = connect()
    row = conn.execute("SELECT coursework_id, max_points, last_sync_summary FROM classroom_rosters WHERE id=?", (rid,)).fetchone()
    conn.close()
    assert row["coursework_id"] == cw_id and row["max_points"] == 1.0 and '"unchanged": 2' in row["last_sync_summary"]

    # assignment deleted in Classroom -> a fresh one is created next time
    classroom_grades["coursework"].clear()
    d = client.post(url, json={"access_token": "good-token"}, headers={"X-CSRFToken": csrf}).get_json()
    assert d["created_assignment"] and d["sent"] == 2
    page = client.get(f"/admin/assessment/{assessment_id}").get_data(as_text=True)
    assert "Send scores" in page and "last sent" in page


def test_grade_sync_counts_unsubmitted_and_missing_students(client, classroom_grades, assessment_id):
    csrf = _admin_login(client)
    rid = _import_roster(client, csrf, assessment_id)
    conn = connect()
    conn.execute("DELETE FROM exam_sessions WHERE assessment_id=?", (assessment_id,))
    conn.execute("UPDATE classroom_rosters SET coursework_id=NULL WHERE id=?", (rid,))
    conn.execute("INSERT INTO classroom_roster_students(roster_id,email,first_name,last_name,google_user_id) VALUES (?,?,?,?,?)",
                 (rid, "late@adnu.edu.ph", "Late", "Joiner", "u9"))  # on roster, not in the Classroom assignment
    conn.commit(); conn.close()
    _submitted_attempt(assessment_id, "late@adnu.edu.ph", 1)
    d = client.post(f"/admin/assessment/{assessment_id}/classroom/{rid}/sync", json={"access_token": "good-token"},
                    headers={"X-CSRFToken": csrf}).get_json()
    assert d["sent"] == 0 and d["not_submitted"] == 2 and d["not_in_classroom"] == 1


def test_monitor_not_started(client, classroom_grades, assessment_id):
    csrf = _admin_login(client)
    _import_roster(client, csrf, assessment_id)
    conn = connect()
    conn.execute("DELETE FROM exam_sessions WHERE assessment_id=?", (assessment_id,))
    conn.commit(); conn.close()
    _submitted_attempt(assessment_id, "ana@gbox.adnu.edu.ph", 1)
    d = client.get("/admin/monitor/not-started").get_json()
    names = [s["name"] for s in d["assessments"][str(assessment_id)]["students"]]
    assert names == ["Ben Roster"]  # Ana already took it
    assert d["assessments"][str(assessment_id)]["students"][0]["section"] == "ZT11"
    assert "data-not-started" in client.get("/admin/monitor").get_data(as_text=True)
    client.get("/admin/logout")
    assert client.get("/admin/monitor/not-started").status_code == 401


def test_builtin_assessment_pages_show_classroom_card(client):
    _admin_login(client)
    for t in ("midterm", "posttest"):
        html = client.get(f"/admin?assessment={t}").get_data(as_text=True)
        assert "data-classroom" in html and "accounts.google.com/gsi/client" in html, t
    conn = connect()
    dry = conn.execute("SELECT id FROM batches WHERE assessment_type='dryrun' LIMIT 1").fetchone()
    conn.close()
    if dry:
        assert "data-classroom" in client.get(f"/admin/batch/{dry['id']}").get_data(as_text=True)


def test_invite_instructor_by_google_email(client, google_token):
    csrf = _admin_login(client)
    r = client.post("/admin/workspace/instructor/add", data={"csrf_token": csrf, "display_name": "Prof Invite",
                                                             "email": "prof.invite@gbox.adnu.edu.ph"})
    assert r.status_code == 302
    conn = connect()
    a = conn.execute("SELECT * FROM admins WHERE email='prof.invite@gbox.adnu.edu.ph'").fetchone()
    i = conn.execute("SELECT * FROM instructors WHERE admin_id=?", (a["id"],)).fetchone()
    conn.close()
    assert a["username"] == "prof.invite" and a["role"] == "instructor" and i["email"] == "prof.invite@gbox.adnu.edu.ph"
    # duplicate email refused
    client.post("/admin/workspace/instructor/add", data={"csrf_token": csrf, "display_name": "Again", "email": "prof.invite@gbox.adnu.edu.ph"})
    conn = connect()
    assert conn.execute("SELECT COUNT(*) FROM admins WHERE email='prof.invite@gbox.adnu.edu.ph'").fetchone()[0] == 1
    conn.close()
    # they sign in with Google straight into the Workspace
    client.get("/admin/logout")
    google_token["inv"] = _claims("prof.invite@gbox.adnu.edu.ph", hd="gbox.adnu.edu.ph")
    csrf = _csrf(client)
    r = client.post("/auth/google/student", json={"credential": "inv"}, headers={"X-CSRFToken": csrf})
    # Classroom mode: known instructors are offered "Continue to my courses" (Classroom re-check)
    assert r.get_json()["role"] == "instructor_check"

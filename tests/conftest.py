"""Shared test configuration. Custos reads its settings once at import time,
so every test module runs against the same configuration: Google sign-in on,
Classroom-instructor mode on, two owners."""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="custos-test-")
CLIENT_ID = "test-client.apps.googleusercontent.com"
os.environ.update({
    "SECRET_KEY": "x" * 64, "ADMIN_USERNAME": "admin", "ADMIN_PASSWORD": "test-admin-password-123",
    "DATABASE_URL": "", "EXAM_DB_PATH": os.path.join(TMP, "test.db"), "AUTO_INIT_DB": "1",
    "GOOGLE_CLIENT_ID": CLIENT_ID, "GOOGLE_ALLOWED_DOMAINS": "adnu.edu.ph,gbox.adnu.edu.ph",
    "STUDENT_GOOGLE_LOGIN_REQUIRED": "1", "CODE_RUNNER_BACKEND": "disabled",
    "CLASSROOM_INSTRUCTORS": "1",
    "CUSTOS_OWNER_EMAILS": "teacher@adnu.edu.ph,owner.two@gbox.adnu.edu.ph",
    "EMAIL_DOMAIN_ALIASES": "gbox.adnu.edu.ph=adnu.edu.ph",
})
sys.path.insert(0, ROOT)

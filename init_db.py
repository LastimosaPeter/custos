import os
from dotenv import load_dotenv
from db import DATABASE_ENGINE, DB_PATH, init_db

load_dotenv()
admin_password = os.getenv("ADMIN_PASSWORD", "").strip()
if not admin_password or admin_password.startswith("replace-"):
    raise RuntimeError("Set ADMIN_PASSWORD in .env before initializing Custos.")

init_db(
    admin_username=os.getenv("ADMIN_USERNAME", "admin"),
    admin_password=admin_password,
)

if DATABASE_ENGINE == "postgresql":
    print("Database initialized: PostgreSQL (DATABASE_URL)")
else:
    print(f"Database initialized: SQLite ({DB_PATH})")

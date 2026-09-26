import os
from dotenv import load_dotenv
from db import init_db, DB_PATH

load_dotenv()
admin_password = os.getenv("ADMIN_PASSWORD", "").strip()
if not admin_password or admin_password.startswith("replace-"):
    raise RuntimeError("Set ADMIN_PASSWORD in .env before initializing Custos.")
init_db(
    admin_username=os.getenv("ADMIN_USERNAME", "admin"),
    admin_password=admin_password,
)
print(f"Database initialized: {DB_PATH}")

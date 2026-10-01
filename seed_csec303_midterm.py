"""Seed the private CSEC303 PHANTOM-303 bank into the configured Custos DB.

Run this script locally. ``private_banks/`` is Git-ignored so answer keys never
need to be pushed to a public repository. Set DATABASE_URL to production when
seeding a Vercel/Render PostgreSQL database.
"""
from __future__ import annotations

from db import connect
from csec303_midterm_seed import ensure_csec303_midterm_seed, _private_bank_path


def main():
    path = _private_bank_path()
    if not path.is_file():
        raise SystemExit(f"Private CSEC303 bank not found: {path}")
    conn = connect()
    try:
        assessment_id = ensure_csec303_midterm_seed(conn)
        assessment = conn.execute(
            "SELECT title,access_code FROM assessments WHERE id=?", (assessment_id,)
        ).fetchone()
        count = conn.execute(
            "SELECT COUNT(*) FROM questions WHERE assessment_id=? AND COALESCE(active,1)=1", (assessment_id,)
        ).fetchone()[0]
        print(f"Seeded: {assessment['title']}")
        print(f"Questions: {count}")
        print(f"Current session key: {assessment['access_code']}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()

"""Create a small public CSEC303 Jupyter Workbench dry run.

This is intentionally a TEST assessment. Its questions and answers are public so
it is safe to commit to GitHub. Run after Custos has initialized its database:

    python seed_csec303_workbench_test.py

The script works with SQLite locally or the PostgreSQL DATABASE_URL configured in
.env. Do not point DATABASE_URL at production unless you actually want the dry run
there.
"""
from __future__ import annotations

import csv
import io
import secrets
from pathlib import Path

from db import connect, iso_now
from notebook_workbench import read_workbench_upload, store_workbench

ROOT = Path(__file__).resolve().parent
SAMPLE = ROOT / "samples" / "csec303_workbench_dry_run"
SLUG = "csec303-workbench-dry-run"
TITLE = "CSEC303 Workbench Dry Run | Image Recovery Mini-Lab"


def _key(conn):
    preferred = "CSEC303-DRYRUN"
    if not conn.execute("SELECT 1 FROM batches WHERE access_code=?", (preferred,)).fetchone():
        return preferred
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    while True:
        code = "CSEC303-DRY-" + "".join(secrets.choice(alphabet) for _ in range(5))
        if not conn.execute("SELECT 1 FROM batches WHERE access_code=?", (code,)).fetchone():
            return code


def main():
    qpath = SAMPLE / "questions.csv"
    zpath = SAMPLE / "CSEC303_Workbench_Dry_Run.zip"
    if not qpath.is_file() or not zpath.is_file():
        raise SystemExit("Dry-run sample files are missing.")

    conn = connect()
    try:
        now = iso_now()
        conn.execute(
            """INSERT INTO subjects(code,name,term,school_year,active,created_at)
               VALUES('CSEC303','Digital Image Processing','1st Semester','2026-2027',1,?)
               ON CONFLICT(code,term,school_year) DO UPDATE SET name=excluded.name,active=1""",
            (now,),
        )
        subject = conn.execute(
            "SELECT * FROM subjects WHERE code='CSEC303' AND term='1st Semester' AND school_year='2026-2027'"
        ).fetchone()
        assessment = conn.execute("SELECT * FROM assessments WHERE slug=?", (SLUG,)).fetchone()
        if not assessment:
            access = _key(conn)
            cur = conn.execute(
                """INSERT INTO assessments(subject_id,title,slug,assessment_type,display_type,description,
                           duration_minutes,start_at,end_at,access_code,max_attempts,security_mode,reveal_score,reveal_answers,
                           shuffle_questions,shuffle_options,allowed_sections,question_limit,active,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id""",
                (
                    subject["id"], TITLE, SLUG, "custom", "Workbench Practice",
                    "Short open-tool practice for the CSEC303 browser Python Workbench. Uses generated evidence only.",
                    45, None, None, access, 1, "standard", 1, 1, 0, 0, "", 0, 1, now,
                ),
            )
            assessment_id = int(cur.fetchone()[0])
        else:
            assessment_id = int(assessment["id"])
            conn.execute(
                """UPDATE assessments SET subject_id=?,title=?,display_type='Workbench Practice',
                          description=?,duration_minutes=45,security_mode='standard',reveal_score=1,reveal_answers=1,
                          shuffle_questions=0,shuffle_options=0,question_limit=0,active=1,deleted_at=NULL WHERE id=?""",
                (subject["id"], TITLE, "Short open-tool practice for the CSEC303 browser Python Workbench. Uses generated evidence only.", assessment_id),
            )
            access = assessment["access_code"] or _key(conn)
            conn.execute("UPDATE assessments SET access_code=? WHERE id=?", (access, assessment_id))

        batch = conn.execute("SELECT * FROM batches WHERE assessment_id=? ORDER BY id LIMIT 1", (assessment_id,)).fetchone()
        if not batch:
            slot = int(conn.execute("SELECT COALESCE(MAX(slot),0)+1 AS n FROM batches").fetchone()["n"])
            conn.execute(
                """INSERT INTO batches(slot,section,batch_label,name,access_code,duration_minutes,reveal_score,reveal_answers,
                           active,assessment_type,subject_id,assessment_id)
                   VALUES(?, 'ALL', 'DRY', ?, ?, 45, 1, 1, 1, 'custom', ?, ?)""",
                (slot, TITLE, access, subject["id"], assessment_id),
            )
        else:
            slot = int(batch["slot"])
            conn.execute(
                """UPDATE batches SET name=?,access_code=?,duration_minutes=45,reveal_score=1,reveal_answers=1,
                          active=1,assessment_type='custom',subject_id=? WHERE id=?""",
                (TITLE, access, subject["id"], batch["id"]),
            )

        has_real_attempts = conn.execute(
            "SELECT 1 FROM exam_sessions WHERE assessment_id=? AND COALESCE(is_test,0)=0 LIMIT 1", (assessment_id,)
        ).fetchone()
        if not has_real_attempts:
            conn.execute("DELETE FROM questions WHERE assessment_id=? AND created_by='csec303_workbench_dryrun'", (assessment_id,))
            rows = list(csv.DictReader(io.StringIO(qpath.read_text(encoding="utf-8"))))
            for pos, q in enumerate(rows, 1):
                conn.execute(
                    """INSERT INTO questions(part,batch_slot,topic,prompt,code,option_a,option_b,option_c,option_d,
                               correct_option,explanation,points,position,workbench_section,active,created_by,subject_id,assessment_id)
                       VALUES(1,?,?,?,?,?,?,?,?,?,?,?, ?,?,1,'csec303_workbench_dryrun',?,?)""",
                    (
                        slot, q["topic"], q["prompt"], q.get("code", ""), q["option_a"], q["option_b"],
                        q["option_c"], q["option_d"], q["correct_option"], q.get("explanation", ""),
                        int(q.get("points") or 1), pos, q.get("workbench_section") or None, subject["id"], assessment_id,
                    ),
                )

        package = read_workbench_upload(zpath.name, zpath.read_bytes())
        store_workbench(conn, assessment_id, package)
        conn.commit()
        question_count = conn.execute("SELECT COUNT(*) AS n FROM questions WHERE assessment_id=? AND active=1", (assessment_id,)).fetchone()["n"]
        print(f"Created/updated: {TITLE}")
        print(f"Questions: {question_count}")
        print(f"Session key: {access}")
        print("Reveal score: on | Reveal answers: on | Security: standard")
    finally:
        conn.close()


if __name__ == "__main__":
    main()

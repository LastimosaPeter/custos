"""Secure seed loader for the CSEC303 PHANTOM-303 laboratory midterm.

The public application source deliberately contains *no answer key*. Question
content and correct answers live in ``private_banks/csec303_midterm`` which is
ignored by Git. A local Custos ZIP can therefore seed the assessment directly,
while a public GitHub/Vercel deployment receives only the assessment shell until
an instructor runs ``seed_csec303_midterm.py`` locally against the production
DATABASE_URL.
"""
from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path

SUBJECT_CODE = "CSEC303"
SUBJECT_NAME = "Digital Image Processing"
TERM = "1st Semester"
SCHOOL_YEAR = "2026-2027"
ASSESSMENT_SLUG = "csec303-midterm-laboratory-case-files"
DEFAULT_PRIVATE_BANK = Path(__file__).resolve().parent / "private_banks" / "csec303_midterm" / "question_bank.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _private_bank_path() -> Path:
    configured = os.getenv("CSEC303_PRIVATE_BANK_PATH", "").strip()
    return Path(configured).expanduser().resolve() if configured else DEFAULT_PRIVATE_BANK


def _load_private_questions() -> list[dict]:
    path = _private_bank_path()
    if not path.is_file():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("CSEC303 private question bank must be a JSON list.")
    required = {"topic", "prompt", "options", "answer", "explanation"}
    questions = []
    for idx, item in enumerate(payload, start=1):
        if not isinstance(item, dict) or not required.issubset(item):
            raise ValueError(f"CSEC303 private question {idx} is incomplete.")
        options = item.get("options")
        if not isinstance(options, list) or len(options) != 4:
            raise ValueError(f"CSEC303 private question {idx} must have exactly four options.")
        answer = str(item.get("answer", "")).strip().upper()
        if answer not in {"A", "B", "C", "D"}:
            raise ValueError(f"CSEC303 private question {idx} has an invalid answer key.")
        questions.append(item)
    return questions


def _topic_section(topic: str | None) -> str:
    text = str(topic or "").upper()
    import re
    match = re.search(r"CASE\s*0?(\d+)", text)
    return f"CASE{int(match.group(1)):02d}" if match else "GUIDE"


def _unique_access_code(conn) -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    for _ in range(40):
        secret = "".join(secrets.choice(alphabet) for _ in range(8))
        code = f"CSEC303-{secret[:4]}-{secret[4:]}"
        if not conn.execute("SELECT 1 FROM batches WHERE access_code=?", (code,)).fetchone():
            return code
    raise RuntimeError("Could not generate a unique CSEC303 session key.")


def ensure_csec303_midterm_seed(conn) -> int:
    """Ensure the subject/assessment exist; seed questions only from private data.

    This function is idempotent. Existing real attempts are never overwritten.
    """
    now = _now()
    questions = _load_private_questions()
    seed_active = 1 if questions else 0
    conn.execute(
        """INSERT INTO subjects(code,name,term,school_year,active,created_at)
           VALUES(?,?,?,?,1,?)
           ON CONFLICT(code,term,school_year) DO UPDATE SET name=excluded.name,active=1""",
        (SUBJECT_CODE, SUBJECT_NAME, TERM, SCHOOL_YEAR, now),
    )
    subject = conn.execute(
        "SELECT * FROM subjects WHERE code=? AND term=? AND school_year=?",
        (SUBJECT_CODE, TERM, SCHOOL_YEAR),
    ).fetchone()

    assessment = conn.execute("SELECT * FROM assessments WHERE slug=?", (ASSESSMENT_SLUG,)).fetchone()
    if not assessment:
        access_code = _unique_access_code(conn)
        cur = conn.execute(
            """INSERT INTO assessments(subject_id,title,slug,assessment_type,display_type,description,
                       duration_minutes,start_at,end_at,access_code,max_attempts,security_mode,reveal_score,
                       shuffle_questions,shuffle_options,allowed_sections,question_limit,active,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id""",
            (
                subject["id"],
                "Case File PHANTOM-303 | Laboratory Midterm Examination",
                ASSESSMENT_SLUG,
                "custom",
                "Laboratory Midterm",
                "Three-day open-tool Digital Image Processing investigation. Use the in-browser Python Workbench or Jupyter Case Kit, process Cases 00–04, then submit Q1–Q20 in Custos. Progress is saved between sessions.",
                4320,
                None,
                None,
                access_code,
                1,
                "standard",
                0,
                0,
                0,
                "",
                0,
                seed_active,
                now,
            ),
        )
        assessment_id = cur.fetchone()[0]
    else:
        assessment_id = assessment["id"]
        conn.execute(
            """UPDATE assessments SET subject_id=?,title=?,display_type=?,description=?,duration_minutes=4320,
                      security_mode='standard',reveal_score=0,shuffle_questions=0,shuffle_options=0,
                      question_limit=0,active=?,deleted_at=NULL
               WHERE id=?""",
            (
                subject["id"],
                "Case File PHANTOM-303 | Laboratory Midterm Examination",
                "Laboratory Midterm",
                "Three-day open-tool Digital Image Processing investigation. Use the in-browser Python Workbench or Jupyter Case Kit, process Cases 00–04, then submit Q1–Q20 in Custos. Progress is saved between sessions.",
                (1 if questions else int(assessment["active"] or 0)),
                assessment_id,
            ),
        )
        if not assessment["access_code"]:
            conn.execute("UPDATE assessments SET access_code=? WHERE id=?", (_unique_access_code(conn), assessment_id))

    assessment = conn.execute("SELECT * FROM assessments WHERE id=?", (assessment_id,)).fetchone()
    batch = conn.execute("SELECT * FROM batches WHERE assessment_id=? ORDER BY id LIMIT 1", (assessment_id,)).fetchone()
    if not batch:
        slot_row = conn.execute("SELECT COALESCE(MAX(slot),17)+1 AS slot FROM batches").fetchone()
        slot = int(slot_row["slot"] or 18)
        conn.execute(
            """INSERT INTO batches(slot,section,batch_label,name,access_code,open_at,close_at,duration_minutes,
                       reveal_score,active,assessment_type,subject_id,assessment_id)
               VALUES(?, 'ALL', 'LAB', ?, ?, NULL, NULL, 4320, 0, ?, 'custom', ?, ?)""",
            (slot, assessment["title"], assessment["access_code"], seed_active, subject["id"], assessment_id),
        )
    else:
        conn.execute(
            """UPDATE batches SET name=?,access_code=?,duration_minutes=4320,reveal_score=0,
                      assessment_type='custom',subject_id=?,active=? WHERE id=?""",
            (assessment["title"], assessment["access_code"], subject["id"], (1 if questions else int(batch["active"] or 0)), batch["id"]),
        )

    batch = conn.execute("SELECT * FROM batches WHERE assessment_id=? ORDER BY id LIMIT 1", (assessment_id,)).fetchone()
    has_attempts = conn.execute("SELECT 1 FROM exam_sessions WHERE assessment_id=? LIMIT 1", (assessment_id,)).fetchone()
    if questions and not has_attempts:
        conn.execute("DELETE FROM questions WHERE assessment_id=? AND created_by='csec303_private_seed'", (assessment_id,))
        # Also remove any pre-release local seed rows if upgrading the prototype.
        conn.execute("DELETE FROM questions WHERE assessment_id=? AND created_by='csec303_midterm_seed'", (assessment_id,))
        for position, q in enumerate(questions, start=1):
            a, b, c, d = q["options"]
            conn.execute(
                """INSERT INTO questions(part,batch_slot,topic,prompt,code,option_a,option_b,option_c,option_d,
                           correct_option,explanation,points,position,workbench_section,active,created_by,subject_id,assessment_id)
                   VALUES(1,?,?,?,?,?,?,?,?,?,?,3,?,?,1,'csec303_private_seed',?,?)""",
                (
                    batch["slot"], q["topic"], q["prompt"], q.get("code", ""), a, b, c, d,
                    q["answer"], q["explanation"], position, q.get("workbench_section") or _topic_section(q.get("topic")), subject["id"], assessment_id,
                ),
            )

    # Existing deployments created before generic workbenches did not store the notebook section.
    # Populate it from the stable CASE xx topic prefix without touching scores or answers.
    qrows = conn.execute("SELECT id,topic,workbench_section FROM questions WHERE assessment_id=?", (assessment_id,)).fetchall()
    for row in qrows:
        if not row["workbench_section"]:
            conn.execute("UPDATE questions SET workbench_section=? WHERE id=?", (_topic_section(row["topic"]), row["id"]))

    instructor = conn.execute("SELECT id FROM instructors WHERE active=1 ORDER BY id LIMIT 1").fetchone()
    if instructor:
        conn.execute(
            """INSERT INTO subject_instructors(subject_id,instructor_id,role) VALUES(?,?,'owner')
               ON CONFLICT(subject_id,instructor_id) DO NOTHING""",
            (subject["id"], instructor["id"]),
        )

    conn.commit()
    return int(assessment_id)

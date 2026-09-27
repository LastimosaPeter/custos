import math
from collections import defaultdict


def _pearson(xs, ys):
    n = len(xs)
    if n < 5:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sx = sum((x - mx) ** 2 for x in xs)
    sy = sum((y - my) ** 2 for y in ys)
    if sx <= 0 or sy <= 0:
        return None
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return cov / math.sqrt(sx * sy)


def _correct_rate_band(p):
    if p is None:
        return "No data"
    if p < 0.40:
        return "Low correct rate"
    if p <= 0.80:
        return "Moderate correct rate"
    return "High correct rate"


def _discrimination_band(r, n):
    if n < 5:
        return "Need ≥5 responses"
    if r is None:
        return "Not estimable"
    if r < 0:
        return "Negative — review item/key"
    if r < 0.10:
        return "Very weak"
    if r < 0.20:
        return "Weak"
    if r < 0.30:
        return "Useful"
    return "Strong"


def build_item_analysis(
    conn,
    batch_slot=None,
    part=None,
    topic=None,
    assessment="midterm",
    assessment_id=None,
):
    """Build item statistics for either a legacy assessment family or one assessment record.

    `assessment_id` is the preferred future-proof selector. `assessment` remains for
    compatibility with the original Midterm/Post-test routes.
    """
    clauses = ["e.status='submitted'", "COALESCE(e.is_test,0)=0"]
    params = []
    if assessment_id is not None:
        clauses.append("e.assessment_id=?")
        params.append(int(assessment_id))
    elif assessment:
        clauses.append("b.assessment_type=?")
        params.append(assessment)
    if batch_slot:
        clauses.append("q.batch_slot=?")
        params.append(int(batch_slot))
    if part:
        clauses.append("q.part=?")
        params.append(int(part))
    if topic:
        clauses.append("q.topic=?")
        params.append(topic)

    where = " AND ".join(clauses)
    rows = conn.execute(
        f"""
        SELECT q.id AS question_id, q.part, q.batch_slot, q.topic, q.prompt, q.code,
               q.option_a, q.option_b, q.option_c, q.option_d, q.correct_option,
               COALESCE(q.points,1) AS points, sq.selected_option, e.id AS session_id,
               COALESCE(e.auto_total,0) AS overall_total
        FROM session_questions sq
        JOIN questions q ON q.id=sq.question_id
        JOIN exam_sessions e ON e.id=sq.session_id
        JOIN batches b ON b.id=e.batch_id
        WHERE {where}
        ORDER BY q.batch_slot, q.part, COALESCE(q.position,q.id), q.id, e.id
        """,
        params,
    ).fetchall()

    grouped = defaultdict(list)
    question_meta = {}
    for row in rows:
        qid = row["question_id"]
        grouped[qid].append(row)
        question_meta[qid] = row

    items = []
    for qid, attempts in grouped.items():
        meta = question_meta[qid]
        n = len(attempts)
        option_counts = {"A": 0, "B": 0, "C": 0, "D": 0}
        omitted = 0
        correct = 0
        xs = []
        ys = []
        item_points = float(meta["points"] or 1)
        for row in attempts:
            selected = row["selected_option"]
            is_correct = 1 if selected == row["correct_option"] else 0
            correct += is_correct
            if selected in option_counts:
                option_counts[selected] += 1
            else:
                omitted += 1
            xs.append(is_correct)
            # Use the score outside this item. This works for weighted custom tests
            # while remaining compatible with the legacy score model.
            earned_here = item_points if is_correct else 0
            ys.append(float(row["overall_total"] or 0) - earned_here)

        p = correct / n if n else None
        response_rate = (n - omitted) / n if n else None
        r_pb = _pearson(xs, ys)
        wrong_options = [o for o in "ABCD" if o != meta["correct_option"]]
        functioning = sum(1 for o in wrong_options if option_counts[o] / n >= 0.05) if n else 0
        top_distractor = None
        if n:
            top_distractor = max(wrong_options, key=lambda o: option_counts[o])
            if option_counts[top_distractor] == 0:
                top_distractor = None

        flags = []
        if n >= 5 and p is not None and p < 0.30:
            flags.append("Very low correct rate")
        if n >= 5 and p is not None and p > 0.95:
            flags.append("Very high correct rate")
        if n >= 5 and r_pb is not None and r_pb < 0:
            flags.append("Negative discrimination")
        elif n >= 5 and r_pb is not None and r_pb < 0.10:
            flags.append("Weak discrimination")
        if n and omitted / n >= 0.20:
            flags.append("High omission rate")
        if n >= 5 and functioning == 0:
            flags.append("No functioning distractor")

        items.append({
            "question_id": qid,
            "part": meta["part"],
            "batch_slot": meta["batch_slot"],
            "topic": meta["topic"],
            "prompt": meta["prompt"],
            "code": meta["code"],
            "points": item_points,
            "options": {
                "A": meta["option_a"], "B": meta["option_b"],
                "C": meta["option_c"], "D": meta["option_d"],
            },
            "correct_option": meta["correct_option"],
            "n": n,
            "correct": correct,
            "p": p,
            "p_pct": round(p * 100, 1) if p is not None else None,
            "response_rate": response_rate,
            "response_pct": round(response_rate * 100, 1) if response_rate is not None else None,
            "omitted": omitted,
            "r_pb": r_pb,
            "r_pb_display": "—" if r_pb is None else f"{r_pb:.2f}",
            "correct_rate_band": _correct_rate_band(p),
            "discrimination_band": _discrimination_band(r_pb, n),
            "option_counts": option_counts,
            "option_pct": {o: round(option_counts[o] / n * 100, 1) if n else 0 for o in "ABCD"},
            "functioning_distractors": functioning,
            "top_distractor": top_distractor,
            "flags": flags,
        })

    topic_groups = defaultdict(lambda: {"correct": 0, "attempts": 0, "omitted": 0})
    for item in items:
        group = topic_groups[(item["part"], item["topic"])]
        group["correct"] += item["correct"]
        group["attempts"] += item["n"]
        group["omitted"] += item["omitted"]
    topic_summary = []
    for (pnum, topic_name), group in topic_groups.items():
        pct = (group["correct"] / group["attempts"] * 100) if group["attempts"] else 0
        topic_summary.append({"part": pnum, "topic": topic_name, **group, "pct": round(pct, 1)})
    topic_summary.sort(key=lambda x: (x["pct"], x["part"], x["topic"]))

    if assessment_id is not None:
        batch_filter = "b.assessment_id=?"
        batch_params = (int(assessment_id),)
        session_filter = "e.assessment_id=?"
        session_params = (int(assessment_id),)
    else:
        batch_filter = "(? IS NULL OR b.assessment_type=?)"
        batch_params = (assessment, assessment)
        session_filter = "(? IS NULL OR b.assessment_type=?)"
        session_params = (assessment, assessment)

    batch_rows = conn.execute(
        f"""
        SELECT b.slot, b.name,
               COUNT(e.id) AS n,
               AVG(e.auto_total) AS avg_score,
               AVG(e.part1_correct) AS avg_p1_raw,
               AVG(e.part2_correct) AS avg_p2_raw,
               AVG(e.flagged_count) AS avg_flags
        FROM batches b
        LEFT JOIN exam_sessions e ON e.batch_id=b.id
             AND e.status='submitted' AND COALESCE(e.is_test,0)=0
        WHERE {batch_filter}
        GROUP BY b.id ORDER BY b.slot
        """,
        batch_params,
    ).fetchall()
    batch_summary = [dict(r) for r in batch_rows]
    for batch in batch_summary:
        for key in ("avg_score", "avg_p1_raw", "avg_p2_raw", "avg_flags"):
            batch[key] = round(batch[key], 2) if batch[key] is not None else None

    submitted_students = conn.execute(
        f"""SELECT COUNT(*) FROM exam_sessions e JOIN batches b ON b.id=e.batch_id
             WHERE e.status='submitted' AND COALESCE(e.is_test,0)=0 AND {session_filter}""",
        session_params,
    ).fetchone()[0]
    mean_score = conn.execute(
        f"""SELECT AVG(e.auto_total) FROM exam_sessions e JOIN batches b ON b.id=e.batch_id
             WHERE e.status='submitted' AND COALESCE(e.is_test,0)=0 AND {session_filter}""",
        session_params,
    ).fetchone()[0]

    return {
        "items": items,
        "topic_summary": topic_summary,
        "batch_summary": batch_summary,
        "submitted_students": submitted_students,
        "mean_score": round(mean_score, 2) if mean_score is not None else None,
        "flagged_items": sum(1 for item in items if item["flags"]),
        "assessment": assessment,
        "assessment_id": assessment_id,
    }

"""Assessment analytics for Custos.

The module intentionally uses only the Python standard library so the analytics
page works on Render, Vercel, Docker, and local deployments without adding a
heavy scientific-computing dependency.
"""

import math
import re
from collections import defaultdict
from statistics import median


MIN_DISCRIMINATION_N = 5
MIN_HIGH_LOW_N = 8


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _mean(values):
    vals = [float(v) for v in values if v is not None]
    return (sum(vals) / len(vals)) if vals else None


def _sample_sd(values):
    vals = [float(v) for v in values if v is not None]
    if len(vals) < 2:
        return None
    m = sum(vals) / len(vals)
    return math.sqrt(sum((x - m) ** 2 for x in vals) / (len(vals) - 1))


def _variance(values):
    sd = _sample_sd(values)
    return None if sd is None else sd * sd


def _pearson(xs, ys):
    pairs = [(float(x), float(y)) for x, y in zip(xs, ys) if x is not None and y is not None]
    n = len(pairs)
    if n < MIN_DISCRIMINATION_N:
        return None
    xvals = [p[0] for p in pairs]
    yvals = [p[1] for p in pairs]
    mx = sum(xvals) / n
    my = sum(yvals) / n
    sx = sum((x - mx) ** 2 for x in xvals)
    sy = sum((y - my) ** 2 for y in yvals)
    if sx <= 0 or sy <= 0:
        return None
    cov = sum((x - mx) * (y - my) for x, y in pairs)
    return cov / math.sqrt(sx * sy)


def _cronbach_alpha(matrix):
    """Return Cronbach alpha for a complete person x item score matrix.

    This is equivalent to KR-20 when all items are dichotomous and equally
    weighted. We deliberately require a complete common form; randomized forms
    with different item sets are reported as non-estimable rather than forcing
    missing-by-design responses to zero.
    """
    if not matrix or len(matrix) < MIN_DISCRIMINATION_N:
        return None
    k = len(matrix[0]) if matrix[0] else 0
    if k < 2 or any(len(row) != k for row in matrix):
        return None
    item_variances = []
    for idx in range(k):
        var = _variance([row[idx] for row in matrix])
        item_variances.append(0.0 if var is None else var)
    totals = [sum(row) for row in matrix]
    total_var = _variance(totals)
    if total_var is None or total_var <= 0:
        return None
    alpha = (k / (k - 1)) * (1 - (sum(item_variances) / total_var))
    # Extremely small samples / degenerate score patterns can create values
    # slightly beyond the usual range. Keep the raw negative signal but cap
    # numerical overshoot above 1.
    return min(alpha, 1.0)


def _alpha_band(alpha):
    if alpha is None:
        return "Not estimable"
    if alpha < 0:
        return "Negative — inspect scoring/items"
    if alpha < 0.60:
        return "Low internal consistency"
    if alpha < 0.70:
        return "Questionable internal consistency"
    if alpha < 0.80:
        return "Acceptable internal consistency"
    if alpha < 0.90:
        return "Good internal consistency"
    return "Very high internal consistency"


def _correct_rate_band(p):
    if p is None:
        return "No data"
    if p < 0.30:
        return "Very difficult"
    if p < 0.50:
        return "Difficult"
    if p <= 0.80:
        return "Moderate"
    if p <= 0.95:
        return "Easy"
    return "Very easy"


def _discrimination_band(r, n):
    if n < MIN_DISCRIMINATION_N:
        return f"Need ≥{MIN_DISCRIMINATION_N} responses"
    if r is None:
        return "Not estimable"
    if r < 0:
        return "Negative — review item/key"
    if r < 0.10:
        return "Very weak"
    if r < 0.20:
        return "Weak"
    if r < 0.30:
        return "Moderate"
    if r < 0.40:
        return "Good"
    return "Very good"


def _high_low(attempts):
    """Top/bottom 27% discrimination using rest-of-test score for grouping."""
    if len(attempts) < MIN_HIGH_LOW_N:
        return None, None, None
    ordered = sorted(attempts, key=lambda x: (x["rest_score"], x["session_id"]))
    group_n = max(1, int(math.floor(len(ordered) * 0.27)))
    low = ordered[:group_n]
    high = ordered[-group_n:]
    p_low = _mean([x["correct"] for x in low])
    p_high = _mean([x["correct"] for x in high])
    if p_low is None or p_high is None:
        return None, None, None
    return p_high - p_low, p_high, p_low


def _high_low_band(d, n):
    if n < MIN_HIGH_LOW_N:
        return f"Need ≥{MIN_HIGH_LOW_N} responses"
    if d is None:
        return "Not estimable"
    if d < 0:
        return "Negative"
    if d < 0.20:
        return "Low"
    if d < 0.30:
        return "Fair"
    if d < 0.40:
        return "Good"
    return "Very good"


def _normalize_short_answer(value):
    return "".join(ch for ch in str(value or "").casefold() if ch.isalnum())


def _short_answer_matches(submitted, accepted):
    normalized = _normalize_short_answer(submitted)
    if not normalized:
        return False
    return any(normalized == _normalize_short_answer(option) for option in str(accepted or "").split("|"))


def _score_distribution(percentages):
    buckets = [
        ("0–19%", 0, 20),
        ("20–39%", 20, 40),
        ("40–59%", 40, 60),
        ("60–79%", 60, 80),
        ("80–89%", 80, 90),
        ("90–100%", 90, 101),
    ]
    total = len(percentages)
    output = []
    for label, low, high in buckets:
        count = sum(1 for p in percentages if low <= p < high)
        output.append({
            "label": label,
            "count": count,
            "pct": round((count / total) * 100, 1) if total else 0,
        })
    return output


def _score_summary(scores, percentages, max_score=None):
    if not scores:
        return {
            "n": 0,
            "mean": None,
            "median": None,
            "sd": None,
            "minimum": None,
            "maximum": None,
            "mean_pct": None,
            "median_pct": None,
            "distribution": _score_distribution([]),
            "max_score": max_score,
        }
    return {
        "n": len(scores),
        "mean": round(_mean(scores), 2),
        "median": round(float(median(scores)), 2),
        "sd": round(_sample_sd(scores), 2) if _sample_sd(scores) is not None else None,
        "minimum": round(min(scores), 2),
        "maximum": round(max(scores), 2),
        "mean_pct": round(_mean(percentages), 1) if percentages else None,
        "median_pct": round(float(median(percentages)), 1) if percentages else None,
        "distribution": _score_distribution(percentages),
        "max_score": max_score,
    }


def _common_form_alpha(session_item_scores):
    """Calculate alpha only when every included student received the same form."""
    if len(session_item_scores) < MIN_DISCRIMINATION_N:
        return None, "At least 5 submitted students are needed."
    item_sets = [set(items.keys()) for items in session_item_scores.values()]
    if not item_sets or not item_sets[0]:
        return None, "No scored items are available."
    first = item_sets[0]
    if any(items != first for items in item_sets[1:]):
        return None, "Students received different randomized item forms; alpha is not pooled across non-equivalent forms."
    ordered = sorted(first, key=lambda x: str(x))
    matrix = [[session_item_scores[sid][qid] for qid in ordered] for sid in sorted(session_item_scores)]
    alpha = _cronbach_alpha(matrix)
    if alpha is None:
        return None, "Score variance is insufficient to estimate reliability."
    return alpha, None


def _format_float(value, digits=2):
    return None if value is None else round(float(value), digits)


def build_item_analysis(
    conn,
    batch_slot=None,
    part=None,
    topic=None,
    assessment="midterm",
    assessment_id=None,
    max_score=None,
):
    """Build classical item analysis for any question-based Custos assessment.

    Techniques include item facility/difficulty, corrected point-biserial
    discrimination, top/bottom 27% discrimination, omission rate, distractor
    functioning, topic summaries, score distribution, and form-level internal
    consistency when the administered form permits it.
    """
    assessment_id = int(assessment_id) if assessment_id is not None else None

    session_clauses = ["e.status='submitted'", "COALESCE(e.is_test,0)=0"]
    session_params = []
    if assessment_id is not None:
        session_clauses.append("e.assessment_id=?")
        session_params.append(assessment_id)
    elif assessment:
        session_clauses.append("b.assessment_type=?")
        session_params.append(assessment)
    session_where = " AND ".join(session_clauses)

    sessions = conn.execute(
        f"""
        SELECT e.id,e.auto_total,e.flagged_count,e.batch_id,e.assessment_id,
               b.slot AS delivery_slot,b.name AS batch_name,b.assessment_type
        FROM exam_sessions e
        JOIN batches b ON b.id=e.batch_id
        WHERE {session_where}
        ORDER BY b.slot,e.id
        """,
        session_params,
    ).fetchall()
    session_ids = {int(r["id"]) for r in sessions}

    row_clauses = ["e.status='submitted'", "COALESCE(e.is_test,0)=0"]
    row_params = []
    if assessment_id is not None:
        row_clauses.append("e.assessment_id=?")
        row_params.append(assessment_id)
    elif assessment:
        row_clauses.append("b.assessment_type=?")
        row_params.append(assessment)
    rows = conn.execute(
        f"""
        SELECT q.id AS question_id,q.part,q.batch_slot,q.topic,q.prompt,q.code,
               q.option_a,q.option_b,q.option_c,q.option_d,q.correct_option,
               COALESCE(q.points,1) AS points,sq.selected_option,e.id AS session_id,
               e.auto_total,b.slot AS delivery_slot,b.name AS batch_name
        FROM session_questions sq
        JOIN questions q ON q.id=sq.question_id
        JOIN exam_sessions e ON e.id=sq.session_id
        JOIN batches b ON b.id=e.batch_id
        WHERE {' AND '.join(row_clauses)}
        ORDER BY b.slot,q.part,COALESCE(q.position,q.id),q.id,e.id
        """,
        row_params,
    ).fetchall()

    # Build objective/rest-of-test scores from the administered items themselves.
    # This avoids contaminating point-biserial discrimination with bonus scores.
    objective_totals = defaultdict(float)
    assigned_max = defaultdict(float)
    session_item_scores = defaultdict(dict)
    for row in rows:
        sid = int(row["session_id"])
        points = _safe_float(row["points"], 1.0)
        earned = points if row["selected_option"] == row["correct_option"] else 0.0
        objective_totals[sid] += earned
        assigned_max[sid] += points
        session_item_scores[sid][("q", int(row["question_id"]))] = earned

    # Midterm bonus questions are also items. They are treated as dichotomous
    # short-answer items and included in the overall item list when applicable.
    bonus_rows = []
    if assessment == "midterm" and session_ids:
        bonus_params = []
        bonus_clauses = ["e.status='submitted'", "COALESCE(e.is_test,0)=0", "bq.assessment_type='midterm'"]
        if assessment_id is not None:
            bonus_clauses.append("e.assessment_id=?")
            bonus_params.append(assessment_id)
        bonus_rows = conn.execute(
            f"""
            SELECT bq.id AS bonus_question_id,bq.position,bq.topic,bq.prompt,bq.accepted_answer,
                   sba.answer_text,e.id AS session_id,e.auto_total,b.slot AS delivery_slot,b.name AS batch_name
            FROM session_bonus_answers sba
            JOIN bonus_questions bq ON bq.id=sba.bonus_question_id
            JOIN exam_sessions e ON e.id=sba.session_id
            JOIN batches b ON b.id=e.batch_id
            WHERE {' AND '.join(bonus_clauses)}
            ORDER BY bq.position,e.id
            """,
            bonus_params,
        ).fetchall()
        # Add bonus earned scores to the form-level matrix only when all sessions
        # actually include them. This makes midterm reliability reflect Part III too.
        for row in bonus_rows:
            sid = int(row["session_id"])
            earned = 1.0 if _short_answer_matches(row["answer_text"], row["accepted_answer"]) else 0.0
            session_item_scores[sid][("b", int(row["bonus_question_id"]))] = earned

    # Score summary uses the actual recorded assessment total. For custom tests,
    # use each student's administered maximum because randomized weighted forms
    # may not share an identical maximum.
    raw_scores = [_safe_float(r["auto_total"]) for r in sessions]
    percentages = []
    for r in sessions:
        sid = int(r["id"])
        denom = max_score
        if assessment == "custom":
            denom = assigned_max.get(sid) or max_score
        if denom and float(denom) > 0:
            percentages.append((_safe_float(r["auto_total"]) / float(denom)) * 100)
    score_summary = _score_summary(raw_scores, percentages, max_score=max_score)

    # Apply item filters after computing rest-of-test totals.
    filtered_rows = []
    for row in rows:
        if batch_slot and int(row["delivery_slot"]) != int(batch_slot):
            continue
        if part and int(row["part"]) != int(part):
            continue
        if topic and str(row["topic"] or "") != str(topic):
            continue
        filtered_rows.append(row)

    grouped = defaultdict(list)
    question_meta = {}
    for row in filtered_rows:
        qid = int(row["question_id"])
        grouped[qid].append(row)
        question_meta[qid] = row

    items = []
    for qid, attempts_rows in grouped.items():
        meta = question_meta[qid]
        n = len(attempts_rows)
        option_counts = {"A": 0, "B": 0, "C": 0, "D": 0}
        omitted = 0
        correct = 0
        item_points = _safe_float(meta["points"], 1.0)
        attempts = []
        for row in attempts_rows:
            sid = int(row["session_id"])
            selected = row["selected_option"]
            is_correct = 1 if selected == row["correct_option"] else 0
            correct += is_correct
            if selected in option_counts:
                option_counts[selected] += 1
            else:
                omitted += 1
            earned_here = item_points if is_correct else 0.0
            attempts.append({
                "session_id": sid,
                "correct": is_correct,
                "rest_score": objective_totals[sid] - earned_here,
            })

        p = correct / n if n else None
        response_rate = (n - omitted) / n if n else None
        r_pb = _pearson([a["correct"] for a in attempts], [a["rest_score"] for a in attempts])
        high_low_d, p_high, p_low = _high_low(attempts)
        wrong_options = [o for o in "ABCD" if o != meta["correct_option"]]
        functioning = sum(1 for o in wrong_options if n and option_counts[o] / n >= 0.05)
        nonfunctioning = 3 - functioning
        top_distractor = None
        if n and wrong_options:
            candidate = max(wrong_options, key=lambda o: option_counts[o])
            if option_counts[candidate] > 0:
                top_distractor = candidate

        flags = []
        if n >= MIN_DISCRIMINATION_N and p is not None and p < 0.30:
            flags.append("Very difficult item")
        if n >= MIN_DISCRIMINATION_N and p is not None and p > 0.95:
            flags.append("Very easy item")
        if n >= MIN_DISCRIMINATION_N and r_pb is not None and r_pb < 0:
            flags.append("Negative point-biserial")
        elif n >= MIN_DISCRIMINATION_N and r_pb is not None and r_pb < 0.15:
            flags.append("Weak point-biserial")
        if n >= MIN_HIGH_LOW_N and high_low_d is not None and high_low_d < 0:
            flags.append("Negative high-low discrimination")
        elif n >= MIN_HIGH_LOW_N and high_low_d is not None and high_low_d < 0.20:
            flags.append("Low high-low discrimination")
        if n and omitted / n >= 0.15:
            flags.append("High omission rate")
        if n >= MIN_DISCRIMINATION_N and nonfunctioning >= 2:
            flags.append("Multiple non-functioning distractors")

        items.append({
            "item_id": f"Q{qid}",
            "question_id": qid,
            "item_type": "mcq",
            "part": int(meta["part"] or 0),
            "batch_slot": int(meta["delivery_slot"] or meta["batch_slot"] or 0),
            "batch_name": meta["batch_name"],
            "topic": meta["topic"] or "General",
            "prompt": meta["prompt"],
            "code": meta["code"],
            "points": item_points,
            "options": {"A": meta["option_a"], "B": meta["option_b"], "C": meta["option_c"], "D": meta["option_d"]},
            "correct_option": meta["correct_option"],
            "n": n,
            "correct": correct,
            "p": p,
            "p_pct": round(p * 100, 1) if p is not None else None,
            "response_rate": response_rate,
            "response_pct": round(response_rate * 100, 1) if response_rate is not None else None,
            "omitted": omitted,
            "omission_pct": round((omitted / n) * 100, 1) if n else 0,
            "r_pb": r_pb,
            "r_pb_display": "—" if r_pb is None else f"{r_pb:.2f}",
            "correct_rate_band": _correct_rate_band(p),
            "discrimination_band": _discrimination_band(r_pb, n),
            "high_low_d": high_low_d,
            "high_low_display": "—" if high_low_d is None else f"{high_low_d:.2f}",
            "high_low_band": _high_low_band(high_low_d, n),
            "p_high": _format_float(p_high, 2),
            "p_low": _format_float(p_low, 2),
            "option_counts": option_counts,
            "option_pct": {o: round(option_counts[o] / n * 100, 1) if n else 0 for o in "ABCD"},
            "functioning_distractors": functioning,
            "nonfunctioning_distractors": nonfunctioning,
            "distractor_efficiency": round((functioning / 3) * 100, 1),
            "top_distractor": top_distractor,
            "flags": flags,
        })

    # Bonus short-answer items appear alongside MCQs for Midterm analysis.
    if assessment == "midterm" and (not part or int(part) == 3):
        bonus_grouped = defaultdict(list)
        bonus_meta = {}
        for row in bonus_rows:
            if batch_slot and int(row["delivery_slot"]) != int(batch_slot):
                continue
            if topic and str(row["topic"] or "") != str(topic):
                continue
            qid = int(row["bonus_question_id"])
            bonus_grouped[qid].append(row)
            bonus_meta[qid] = row
        for qid, attempts_rows in bonus_grouped.items():
            meta = bonus_meta[qid]
            attempts = []
            correct = 0
            omitted = 0
            for row in attempts_rows:
                sid = int(row["session_id"])
                answer = str(row["answer_text"] or "")
                is_correct = 1 if _short_answer_matches(answer, row["accepted_answer"]) else 0
                correct += is_correct
                if not answer.strip():
                    omitted += 1
                # auto_total already contains this bonus item; subtract it for
                # corrected item-total discrimination.
                rest = _safe_float(row["auto_total"]) - is_correct
                attempts.append({"session_id": sid, "correct": is_correct, "rest_score": rest})
            n = len(attempts)
            p = correct / n if n else None
            r_pb = _pearson([a["correct"] for a in attempts], [a["rest_score"] for a in attempts])
            high_low_d, p_high, p_low = _high_low(attempts)
            flags = []
            if n >= MIN_DISCRIMINATION_N and p is not None and p < 0.30:
                flags.append("Very difficult item")
            if n >= MIN_DISCRIMINATION_N and p is not None and p > 0.95:
                flags.append("Very easy item")
            if n >= MIN_DISCRIMINATION_N and r_pb is not None and r_pb < 0:
                flags.append("Negative point-biserial")
            elif n >= MIN_DISCRIMINATION_N and r_pb is not None and r_pb < 0.15:
                flags.append("Weak point-biserial")
            if n and omitted / n >= 0.15:
                flags.append("High omission rate")
            items.append({
                "item_id": f"B{int(meta['position'])}",
                "question_id": None,
                "bonus_question_id": qid,
                "item_type": "short_answer",
                "part": 3,
                "batch_slot": None,
                "batch_name": "All sets" if not batch_slot else meta["batch_name"],
                "topic": meta["topic"] or "Bonus",
                "prompt": meta["prompt"],
                "points": 1.0,
                "correct_option": None,
                "n": n,
                "correct": correct,
                "p": p,
                "p_pct": round(p * 100, 1) if p is not None else None,
                "response_rate": ((n - omitted) / n) if n else None,
                "response_pct": round(((n - omitted) / n) * 100, 1) if n else None,
                "omitted": omitted,
                "omission_pct": round((omitted / n) * 100, 1) if n else 0,
                "r_pb": r_pb,
                "r_pb_display": "—" if r_pb is None else f"{r_pb:.2f}",
                "correct_rate_band": _correct_rate_band(p),
                "discrimination_band": _discrimination_band(r_pb, n),
                "high_low_d": high_low_d,
                "high_low_display": "—" if high_low_d is None else f"{high_low_d:.2f}",
                "high_low_band": _high_low_band(high_low_d, n),
                "p_high": _format_float(p_high, 2),
                "p_low": _format_float(p_low, 2),
                "option_counts": {},
                "option_pct": {},
                "functioning_distractors": None,
                "nonfunctioning_distractors": None,
                "distractor_efficiency": None,
                "top_distractor": None,
                "flags": flags,
            })

    items.sort(key=lambda x: ((x.get("batch_slot") or 9999), x.get("part") or 0, x["item_id"]))

    topic_groups = defaultdict(lambda: {"correct": 0, "attempts": 0, "omitted": 0, "items": 0, "disc": []})
    for item in items:
        key = (item.get("part") or 0, item.get("topic") or "General")
        group = topic_groups[key]
        group["correct"] += item["correct"]
        group["attempts"] += item["n"]
        group["omitted"] += item["omitted"]
        group["items"] += 1
        if item["r_pb"] is not None:
            group["disc"].append(item["r_pb"])
    topic_summary = []
    for (pnum, topic_name), group in topic_groups.items():
        pct = (group["correct"] / group["attempts"] * 100) if group["attempts"] else 0
        omission = (group["omitted"] / group["attempts"] * 100) if group["attempts"] else 0
        avg_disc = _mean(group["disc"])
        topic_summary.append({
            "part": pnum,
            "topic": topic_name,
            "correct": group["correct"],
            "attempts": group["attempts"],
            "items": group["items"],
            "pct": round(pct, 1),
            "omission_pct": round(omission, 1),
            "avg_discrimination": _format_float(avg_disc, 2),
        })
    topic_summary.sort(key=lambda x: (x["pct"], x["part"], x["topic"]))

    # Delivery/set summaries, including reliability only when students within a
    # delivery actually share the same administered item form.
    sessions_by_batch = defaultdict(list)
    for r in sessions:
        sessions_by_batch[int(r["delivery_slot"])].append(r)
    batch_summary = []
    for slot in sorted(sessions_by_batch):
        group_sessions = sessions_by_batch[slot]
        ids = {int(x["id"]) for x in group_sessions}
        scores = [_safe_float(x["auto_total"]) for x in group_sessions]
        flags = [_safe_float(x["flagged_count"]) for x in group_sessions]
        form_scores = {sid: session_item_scores.get(sid, {}) for sid in ids}
        alpha, alpha_note = _common_form_alpha(form_scores)
        batch_summary.append({
            "slot": slot,
            "name": group_sessions[0]["batch_name"],
            "n": len(group_sessions),
            "avg_score": _format_float(_mean(scores), 2),
            "median_score": _format_float(float(median(scores)), 2) if scores else None,
            "sd_score": _format_float(_sample_sd(scores), 2),
            "avg_flags": _format_float(_mean(flags), 2),
            "alpha": _format_float(alpha, 2),
            "alpha_note": alpha_note,
        })

    # Overall internal consistency is reported only when every submitted student
    # received a common form. Otherwise surface the average of estimable form
    # alphas as a descriptive, explicitly form-level metric.
    overall_alpha, alpha_note = _common_form_alpha({sid: session_item_scores.get(sid, {}) for sid in session_ids})
    alpha_label = "Cronbach α / KR-20"
    if overall_alpha is None:
        estimable = [b["alpha"] for b in batch_summary if b["alpha"] is not None]
        if estimable:
            overall_alpha = _mean(estimable)
            alpha_label = "Mean form α"
            alpha_note = "The assessment used different forms/sets, so Custos reports the mean of estimable form-level alpha values rather than pooling non-equivalent forms."
    reliability = {
        "value": _format_float(overall_alpha, 2),
        "label": alpha_label,
        "band": _alpha_band(overall_alpha),
        "note": alpha_note,
        "sem": None,
    }
    if overall_alpha is not None and score_summary["sd"] is not None and 0 <= overall_alpha <= 1:
        reliability["sem"] = round(float(score_summary["sd"]) * math.sqrt(max(0.0, 1 - overall_alpha)), 2)

    return {
        "kind": "objective",
        "items": items,
        "topic_summary": topic_summary,
        "batch_summary": batch_summary,
        "submitted_students": len(sessions),
        "mean_score": score_summary["mean"],
        "score_summary": score_summary,
        "reliability": reliability,
        "flagged_items": sum(1 for item in items if item["flags"]),
        "assessment": assessment,
        "assessment_id": assessment_id,
        "method_note": "Classical item analysis. Difficulty is percent correct; discrimination uses corrected item-total point-biserial plus top/bottom 27% groups. Reliability is only pooled when students share a common administered form.",
    }


def build_programming_analysis(conn, assessment_id, max_score=None):
    """Task-level item analysis for a Programming Lab assessment."""
    lab = conn.execute("SELECT * FROM programming_labs WHERE assessment_id=?", (int(assessment_id),)).fetchone()
    if not lab:
        return {
            "kind": "programming", "tasks": [], "submitted_students": 0,
            "score_summary": _score_summary([], [], max_score=max_score),
            "reliability": {"value": None, "label": "Cronbach α", "band": "Not estimable", "note": "No lab is configured.", "sem": None},
            "flagged_items": 0,
        }

    sessions = conn.execute(
        """SELECT id,total_score,flagged_count FROM coding_sessions
           WHERE lab_id=? AND status='submitted' AND COALESCE(is_test,0)=0 ORDER BY id""",
        (lab["id"],),
    ).fetchall()
    session_ids = {int(r["id"]) for r in sessions}
    tasks = conn.execute(
        """SELECT * FROM programming_tasks WHERE lab_id=? AND COALESCE(active,1)=1 ORDER BY position,id""",
        (lab["id"],),
    ).fetchall()
    progress = conn.execute(
        """SELECT ctp.*,cs.total_score,cs.status,cs.is_test,pt.position,pt.title,pt.points
           FROM coding_task_progress ctp
           JOIN coding_sessions cs ON cs.id=ctp.session_id
           JOIN programming_tasks pt ON pt.id=ctp.task_id
           WHERE cs.lab_id=? AND cs.status='submitted' AND COALESCE(cs.is_test,0)=0
             AND COALESCE(pt.active,1)=1
           ORDER BY pt.position,cs.id""",
        (lab["id"],),
    ).fetchall()

    by_task = defaultdict(list)
    by_session = defaultdict(dict)
    for row in progress:
        by_task[int(row["task_id"])].append(row)
        by_session[int(row["session_id"])][("t", int(row["task_id"]))] = _safe_float(row["score"])

    task_items = []
    for task in tasks:
        tid = int(task["id"])
        rows = by_task.get(tid, [])
        points = max(_safe_float(task["points"], 0.0), 0.0)
        attempts = []
        scores = []
        pcts = []
        runs = []
        full = 0
        zero = 0
        task_submitted = 0
        for row in rows:
            score = _safe_float(row["score"])
            pct = (score / points) if points > 0 else 0.0
            sid = int(row["session_id"])
            rest = _safe_float(row["total_score"]) - score
            scores.append(score)
            pcts.append(pct)
            runs.append(_safe_float(row["run_count"]))
            full += 1 if points > 0 and score >= points else 0
            zero += 1 if score <= 0 else 0
            task_submitted += 1 if row["submitted_at"] else 0
            attempts.append({"session_id": sid, "correct": pct, "rest_score": rest})
        n = len(rows)
        success = _mean(pcts)
        r = _pearson([a["correct"] for a in attempts], [a["rest_score"] for a in attempts])
        high_low_d, p_high, p_low = _high_low(attempts)
        flags = []
        if n >= MIN_DISCRIMINATION_N and success is not None and success < 0.40:
            flags.append("Low average task attainment")
        if n >= MIN_DISCRIMINATION_N and success is not None and success > 0.95:
            flags.append("Very high task attainment")
        if n >= MIN_DISCRIMINATION_N and r is not None and r < 0:
            flags.append("Negative task-total discrimination")
        elif n >= MIN_DISCRIMINATION_N and r is not None and r < 0.15:
            flags.append("Weak task-total discrimination")
        if n >= MIN_HIGH_LOW_N and high_low_d is not None and high_low_d < 0.20:
            flags.append("Low high-low separation")
        task_items.append({
            "item_id": f"T{int(task['position'])}",
            "task_id": tid,
            "position": int(task["position"]),
            "title": task["title"],
            "points": points,
            "n": n,
            "avg_score": _format_float(_mean(scores), 2),
            "attainment": success,
            "attainment_pct": round(success * 100, 1) if success is not None else None,
            "avg_runs": _format_float(_mean(runs), 2),
            "full_score_count": full,
            "full_score_pct": round((full / n) * 100, 1) if n else 0,
            "zero_score_count": zero,
            "zero_score_pct": round((zero / n) * 100, 1) if n else 0,
            "submitted_count": task_submitted,
            "r_pb": r,
            "r_pb_display": "—" if r is None else f"{r:.2f}",
            "discrimination_band": _discrimination_band(r, n),
            "high_low_d": high_low_d,
            "high_low_display": "—" if high_low_d is None else f"{high_low_d:.2f}",
            "high_low_band": _high_low_band(high_low_d, n),
            "p_high": _format_float(p_high, 2),
            "p_low": _format_float(p_low, 2),
            "flags": flags,
        })

    scores = [_safe_float(r["total_score"]) for r in sessions]
    percentages = [(_safe_float(r["total_score"]) / float(max_score)) * 100 for r in sessions if max_score and float(max_score) > 0]
    score_summary = _score_summary(scores, percentages, max_score=max_score)
    alpha, alpha_note = _common_form_alpha({sid: by_session.get(sid, {}) for sid in session_ids})
    reliability = {
        "value": _format_float(alpha, 2),
        "label": "Cronbach α",
        "band": _alpha_band(alpha),
        "note": alpha_note,
        "sem": None,
    }
    if alpha is not None and score_summary["sd"] is not None and 0 <= alpha <= 1:
        reliability["sem"] = round(float(score_summary["sd"]) * math.sqrt(max(0.0, 1 - alpha)), 2)

    return {
        "kind": "programming",
        "tasks": task_items,
        "submitted_students": len(sessions),
        "mean_score": score_summary["mean"],
        "score_summary": score_summary,
        "reliability": reliability,
        "flagged_items": sum(1 for item in task_items if item["flags"]),
        "assessment_id": int(assessment_id),
        "method_note": "Programming tasks are treated as scored items. Custos reports mean task attainment, run behavior, corrected task-total correlation, top/bottom 27% separation, score spread, and internal consistency when enough submitted sessions exist.",
    }

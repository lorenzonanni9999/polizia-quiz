import json
import random
from pathlib import Path

_questions_by_id = {}
_ids_by_subject = {}
_subjects_order = []


def load_questions(json_path):
    global _questions_by_id, _ids_by_subject, _subjects_order
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    _questions_by_id = {q["id"]: q for q in data}
    _ids_by_subject = {}
    for q in data:
        _ids_by_subject.setdefault(q["subject"], []).append(q["id"])
    _subjects_order = list(_ids_by_subject.keys())


def get_subjects():
    return list(_subjects_order)


def subject_question_count(subject):
    return len(_ids_by_subject.get(subject, []))


def get_question(question_id):
    return _questions_by_id[question_id]


def build_single_subject_quiz(subject, count):
    pool = _ids_by_subject.get(subject, [])
    count = max(0, min(count, len(pool)))
    if count <= 0:
        return []
    chosen_ids = random.sample(pool, count)
    selected = []
    for qid in chosen_ids:
        order = [0, 1, 2, 3, 4]
        random.shuffle(order)
        selected.append({
            "question_id": qid,
            "subject": subject,
            "option_order": order,
        })
    return selected


def build_quiz(subject_quota):
    """Pick random questions per subject/quota and shuffle each question's
    options. Returns a list of dicts ready to be persisted as attempt_answers,
    grouped by subject, each with a fresh random option order."""
    selected = []
    for subject in _subjects_order:
        quota = subject_quota.get(subject, 0)
        pool = _ids_by_subject.get(subject, [])
        quota = min(quota, len(pool))
        if quota <= 0:
            continue
        chosen_ids = random.sample(pool, quota)
        for qid in chosen_ids:
            order = [0, 1, 2, 3, 4]
            random.shuffle(order)
            selected.append({
                "question_id": qid,
                "subject": subject,
                "option_order": order,
            })
    return selected

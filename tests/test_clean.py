"""Rejection rules of worker/clean.py (Task 1 cleaning)."""
import json

import clean

SCHEMA = json.loads(open("data/schema.json", encoding="utf-8").read())


def rec(raw, text="wake me at seven tomorrow"):
    return {"id": 1, "text": text, "teacher_raw": raw}


def obj(**kw):
    base = {"intent": "alarm_set", "date": None, "time": None, "place": None}
    base.update(kw)
    return json.dumps(base)


def test_good_record_is_kept():
    assert clean.classify(rec(obj(time="seven", date="tomorrow")), SCHEMA) is None


def test_invalid_json_is_rule_a():
    assert clean.classify(rec("{not json"), SCHEMA) == "a"


def test_wrong_keys_is_rule_b():
    assert clean.classify(rec('{"intent": "alarm_set"}'), SCHEMA) == "b"


def test_unknown_intent_is_rule_c():
    assert clean.classify(rec(obj(intent="make_coffee")), SCHEMA) == "c"


def test_slot_not_in_command_is_rule_d():
    assert clean.classify(rec(obj(place="paris")), SCHEMA) == "d"

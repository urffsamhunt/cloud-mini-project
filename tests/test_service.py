"""Service logic that needs no model: schema validation, probes, prompt format."""
import app
import common
from fastapi.testclient import TestClient


def test_validate_accepts_four_key_object():
    raw = '{"intent": "weather_query", "date": null, "time": null, "place": "london"}'
    assert app.validate(raw) is not None


def test_validate_rejects_bad_outputs():
    assert app.validate("not json") is None
    assert app.validate('{"intent": "weather_query"}') is None                      # missing keys
    assert app.validate('{"intent": "dance", "date": null, "time": null, "place": null}') is None
    assert app.validate('{"intent": "alarm_set", "date": null, "time": null, "place": null, "x": 1}') is None


def test_probes_before_model_is_loaded():
    client = TestClient(app.app)   # no "with": start-up (model download) is not triggered
    assert client.get("/healthz").status_code == 200
    r = client.get("/readyz")
    assert r.status_code == 503 and r.json() == {"status": "loading"}


def test_parse_rejects_empty_text():
    assert TestClient(app.app).post("/parse", json={"text": ""}).status_code == 422


def test_prompt_format_is_the_training_format():
    assert common.prompt_for("hello") == "Command: hello\nJSON:"

"""score.py quality gate and the NACL file."""
import json
import subprocess
import sys


def run(*args):
    return subprocess.run([sys.executable, *args], capture_output=True, text=True)


def test_quality_gate_fails_on_invalid_predictions(tmp_path):
    preds = tmp_path / "p.jsonl"
    gold = [json.loads(line) for line in open("data/validation.jsonl", encoding="utf-8") if line.strip()]
    preds.write_text("".join(json.dumps({"id": g["id"], "prediction": "garbage"}) + "\n" for g in gold))
    r = run("tools/score.py", str(preds), "data/validation.jsonl", "--min-validity", "95")
    assert r.returncode == 1


def test_quality_gate_passes_on_perfect_predictions(tmp_path):
    preds = tmp_path / "p.jsonl"
    gold = [json.loads(line) for line in open("data/validation.jsonl", encoding="utf-8") if line.strip()]
    keys = ("intent", "date", "time", "place")
    preds.write_text("".join(json.dumps({"id": g["id"], "prediction": json.dumps({k: g[k] for k in keys})}) + "\n"
                             for g in gold))
    assert run("tools/score.py", str(preds), "data/validation.jsonl", "--min-validity", "95").returncode == 0


def test_nacl_decides_all_sample_packets_correctly():
    for packets in ("network/packets_sample.jsonl", "network/packets_extra.jsonl"):
        r = run("tools/nacl_sim.py", "network/nacl.json", packets, "--check")
        assert "WRONG" not in r.stdout, r.stdout

"""Try the teacher prompt on a few pool commands (Task 1, step 4).

Usage: python3 scripts/test_teacher.py [N] [--host URL]
Runs each sampled command twice (temperature 0, seed 42) to check determinism,
and reports how many replies are valid JSON with the four required keys.
"""
import argparse, json, random, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEYS = ["intent", "date", "time", "place"]


def ask(host, prompt, num_predict=128):
    body = json.dumps({
        "model": "phi3.5", "prompt": prompt, "stream": False,
        "options": {"temperature": 0, "seed": 42, "num_predict": num_predict, "stop": ["\n"]},
    }).encode()
    req = urllib.request.Request(f"{host}/api/generate", body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.load(r)["response"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("n", nargs="?", type=int, default=10)
    ap.add_argument("--host", default="http://localhost:11434")
    a = ap.parse_args()

    template = (ROOT / "prompts" / "teacher_prompt.txt").read_text()
    rows = [json.loads(l) for l in (ROOT / "data" / "commands_pool.jsonl").open()]
    random.Random(0).shuffle(rows)

    ok = same = 0
    for row in rows[: a.n]:
        prompt = template.replace("{command}", row["text"])
        t0 = time.time()
        r1 = ask(a.host, prompt)
        dt = time.time() - t0
        r2 = ask(a.host, prompt)
        try:
            obj = json.loads(r1)
            valid = isinstance(obj, dict) and sorted(obj) == sorted(KEYS)
        except ValueError:
            valid = False
        ok += valid
        same += r1 == r2
        print(f"{'OK ' if valid else 'BAD'} {'same' if r1 == r2 else 'DIFF'} {dt:5.1f}s  {row['text']!r}\n      -> {r1!r}")
    print(f"\nvalid {ok}/{a.n}   deterministic {same}/{a.n}")


if __name__ == "__main__":
    main()

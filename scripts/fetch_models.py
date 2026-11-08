"""Make out/models/<version>/ ready for upload: from a local archive or from the GitHub Release.

Usage: python3 scripts/fetch_models.py v1 [v2 ...]

For each version:
  1. if out/models/<v>/model-<v>.tar exists (you trained it yourself), use it;
  2. otherwise download it from the GitHub Release `model-<v>` of this repository
     (override the repository with MODEL_REPO=owner/name);
  3. verify its SHA-256 against release/model-<v>.sha256 (committed in the repository);
  4. extract it and write files.sha256 and model.sha256, the same layout `make train` produces.
Standard library only.
"""
import hashlib
import os
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def repo_slug():
    if os.environ.get("MODEL_REPO"):
        return os.environ["MODEL_REPO"]
    url = subprocess.check_output(["git", "-C", str(ROOT), "remote", "get-url", "origin"], text=True).strip()
    return url.removesuffix(".git").split("github.com")[-1].lstrip(":/")


def prepare(v):
    d = ROOT / "out" / "models" / v
    tar = d / f"model-{v}.tar"
    want = (ROOT / "release" / f"model-{v}.sha256").read_text().split()[0]
    if not tar.exists():
        d.mkdir(parents=True, exist_ok=True)
        url = f"https://github.com/{repo_slug()}/releases/download/model-{v}/model-{v}.tar"
        print(f"downloading {url}")
        urllib.request.urlretrieve(url, tar)
    got = sha256_file(tar)
    if got != want:
        sys.exit(f"{tar}: SHA-256 {got} does not match release/model-{v}.sha256 ({want})")
    print(f"{tar.name}: checksum OK")
    with tarfile.open(tar) as t:
        t.extractall(d, filter="data")
    names = sorted(m for m in os.listdir(d) if m != tar.name and not m.endswith(".sha256"))
    (d / "files.sha256").write_text("".join(f"{sha256_file(d / n)}  {n}\n" for n in names))
    (d / "model.sha256").write_text(f"{want}  {tar.name}\n")


if __name__ == "__main__":
    for version in sys.argv[1:]:
        prepare(version)

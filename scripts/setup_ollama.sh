#!/usr/bin/env bash
# One-time host setup for the teacher model (needs sudo). Run once per machine.
#  - makes the Ollama service listen on all interfaces so pods in k3d can reach it
#  - serves one request at a time, so teacher outputs stay reproducible
#  - pulls the fixed teacher model, phi3.5
# Assumes Ollama is installed as a systemd service (curl -fsSL https://ollama.com/install.sh | sh).
set -euo pipefail
sudo mkdir -p /etc/systemd/system/ollama.service.d
printf '[Service]\nEnvironment="OLLAMA_HOST=0.0.0.0"\nEnvironment="OLLAMA_NUM_PARALLEL=1"\n' \
  | sudo tee /etc/systemd/system/ollama.service.d/override.conf >/dev/null
sudo systemctl daemon-reload
sudo systemctl restart ollama
for _ in $(seq 1 30); do curl -s -m 2 localhost:11434/api/tags >/dev/null && break; sleep 1; done
ollama pull phi3.5
curl -s localhost:11434/api/tags | python3 -I -c "import sys,json; [print(m['name'], m['digest'][:12], m['details']['quantization_level']) for m in json.load(sys.stdin)['models']]"

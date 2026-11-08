# AI use

## Tools

- **Claude Code** (Anthropic's coding assistant, running in my terminal with access to this repository). Most of the code, manifests and documentation in this repository were written by it at my request, step by step, task by task.
- **phi3.5 through Ollama** is the teacher model required by the project (Task 1). It labelled the 3,000 commands; it was not used to write any code or text.
- No other AI tool (no ChatGPT, Copilot, etc.) was used for this project.

## What the assistant was used for

| Area | What it did |
|---|---|
| Reading the handout | Summarised the seven tasks and checked my proposed stack (Azure, SST, LM Studio) against the handout. It said that stack did not comply, so I switched to k3d, SeaweedFS and Ollama. |
| Task 1 | Wrote the teacher prompt and the test script, the labelling worker, the Indexed Job, the cleaning script, the cluster and SeaweedFS manifests, the Makefile and the setup scripts. |
| Task 2 | Wrote the training, prediction and upload scripts and the two configs; ran training on the CPU. |
| Task 3 | Wrote the FastAPI service, the Dockerfile and the two check scripts. |
| Task 4 | Wrote `k8s/app.yaml` and `scripts/task4_evidence.sh`. |
| Task 5 | Computed the subnets, wrote the NACL and the explanation. |
| Task 6 | Wrote the unit tests, the lint config, the workflow, `scripts/fetch_models.py` and this file. |
| Other | The personal test page in `playground/` (not part of the graded pipeline); setup logs in `docs/`. |

## How I checked what it produced

The assistant ran every command itself and I could read the output and the logs in `docs/SETUP_LOG.md`. Checks that went beyond "it ran":

- **Teacher output:** 20 test commands run twice each (valid JSON and identical both times) before launching the full job; the first version of the prompt gave only 6 valid answers out of 10, which led to adding the stop sequence.
- **Cleaning:** reject counts by rule are written to `results/clean_report.json`; the dataset checksum is checked again before every training run.
- **Training:** a first run was much too slow; the cause was found by profiling (float16 weights) and fixed by loading in float32. Model scores come from `tools/score.py`, the handout's script, not from my own metric. The base Pythia scored 0, as expected.
- **Service:** an API check script covers the status codes, headers, empty input and the fault-injection switch; a limits test runs the image with 1 CPU and 1 GiB.
- **Kubernetes:** the evidence script sends a steady stream of requests during pod deletion and rolling update and counts the status codes. Its first run showed HTTP 502 errors during the rolling update; the cause (Traefik still routing to a terminating pod) was fixed with a `preStop` delay and the test was rerun.
- **Network:** `nacl_sim.py` on the handout's sample packets plus 23 packets I had the assistant write. Two of those expected answers were wrong (the reply rule also allows port 8000 outbound) and were corrected, not the rules.
- **Secrets:** gitleaks over the git history reports no leaks; credentials are generated at deploy time and live only in Kubernetes Secrets.

## Known gaps in my checking

- I have not independently re-derived the loss values or the scores; I rely on the scripts and the saved logs.
- `make train` giving byte-identical weights on a second run has not been tested.
- The GitHub Actions workflow could only be validated for YAML syntax and for the individual commands locally; it has to be run on GitHub (see the report for links to the runs).

## Corrections I would make to assistant output

(Student: add here anything you changed or rejected yourself before submission.)

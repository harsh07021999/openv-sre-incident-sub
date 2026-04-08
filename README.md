---
title: SRE Incident Response Simulator
emoji: 🚨
colorFrom: red
colorTo: yellow
sdk: docker
pinned: false
app_port: 8000
tags:
  - openenv
---

# 🚨 SRE Incident Response Simulator

An **OpenEnv** environment that simulates real-world production incidents for training and evaluating AI-powered SRE (Site Reliability Engineering) agents.

An AI agent receives a live production alert — with severity, affected services, metrics, event logs, and runbook excerpts — and must diagnose the root cause and apply the correct remediation through a structured action API, exactly as a human on-call SRE would.

---

## Motivation

Every tech company runs on-call rotations. SREs diagnose alerts, query metrics, apply remediations, and write postmortems under time pressure. This environment fills a real gap in the agent evaluation landscape: **there is no existing OpenEnv benchmark for AIOps / operational AI systems**.

Training agents on this environment teaches:
- Multi-step causal reasoning over system dependency graphs
- Prioritised information gathering (run the right queries, not all queries)
- Root-cause discrimination (distinguishing red herrings from real signals)
- Time-sensitive decision-making under P1 urgency

---

## Action Space

```python
class SREAction(Action):
    command: Literal[
        "acknowledge",    # Acknowledge the alert — always the first step
        "run_query",      # Run a PromQL/log/trace diagnostic query
        "apply_fix",      # Apply a remediation (restart, rollback, patch config)
        "resolve",        # Mark the incident resolved
        "escalate",       # Page another team
        "add_annotation", # Add a postmortem note
        "no_op",          # No action this step
    ]
    parameters: dict     # Command-specific payload (see below)
```

### Parameter shapes by command

| Command | Parameters |
|---|---|
| `acknowledge` | `{}` |
| `run_query` | `{"target": "<service or metric>", "query_type": "metrics\|logs"}` |
| `apply_fix` | `{"action": "restart_deployment\|rollback\|patch_config\|scale_up", "service": "...", ...}` |
| `resolve` | `{}` |
| `escalate` | `{"team": "...", "reason": "..."}` |
| `add_annotation` | `{"note": "..."}` |
| `no_op` | `{}` |

### `apply_fix` action shapes

```json
{"action": "restart_deployment", "service": "user-profile-svc"}
{"action": "rollback",           "service": "payment-svc", "to_version": "v2.1.4"}
{"action": "patch_config",       "service": "postgres",    "param": "max_connections", "value": 200}
{"action": "scale_up",           "service": "worker-pool", "replicas": 10}
```

---

## Observation Space

```python
class SREObservation(Observation):
    incident_id: str         # e.g. "INC-2024-001"
    severity: str            # "P1" | "P2" | "P3"
    service: str             # Primary affected service(s)
    alert_title: str         # Short alert summary
    alert_body: str          # Full alert with timeline and affected services
    metrics_snapshot: dict   # Key metric values at current step
    recent_events: list[str] # Chronological event/deployment log
    runbook: str             # Relevant runbook excerpt
    acknowledged: bool       # Whether the alert has been acknowledged
    resolved: bool           # Whether the incident is resolved
    time_elapsed_seconds: int
    task_name: str
    hint: str                # Contextual hint to guide diagnosis
    last_action_result: str  # Output of the previous action (query result, fix result, etc.)
    # Inherited from Observation:
    reward: float
    done: bool
    metadata: dict
```

---

## Tasks

### Task 1 — `memory-leak-easy` (P3) 🟢

**Scenario**: `user-profile-svc` pods are OOMKilling due to a memory leak. 2 of 4 pods are regularly restarting. Memory usage is at 95.2%.

**Correct action sequence**:
1. `acknowledge`
2. `run_query` → memory metrics
3. `apply_fix` → `{"action": "restart_deployment", "service": "user-profile-svc"}`
4. `resolve`

**Why easy**: Single service, no red herrings, the runbook explicitly names the fix. Rewards full score for a 4-step episode.

**Baseline score**: ~0.80 (frontier models)

---

### Task 2 — `latency-spike-medium` (P2) 🟡

**Scenario**: `api-gateway` P95 latency is 2340ms (SLO: 500ms) with 8.3% error rate. A new gateway version was deployed 45 minutes ago — but the root cause is PostgreSQL connection pool exhaustion (max_connections=100, 847 connections waiting).

**Correct action sequence**:
1. `acknowledge`
2. `run_query` → gateway latency breakdown (reveals postgres timeout)
3. `run_query` → postgres connection pool (reveals pool exhausted)
4. `apply_fix` → `{"action": "patch_config", "service": "postgres", "param": "max_connections", "value": 200}`
5. `resolve`

**Why medium**: The gateway deploy is a red herring. Agent must correlate two queries to identify the real bottleneck before applying the fix.

**Baseline score**: ~0.55 (frontier models)

---

### Task 3 — `cascading-failure-hard` (P1) 🔴

**Scenario**: Full P1 outage. `order-svc` (100% error), `inventory-svc` (87% error), and `payment-svc` (100% error) are all down in a cascade. Root cause: `payment-svc v2.2.0` introduced a breaking gRPC proto change (added a required field `loyalty_points`). Red herring: a k8s node pool patch happened 5 minutes before the deploy (but completed cleanly).

**Correct action sequence**:
1. `acknowledge`
2. `run_query` → payment-svc (reveals proto break in v2.2.0)
3. `run_query` → inventory-svc (confirms it's a victim)
4. `run_query` → order-svc (confirms full cascade)
5. `apply_fix` → `{"action": "rollback", "service": "payment-svc", "to_version": "v2.1.4"}`
6. `resolve`

**Why hard**: Multi-service cascade, sequence-dependent grading, red herring distractor, steeper time penalty (P1 urgency).

**Baseline score**: ~0.30 (frontier models)

---

## Reward Function

Rewards are **shaped** — the agent receives signal at every step, not just at episode end.

| Event | Reward |
|---|---|
| `acknowledge` alert | +0.05 to +0.10 |
| Relevant diagnostic query (first of each type) | +0.05 to +0.10 |
| Correct `apply_fix` | +0.50 to +0.55 |
| `resolve` after correct fix | +0.25 |
| Wrong `apply_fix` | −0.10 to −0.15 |
| `resolve` before applying fix | −0.15 |
| Each step after threshold (step 5–6) | −0.02 to −0.03 |

A **perfect episode** (no wasted steps) accumulates rewards summing to **1.0**. Final score = `clamp(sum_rewards, 0.0, 1.0)`.

---

## Setup

### Prerequisites

- Python 3.10+
- `pip install -r requirements.txt` (or via pyproject.toml)

### Demo Script (No API Key Required)

Run the automated interactive demo to see how exactly the simulation behaves and tests the agent automatically across the hardest cascading failure scenario. 

```bash
python demo.py
```

### Run Locally (no Docker)

```bash
cd sre-incident-sim

# Install dependencies
pip install -e ".[dev]"

# Smoke test (no LLM required)
python server/environment.py

# Start the HTTP server (task selectable via env var)
SRE_TASK=memory-leak-easy uvicorn server.app:app --reload --port 8000
```

### Baseline Inference Script

```bash
export HF_TOKEN="your-token"
export API_BASE_URL="https://router.huggingface.co/v1"
export MODEL_NAME="Qwen/Qwen2.5-72B-Instruct"

python inference.py
```

Expected stdout format:
```
[START] task=memory-leak-easy env=sre-incident-sim model=Qwen/Qwen2.5-72B-Instruct
[STEP] step=1 action={"command":"acknowledge","parameters":{}} reward=0.10 done=false error=null
[STEP] step=2 action={"command":"run_query","parameters":{"target":"user-profile-svc memory"}} reward=0.10 done=false error=null
[STEP] step=3 action={"command":"apply_fix","parameters":{"action":"restart_deployment","service":"user-profile-svc"}} reward=0.55 done=false error=null
[STEP] step=4 action={"command":"resolve","parameters":{}} reward=0.25 done=true error=null
[END] success=true steps=4 score=1.000 rewards=0.10,0.10,0.55,0.25
```

### Docker

```bash
# Build
docker build -t sre-incident-sim:latest -f server/Dockerfile .

# Run (default task: memory-leak-easy)
docker run -p 8000:8000 sre-incident-sim:latest

# Run a specific task
docker run -p 8000:8000 -e SRE_TASK=cascading-failure-hard sre-incident-sim:latest
```

### OpenEnv Validation

```bash
cd sre-incident-sim
openenv validate
```

---

## API Reference

Once the server is running at `http://localhost:8000`:

| Endpoint | Method | Description |
|---|---|---|
| `/reset` | POST | Reset environment, returns initial observation |
| `/step` | POST | Execute an action, returns observation + reward |
| `/state` | GET | Current episode state |
| `/schema` | GET | Action / observation JSON schemas |
| `/health` | GET | Health check |
| `/ws` | WebSocket | Persistent session for low-latency multi-step interaction |
| `/web` | GET | Interactive web UI |
| `/docs` | GET | Swagger / OpenAPI documentation |

### curl examples

```bash
# Reset
curl -X POST http://localhost:8000/reset -H "Content-Type: application/json" -d '{}'

# Acknowledge
curl -X POST http://localhost:8000/step \
  -H "Content-Type: application/json" \
  -d '{"command": "acknowledge", "parameters": {}}'

# Run a query
curl -X POST http://localhost:8000/step \
  -H "Content-Type: application/json" \
  -d '{"command": "run_query", "parameters": {"target": "postgres connection pool", "query_type": "metrics"}}'

# Apply fix
curl -X POST http://localhost:8000/step \
  -H "Content-Type: application/json" \
  -d '{"command": "apply_fix", "parameters": {"action": "patch_config", "service": "postgres", "param": "max_connections", "value": 200}}'

# Resolve
curl -X POST http://localhost:8000/step \
  -H "Content-Type: application/json" \
  -d '{"command": "resolve", "parameters": {}}'
```

---

## Project Structure

```
sre-incident-sim/
├── openenv.yaml          # OpenEnv manifest (spec_version, name, app, port)
├── pyproject.toml        # Project metadata and dependencies
├── requirements.txt      # Explicit pip constraints 
├── demo.py               # Local automated demo (no API keys required)
├── inference.py          # Baseline LLM agent agent script
├── README.md             # This file (also HF Space frontmatter)
├── __init__.py           # Package exports
├── models.py             # Typed Pydantic Action + Observation models
├── client.py             # SREIncidentEnv HTTP/WebSocket client
└── server/
    ├── __init__.py
    ├── app.py            # FastAPI app (via openenv-core create_app)
    ├── environment.py    # Core environment logic + reward shaping + grader
    ├── scenarios.py      # All 3 task scenario definitions (data only)
    └── Dockerfile        # Multi-stage container image
```

---

## Baseline Scores

| Task | Difficulty | Qwen2.5-72B |
|---|---|---|
| `memory-leak-easy` | Easy (P3) | ~0.80 |
| `latency-spike-medium` | Medium (P2) | ~0.55 |
| `cascading-failure-hard` | Hard (P1) | ~0.30 |
| **Average** | | **~0.55** |

Scores are reproducible given the same model, temperature (0.2), and environment state (fully deterministic — no randomness).

---

## Environment Variable Reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `HF_TOKEN` | Yes (inference) | — | Hugging Face / API key |
| `OPENAI_API_KEY` | Alt. to HF_TOKEN | — | OpenAI API key fallback |
| `API_BASE_URL` | No | HF router | LLM API base URL |
| `MODEL_NAME` | No | Qwen2.5-72B-Instruct | Model identifier |
| `SRE_TASK` | No (server only) | `memory-leak-easy` | Active task for HTTP server |

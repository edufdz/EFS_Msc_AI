# How to Run the Agent Debugger Platform

This guide covers running the full platform: the web UI (FastAPI backend + React frontend), the sample agent used for testing, and the CLI pipeline.

## Prerequisites

- **Python 3.10+**
- **Node.js 18+** or **Bun** (frontend and sample agent)
- **API keys** in `debugger-platforn/.env`:
  - `ANTHROPIC_API_KEY` — used by the platform's AI analysis phases (not needed with `--skip-ai` / mock mode)
  - `OPENAI_API_KEY` — used by the sample car dealership agent

## 1. One-Time Setup

### Python environment

```bash
cd debugger-platforn

# Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
pip install fastapi uvicorn   # required by the web API
```

Alternatively, `source run.sh` creates/activates the venv for CLI use (it installs a minimal dependency set — prefer `requirements.txt` for the full platform).

### Environment variables

Create `debugger-platforn/.env`:

```
ANTHROPIC_API_KEY=sk-ant-...
```

The web API loads this file automatically on startup.

### Frontend dependencies

```bash
cd debugger-platforn/web/frontend
npm install        # or: bun install
```

### Sample agent dependencies (optional)

```bash
cd fake-car-dealership-agent
npm install        # or: bun install
echo "OPENAI_API_KEY=sk-..." > .env
```

## 2. Running the Web Platform

The web platform needs **two processes** (three if you also run the sample agent). Open a terminal for each.

### Terminal 1 — Backend API (port 8000)

```bash
cd debugger-platforn
source venv/bin/activate
uvicorn web.api.app:app --reload --port 8000
```

Health check: http://localhost:8000/api/health

### Terminal 2 — Frontend (port 5173)

```bash
cd debugger-platforn/web/frontend
npm run dev
```

Open **http://localhost:5173** in your browser. Vite proxies `/api` and `/ws` requests to the backend on port 8000 (see `vite.config.ts`), so no extra configuration is needed.

### Terminal 3 — The sandboxed production agent (port 3098) ← the demo target

This is the verbatim TechRepair WhatsApp agent (real LangGraph, real prompts,
real guardrails) running against an in-memory fake database. It is what the
dissertation's results were produced against.

```bash
cd tech_repair-live-agent
bun server.ts
```

Requires `ANTHROPIC_API_KEY` in `tech_repair-live-agent/.env` (an
`OPENAI_API_KEY` is optional — without it the event verifier degrades but the
agent still runs). Endpoints:

| Route | Purpose |
|---|---|
| `POST /chat` | `{ message, session_id? }` → `{ response, tool_calls }` |
| `GET /db` | inspect the fake database (escalations, mutations) |
| `POST /reset` | fresh fake DB + sessions — **run this between batches** |

Smoke test:

```bash
curl -s -X POST http://localhost:3098/chat -H 'Content-Type: application/json' \
  -d '{"message":"Hola, quiero saber el estado de mi orden 4151234567","session_id":"smoke"}'
```

You should get a Spanish reply plus an `order_lookup` tool call for Valeria
Mendoza García's Galaxy S24 Ultra.

> The fake database is **shared across tests within a run** (sessions are
> isolated, the database is not). Call `POST /reset` between batches.

### Terminal 4 — Sample agent (optional, port 3099)

The mock car dealership agent ("AutoServe AI") gives the platform a real endpoint to test against:

```bash
cd fake-car-dealership-agent
bun server.ts       # or: npm run api
```

The agent API listens on http://localhost:3099 (override with `PORT=xxxx`).

### Production build (single server)

To serve the frontend from the backend instead of running Vite:

```bash
cd debugger-platforn/web/frontend
npm run build       # outputs to web/frontend/dist

cd ../..
uvicorn web.api.app:app --port 8000
```

The backend serves the built frontend at http://localhost:8000 when `web/frontend/dist` exists.

## 3. Running the CLI Pipeline (no web UI)

The pipeline runs Phases A→E: **Analyze → Generate Tests → Execute → Diagnose → Improve**.

```bash
cd debugger-platforn
source venv/bin/activate

# Full offline run against the sample agent (no API keys needed)
python run_pipeline.py ../fake-car-dealership-agent --mock --skip-ai --test-count 20 --count 10

# Stop after test execution (Phase C)
python run_pipeline.py ../fake-car-dealership-agent --mock --skip-ai --stop-after c

# Resume from an existing agent map (skips Phase A)
python run_pipeline.py ../fake-car-dealership-agent --agent-map agent_map.json --mock --skip-ai
```

Useful flags:

| Flag | Effect |
|------|--------|
| `--mock` | Simulate the agent instead of calling a real endpoint |
| `--skip-ai` | Offline heuristics only — no Anthropic API calls or key needed |
| `--stop-after a\|b\|c\|d\|e` | How far the pipeline runs (default `e`) |
| `--agent-map <file>` | Skip Phase A |
| `--test-suite <file>` | Skip Phase B |

Individual phases can also be run standalone: `analyze.py`, `generate_tests.py`, `execute_tests.py`, `diagnose_failures.py`, `improve_agent.py`. See `debugger-platforn/README.md` for per-phase options (GAN mode, rate limiting, A/B testing, etc.).

## 4. Research Workflow (RQ1–RQ4)

The offline research loop — anonymise the production export, build ground
truth, compare blind vs feedback-seeded generation — is documented in
[docs/RESEARCH_WORKFLOW.md](docs/RESEARCH_WORKFLOW.md). Quick version:

```bash
cd debugger-platforn

# 1. Anonymise the extracted conversations (once)
python3 anonymize_export.py \
    --input ../docs/tech_repair-conversations-export.json \
    --output ../docs/tech_repair-conversations-anonymized.json

# 2. Run the predictive-validity experiments
python3 run_experiments.py \
    --export ../docs/tech_repair-conversations-anonymized.json \
    --agent-map tech_repair_whatsapp_map.json --budget 100
```

Artefacts land in `experiments_output/<timestamp>/` (results.json, REPORT.md,
charts). The same workflow is available in the web UI under **Research**.

Optional simulation endpoint + production-vs-simulation fidelity comparison:

```bash
python3 sandbox_bridge.py serve --agent-map tech_repair_whatsapp_map.json --port 8099
python3 sandbox_bridge.py replay --agent-map tech_repair_whatsapp_map.json \
    --export ../docs/tech_repair-conversations-anonymized.json --sample 50 \
    --output fidelity_report.json
```

## 5. The demo: end-to-end against the live agent

The full research loop in three commands, with the agent running on :3098.

```bash
cd debugger-platforn

# 1. Execute simulated conversations against the real agent code.
#    Persona context must be stated explicitly — it materially changes
#    conversation shape, so scripted runs never inherit a silent default.
python3 execute_tests.py \
    pipeline_output/session-636fc721/generated/test_suite.json \
    tech_repair_whatsapp_map_live.json \
    -o results_demo -c 10 -w 4 --ai-personas --seed 42 \
    --persona-context

# 2. Score the run with the *production* scorer and compare against reality.
python3 compare_real_vs_sim.py \
    --real ../investigation/02_data/real/tech_repair-conversations-anonymized.json \
    --sim results_demo/conversations.json \
    -o results_demo/comparison
```

Step 1 prints pass/fail, tool coverage, cost, and writes
`conversations.json` (every dialogue, verdict-independent). Step 2 prints
category coverage and JSD against the real corpus with its noise floor.

Persona-context flags:

| Flag | Effect |
|---|---|
| `--persona-context` | use the default fake-customer context (the dissertation's setting) |
| `--persona-context-file PATH` | use your own |
| `--no-persona-context` | run without it, explicitly |

Omitting all three on a non-interactive terminal is an error rather than a
silent default.

## 6. The anonymisation system

```bash
cd anonymization/backend
./venv/bin/python -m uvicorn app:app --port 8077
```

`GET /api/health`, `POST /api/anonymize` and `POST /api/anonymize/preview` take
a file upload (`.txt` or `.json`):

```bash
curl -s -X POST http://localhost:8077/api/anonymize -F "file=@conversation.txt"
```

Frontend review surface:

```bash
cd anonymization/frontend && npm install && npm run dev
```

Batch-anonymising a production export goes through the platform, which reuses
this same backend:

```bash
cd debugger-platforn
python3 anonymize_export.py --input raw-export.json --output anonymized.json
```

This **fails closed**: if the spaCy/Presidio backend is not importable it aborts
rather than silently falling back to regex-only redaction. Pass
`--allow-fallback` only if you explicitly accept weaker redaction (never for
research output).

## 7. Running tests

```bash
# Platform — 748 tests
cd debugger-platforn && ./venv/bin/python -m pytest tests/ -q

# Anonymiser — 51 tests
cd anonymization && ./backend/venv/bin/python -m pytest tests/ -q
```

## 8. Regenerating the dissertation figures

```bash
cd "dissertation edu/tools"
../../debugger-platforn/venv/bin/python render_langgraph.py
../../debugger-platforn/venv/bin/python render_chapter3_figures.py
```

See `dissertation edu/FIGURES.md` for what each figure is and where it belongs,
and `dissertation edu/CORRECTIONS.md` for the claim-by-claim audit of the
dissertation against this repository.

## Quick Reference

| Component | Directory | Command | Port |
|-----------|-----------|---------|------|
| Backend API | `debugger-platforn` | `uvicorn web.api.app:app --reload --port 8000` | 8000 |
| Frontend | `debugger-platforn/web/frontend` | `npm run dev` | 5173 |
| Sample agent | `fake-car-dealership-agent` | `bun server.ts` | 3099 |
| CLI pipeline | `debugger-platforn` | `python run_pipeline.py <agent> --mock --skip-ai` | — |

## Troubleshooting

- **Frontend loads but API calls fail** — make sure the backend is running on port 8000; the Vite proxy targets `http://localhost:8000`.
- **`ModuleNotFoundError: fastapi` / `uvicorn: command not found`** — install them into the venv: `pip install fastapi uvicorn`.
- **AI phases fail with auth errors** — check `ANTHROPIC_API_KEY` in `debugger-platforn/.env`, or add `--skip-ai` to run offline.
- **Sample agent exits immediately** — it requires `OPENAI_API_KEY` in `fake-car-dealership-agent/.env`.

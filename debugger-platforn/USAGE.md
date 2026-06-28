# Usage Guide: Running the Agent Debugger

All commands run from the `debugger-platforn/` directory.

```
cd debugger-platforn
```

---

## Pipeline overview

```
Phase A: Analyze    ──>  agent_map.json
Phase B: Generate   ──>  test_suite.json  (+ persona_library.json, scenario_catalog.json)
Phase C: Execute    ──>  test_run_report.json + failure_inbox.json + traces/
Phase D: Diagnose   ──>  diagnosis_report.json
Phase E: Improve    ──>  improvement outputs
```

Each phase takes the output of the previous phase as input. You can run them individually, chain them together with flags (`--diagnose`, `--improve`), or use `run_pipeline.py` to execute everything in one command.

### Prerequisites

```bash
pip install -e .                    # Core dependencies
pip install -e ".[ui]"              # Web dashboard (websockets)
pip install -e ".[dev]"             # Dev tools (pytest)
cp .env.example .env               # Add your ANTHROPIC_API_KEY
```

---

## Phase A: Analyze agent codebase

Scans the agent source code and produces an `agent_map.json` describing its tools, prompts, memory, framework, and risks.

**Script:** `analyze.py`

```bash
# Basic (offline, no AI)
python analyze.py /path/to/agent/repo --skip-ai

# With AI semantic analysis (needs ANTHROPIC_API_KEY)
python analyze.py /path/to/agent/repo

# Custom output path
python analyze.py /path/to/agent/repo -o my_agent_map.json
```

**Output:** `agent_map.json`

| Flag | Default | Description |
|------|---------|-------------|
| `--skip-ai` | off | Skip AI analysis (offline heuristics only) |
| `--output, -o` | `agent_map.json` | Output file path |
| `--language, -l` | all | Language filter for scanning (e.g., python, javascript) |
| `--prompt-encoding` | utf-8 | Encoding for prompt files |
| `--verbose, -v` | off | Show parse warnings |

**What it does:**
1. Ingests the repo — scans for code files, entry points, prompt files
2. Static analysis — parses with Tree-sitter to extract functions, classes, imports
3. Pattern detection — identifies framework (OpenAI, LangChain, etc.), tools, prompts, memory
4. Risk analysis — flags security risks for tools and prompts
5. AI semantic analysis (optional) — uses Claude to understand goal, workflow, guardrails
6. Generates `agent_map.json` with everything the later phases need

> **Note:** For the fake-car-dealership agent, `agent_map.json` is already provided in `debugger-platforn/`. You can skip this phase.

---

## Phase B: Generate test suite

Creates personas, scenarios, coverage goals, and combines them into an executable test suite.

**Script:** `generate_tests.py`

```bash
# Offline with template personas (fast, no API cost)
python generate_tests.py agent_map.json --skip-ai --count 20


# With AI enrichment (generates additional personas + scenarios via Claude)
python generate_tests.py agent_map.json --count 250 --persona-count 8 --scenario-count 10

# Custom output directory
python generate_tests.py agent_map.json --skip-ai --count 20 -o my_tests/
```

**Output directory** (default `generated/`):

| File | Description |
|------|-------------|
| `test_configuration.json` | Coverage goals, sandbox config |
| `persona_library.json` | All personas with traits, styles, edge behaviors |
| `scenario_catalog.json` | All scenarios and variants |
| `test_suite.json` | The executable test cases (input for Phase C) |

| Flag | Default | Description |
|------|---------|-------------|
| `--output-dir, -o` | `generated` | Output directory |
| `--skip-ai` | off | Skip all AI generation |
| `--count, -c` | 250 | Target number of test cases |
| `--persona-count` | 8 | AI-generated personas to add |
| `--scenario-count` | 10 | AI-generated scenarios to add |z
| `--variants` | 3 | Variants per base scenario |
| `--seed` | random | Random seed |
| `--language, -l` | auto | Language for generated content |
| `--use-tlahuac` | off | Load personas/scenarios from tlahuac data |
| `--tlahuac-dir` | auto | Path to tlahuac data directory |

**What it does (4 steps):**

1. **B1 — Coverage configuration:** Calculates coverage goals per tool, defines tool combinations to test, generates sandbox config (mock modes, rate limits, latency simulation)
2. **B2 — Persona library:** Loads template personas, generates tool-attack personas (one per tool), flow-attack personas (one per tool chain), and optionally AI-generated personas. Each persona has 10 trait dimensions, style settings, and edge behaviors
3. **B3 — Scenario catalog:** Loads template scenarios, generates variants (happy path, error path, edge case), optionally creates AI scenarios. Each scenario specifies required/optional/forbidden tools and success/failure conditions
4. **B4 — Test suite assembly:** Combines personas + scenarios + coverage goals using affinity-weighted pairing (not random) into executable test cases

You can also run each step individually:

```bash
python coverage_builder.py agent_map.json       # Step B1 only
python persona_builder.py agent_map.json         # Step B2 only
python scenario_builder.py agent_map.json        # Step B3 only
```

---

## Phase C: Execute tests

Runs the test suite against the agent with parallel workers, collects per-test traces, and generates a failure inbox.

**Script:** `execute_tests.py`

```bash
# Mock agent (no real agent needed — for pipeline testing)
python execute_tests.py generated/test_suite.json agent_map.json --mock

# Mock with AI persona messages (more realistic but costs $)
python execute_tests.py generated/test_suite.json agent_map.json --mock --ai-personas

# Against a real agent API endpoint
python execute_tests.py generated/test_suite.json agent_map.json

# Limit to 10 tests, custom output
python execute_tests.py generated/test_suite.json agent_map.json --mock --count 10 -o results

# With web dashboard (see below)
python execute_tests.py generated/test_suite.json agent_map.json --mock --ui --count 10

# When you run Phase C, you'll be prompted: "Do you want to add context for the personas to use? (y/n)"
# If y, you can paste inline text (e.g. VIN, model name) or a path to a file (e.g. ./context.txt).

# Execute then auto-run diagnosis (Phase C + D)
python execute_tests.py generated/test_suite.json agent_map.json --mock --diagnose

# Execute + diagnose + improve (Phase C + D + E)
python execute_tests.py generated/test_suite.json agent_map.json --mock --improve --apply-fixes
```

## Testing the fake-car-dealership agent

The repo includes a sample agent at `fake-car-dealership-agent/` (Prestige Motors / AutoServe AI) and a pre-built `agent_map.json` in `debugger-platforn/`.

### With mock agent (no real agent process needed)

```bash
cd debugger-platforn

# Generate test suite (or use existing generated/)
python generate_tests.py agent_map.json --skip-ai --count 20

# Run Phase C with mock agent
python execute_tests.py generated/test_suite.json agent_map.json --mock --count 10 -o results

# With web dashboard
python execute_tests.py generated/test_suite.json agent_map.json --mock --ui --count 10
```

### Testing persona context

Before Phase C runs, the CLI asks: **Do you want to add context for the personas to use? (y/n)**. If you choose **y**:

- **Inline:** type or paste context (e.g. `VIN: 1HGBH41JXMN109186, Model: Honda Accord 2021`) and press Enter.
- **File:** enter a path (e.g. `./context.txt` or `./data/vin_list.txt`). The file contents are loaded and used as context.

Personas (especially with `--ai-personas`) will see this context in their instructions and can mention it when talking to the agent. The execution summary shows **Persona context: yes** when context was loaded.

**Automated tests:** run the persona-context tests (from `debugger-platforn/` with pytest installed):

```bash
python -m pytest tests/test_persona_context.py -v
```

### Against the real agent

**Terminal 1** — start the agent API (from repo root):

```bash
cd fake-car-dealership-agent
bun run api
# Listens on http://localhost:3099
```

**Terminal 2** — run Phase C:

```bash
cd debugger-platforn
python execute_tests.py generated/test_suite.json agent_map.json --ui --ai-personas --count 10 -o results
```

The API URL is **not** stored in `agent_map.json` (the map is generated from code and has no endpoint). It is read from **`agent_endpoints.json`** in the same directory (or the current working directory). That file defines which `localhost` (or URL) to use. See [Agent endpoints config](#agent-endpoints-config) below.

#### Agent endpoints config

Create (or edit) **`agent_endpoints.json`** next to your `agent_map.json` (or in the current working directory). It determines which base URL is used when running tests against a real agent:

- **`default`** — used when the agent is not listed by ID (e.g. `"default": "http://localhost:3099"`).
- **`by_agent_id`** — optional map of `agent_id` → URL for per-agent endpoints.

Example:

```json
{
  "default": "http://localhost:3099",
  "by_agent_id": {
    "08b16417-9e06-4521-b0e5-6f835e71af83": "http://localhost:3099"
  }
}
```

To use another port (e.g. `3000`), run the agent with `PORT=3000 bun run api` and set that URL in `agent_endpoints.json` (in `default` and/or the relevant `by_agent_id` entry).

**Output directory** (default `results/`):

| File | Description |
|------|-------------|
| `test_run_report.json` | Pass/fail stats, coverage, timing, cost |
| `failure_inbox.json` | All failures with full context |
| `conversations.log` | JSON-lines log (for live viewer / standalone dashboard) |
| `traces/` | Per-test trace files with full conversation history |

### Core flags

| Flag | Default | Description |
|------|---------|-------------|
| `--output, -o` | `results` | Output directory |
| `--workers, -w` | 10 | Max parallel workers |
| `--count, -c` | 0 (all) | Limit to first N tests |
| `--mock` | off | Use mock agent (no real agent needed) |
| `--ai-personas` | off | Use AI for persona messages (costs $) |
| `--traces/--no-traces` | on | Save per-test trace files |
| `--fail-rate` | 0.05 | Mock agent failure rate |
| `--language, -l` | auto | Language for persona messages (auto-detects from agent_map) |
| `--seed` | random | Random seed |

### Monitoring flags

| Flag | Default | Description |
|------|---------|-------------|
| `--no-monitor` | off | Disable the Rich terminal dashboard |
| `--ui` | off | Launch web dashboard at `http://localhost:8080` |
| `--ui-port` | 8080 | Port for the web dashboard |

### Chained phase flags

| Flag | Default | Description |
|------|---------|-------------|
| `--diagnose` | off | Auto-run Phase D after execution |
| `--skip-ai` | off | Skip AI in diagnosis (offline heuristics) |
| `--use-embeddings` | off | Use embeddings for clustering |
| `--max-retries` | 3 | Max retries for AI API calls |
| `--backoff-base` | 2.0 | Exponential backoff base (seconds) |
| `--backoff-max` | 60.0 | Maximum backoff delay (seconds) |
| `--ai-workers` | 1 | Parallel AI workers for diagnosis |
| `--improve` | off | Auto-run Phase D + E after execution (implies `--diagnose`) |
| `--apply-fixes` | off | Actually apply fixes in Phase E (default is dry run) |
| `--baseline-fail-rate` | 0.05 | Baseline fail rate for A/B test |
| `--fixed-fail-rate` | 0.01 | Fixed fail rate for A/B test |
| `--smoke-limit` | 10 | Max tests for Phase E smoke test |
| `--full-limit` | 50 | Max tests for Phase E full test |

### Web dashboard (`--ui`)

When you pass `--ui`, Phase C starts a WebSocket server and serves a browser-based live dashboard instead of the Rich terminal monitor.

```bash
python execute_tests.py generated/test_suite.json agent_map.json --mock --ui
# Then open http://localhost:8080 in your browser
```

**Dashboard features:**

- **Active Simulations tab** — Up to 8 live cards showing test conversations in progress: chat bubbles, tool call pills (color-coded by status), live status
- **Conversations tab** — Full conversation viewer for any test (running or completed). Select a test from the list to see every user/agent message, tool calls with expandable input/output, and pass/fail result. Search and filter by status
- **Left panel** — Progress bar, pass/fail/error/timeout counts, pass rate, tool coverage checklist, cost/latency/speed metrics
- **Right panel** — Scrolling event feed with timestamps, and failure inbox with expandable conversation traces

Cards auto-remove 4 seconds after completion. The dashboard auto-reconnects if the connection drops. All data persists for the duration of the run.

Custom port: `--ui --ui-port 8085` then open `http://localhost:8085`.

### Standalone dashboard (for existing logs)

You can also run the dashboard against an existing `conversations.log` without re-running tests:

```bash
python -m src.monitor_ui.server --log results/conversations.log --port 8080
# Open http://localhost:8080
```

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--log` | yes | — | Path to conversations.log |
| `--port` | no | 8080 | Server port |
| `--host` | no | 0.0.0.0 | Server host |
| `--report` | no | — | Path to test_run_report.json (enables `/api/report`) |

### Live conversation viewer (legacy)

# Open http://localhost:8080
```

---

## Phase D: Diagnose failures

Clusters failures by root cause, identifies patterns, generates minimal reproductions, and proposes fixes.

**Script:** `diagnose_failures.py`

```bash
# AI-powered analysis (needs ANTHROPIC_API_KEY)
python diagnose_failures.py results/failure_inbox.json results/test_run_report.json agent_map.json

# Offline heuristics only (no API cost)
python diagnose_failures.py results/failure_inbox.json results/test_run_report.json agent_map.json --skip-ai

# Custom output
python diagnose_failures.py results/failure_inbox.json results/test_run_report.json agent_map.json -o results/diagnosis.json
```

**Output:** `diagnosis_report.json`

| Flag | Default | Description |
|------|---------|-------------|
| `--output, -o` | `diagnosis_report.json` | Output file |
| `--skip-ai` | off | Offline heuristics only |
| `--use-embeddings` | off | Use embeddings for clustering |
| `--max-retries` | 3 | API retry attempts |
| `--backoff-base` | 2.0 | Exponential backoff base (seconds) |
| `--backoff-max` | 60.0 | Maximum backoff delay (seconds) |

**What it does:**
1. **Failure clustering** — Groups similar failures by root cause pattern (error_handling, tool_misconfiguration, prompt_issues, etc.)
2. **Root cause analysis** — Identifies common error types and key indicators
3. **Severity assessment** — Rates each cluster: low, medium, high, critical
4. **Minimal reproduction** — Creates the simplest conversation to reproduce each cluster
5. **Fix proposals** — Suggests fixes with estimated effort, fix rate, and risk level
6. **Priority ranking** — Ranks clusters by impact to guide what to fix first

### Diagnosis Performance Metrics

The diagnosis summary includes metrics that measure the **quality of the testing process itself** (not just the agent under test):

| Metric | Formula | What it measures |
|--------|---------|-----------------|
| **Bug Discovery Rate** | `unique_clusters / total_tests × 100` | Efficiency — how many unique bugs the tester finds per test executed. Higher = more efficient testing. |
| **Redundancy Rate** | `(total_failures − unique_clusters) / total_failures × 100` | Waste — percentage of test failures that are duplicates of already-found bugs. Lower = less wasted effort. |
| **Severity-Weighted Score** | `Σ(cluster.failures × severity_weight) / total_failures` | Average severity per failure. Weights: critical=5, high=3, medium=2, low=1. Higher = tester finds more severe bugs. |

These metrics appear in the diagnosis summary panel alongside existing stats (failure rate, root cause breakdown, severity distribution).

> You can also run Phase D automatically from Phase C by adding `--diagnose` to the execute command.

---

## Phase E: Improve agent

Applies fixes from Phase D, runs A/B tests, validates improvements, generates regression tests, and builds a deployment package.

**Script:** `improve_agent.py`

```bash
# Dry run (no files modified — preview what would happen)
python improve_agent.py results/diagnosis_report.json agent_map.json generated/test_suite.json

# Apply fixes
python improve_agent.py results/diagnosis_report.json agent_map.json generated/test_suite.json --apply

# With agent source directory and custom limits
python improve_agent.py results/diagnosis_report.json agent_map.json generated/test_suite.json \
  --apply -d /path/to/agent/src --smoke-limit 20 --full-limit 100
```

**Output directory** (default `improvement/`):

| File | Description |
|------|-------------|
| `applied_fixes.json` | List of fixes applied (or previewed) |
| `ab_test_results.json` | Baseline vs fixed comparison |
| `improvement_report.json` | Overall improvement metrics |
| `regression_tests.json` | New tests for fixed issues |
| `deployment/` | Patched source code ready to deploy |

| Flag | Default | Description |
|------|---------|-------------|
| `--output, -o` | `improvement` | Output directory |
| `--apply` | off | Actually apply fixes (default is dry run) |
| `--agent-dir, -d` | `.` | Agent source directory for patching |
| `--baseline-fail-rate` | 0.05 | Baseline fail rate for A/B comparison |
| `--fixed-fail-rate` | 0.01 | Fixed fail rate for A/B comparison |
| `--smoke-limit` | 10 | Max tests for smoke test |
| `--full-limit` | 50 | Max tests for full test |
| `--workers, -w` | 10 | Parallel workers |

**What it does:**
1. **Fix application** — Applies proposed fixes to agent code (dry run or real)
2. **Smoke tests** — Quick validation on limited test set
3. **A/B testing** — Compares baseline vs fixed failure rates with statistical significance (p-value)
4. **Regression tests** — Generates new test cases that exercise the fixes
5. **Deployment package** — Creates ready-to-deploy patched source code

> You can also run Phase E automatically from Phase C by adding `--improve --apply-fixes`.

---

## Full pipeline (A through E in one command)

Runs all phases sequentially. You can skip phases and stop early.

**Script:** `run_pipeline.py`

```bash
# Full pipeline, offline, mock agent
python run_pipeline.py /path/to/agent --mock --skip-ai --test-count 20 --count 10

# Stop after Phase C (no diagnosis/improvement)
python run_pipeline.py /path/to/agent --mock --skip-ai --stop-after c

# Skip Phase A (use existing agent map)
python run_pipeline.py /path/to/agent --agent-map agent_map.json --mock --skip-ai --test-count 20

# Skip Phase A + B (use existing agent map + test suite)
python run_pipeline.py /path/to/agent \
  --agent-map agent_map.json \
  --test-suite generated/test_suite.json \
  --mock --count 10

# Full pipeline with AI
python run_pipeline.py /path/to/agent --test-count 250 --ai-personas
```

### Pipeline flags

**General:**

| Flag | Default | Description |
|------|---------|-------------|
| `--output-dir, -o` | `pipeline_output` | Base output directory for all phases |
| `--skip-ai` | off | Skip all AI calls across all phases |
| `--language, -l` | auto | Language for conversations |
| `--seed` | random | Random seed |
| `--verbose, -v` | off | Verbose output |
| `--stop-after` | `e` | Stop after phase: `a`, `b`, `c`, `d`, or `e` |

**Phase A:**

| Flag | Default | Description |
|------|---------|-------------|
| `--agent-map` | — | Skip Phase A; use this existing agent_map.json |
| `--prompt-encoding` | utf-8 | Encoding for prompt files |

**Phase B:**

| Flag | Default | Description |
|------|---------|-------------|
| `--test-suite` | — | Skip Phase B; use this existing test_suite.json |
| `--test-count` | 250 | Target test cases to generate |
| `--persona-count` | 8 | AI personas to generate |
| `--scenario-count` | 10 | AI scenarios to generate |

**Phase C:**

| Flag | Default | Description |
|------|---------|-------------|
| `--mock` | off | Use mock agent connector |
| `--fail-rate` | 0.05 | Mock agent failure rate |
| `--workers, -w` | 10 | Parallel workers |
| `--count, -c` | 0 (all) | Limit tests to execute |
| `--ai-personas` | off | Use AI for persona messages |

**Phase D:**

| Flag | Default | Description |
|------|---------|-------------|
| `--use-embeddings` | off | Use embeddings for clustering |
| `--max-retries` | 3 | API retry attempts |
| `--backoff-base` | 2.0 | Backoff base seconds |
| `--backoff-max` | 60.0 | Backoff max seconds |

**Phase E:**

| Flag | Default | Description |
|------|---------|-------------|
| `--apply-fixes` | off | Apply fixes (default: dry run) |
| `--baseline-fail-rate` | 0.05 | Baseline fail rate for A/B |
| `--fixed-fail-rate` | 0.01 | Fixed fail rate for A/B |
| `--smoke-limit` | 10 | Smoke test limit |
| `--full-limit` | 50 | Full test limit |

**Pipeline output structure:**

```
pipeline_output/
├── agent_map.json                   (Phase A)
├── generated/
│   ├── test_configuration.json      (Phase B)
│   ├── persona_library.json         (Phase B)
│   ├── scenario_catalog.json        (Phase B)
│   └── test_suite.json              (Phase B)
├── results/
│   ├── test_run_report.json         (Phase C)
│   ├── failure_inbox.json           (Phase C)
│   ├── conversations.log            (Phase C)
│   ├── diagnosis_report.json        (Phase D)
│   └── traces/                      (Phase C)
│       ├── trace_0001_*.json
│       └── ...
└── improvement/                     (Phase E)
    ├── applied_fixes.json
    ├── ab_test_results.json
    ├── improvement_report.json
    ├── regression_tests.json
    └── deployment/
```

---

## Common workflows

### Quick smoke test (offline, no API cost)

```bash
python generate_tests.py agent_map.json --skip-ai --count 10
python execute_tests.py generated/test_suite.json agent_map.json --mock --count 10
```

### Smoke test with web dashboard

```bash
python generate_tests.py agent_map.json --skip-ai --count 10
python execute_tests.py generated/test_suite.json agent_map.json --mock --ui --count 10
# Open http://localhost:8080 and watch tests run live
```

### Full test run with diagnosis

```bash
python generate_tests.py agent_map.json --skip-ai --count 100
python execute_tests.py generated/test_suite.json agent_map.json --mock --diagnose -o results
```

### End-to-end with improvement

```bash
python generate_tests.py agent_map.json --skip-ai --count 50
python execute_tests.py generated/test_suite.json agent_map.json --mock --improve --apply-fixes -o results
```

### One-command pipeline

```bash
python run_pipeline.py /path/to/agent --mock --skip-ai --test-count 20 --count 10
```

### Reproduce a specific failure

Look at the trace file for the failed test, then re-run with the same seed:

```bash
python generate_tests.py agent_map.json --skip-ai --count 50 --seed 42
python execute_tests.py generated/test_suite.json agent_map.json --mock --count 1 --seed 42
```

---



---

## Quick reference

| Phase | Script | Input | Output | Key Flags |
|-------|--------|-------|--------|-----------|
| **A** | `analyze.py` | agent repo | `agent_map.json` | `--skip-ai` |
| **B** | `generate_tests.py` | `agent_map.json` | `test_suite.json` + config, personas, scenarios | `--skip-ai`, `--count`, `--use-tlahuac` |
| **C** | `execute_tests.py` | `test_suite.json`, `agent_map.json` | `test_run_report.json`, `failure_inbox.json`, `traces/` | `--mock`, `--ui`, `--ai-personas`, `--diagnose`, `--improve` |
| **D** | `diagnose_failures.py` | `failure_inbox.json`, `test_run_report.json`, `agent_map.json` | `diagnosis_report.json` | `--skip-ai` |
| **E** | `improve_agent.py` | `diagnosis_report.json`, `agent_map.json`, `test_suite.json` | `improvement/` | `--apply` |
| **All** | `run_pipeline.py` | agent repo | all of the above | `--stop-after`, `--agent-map`, `--test-suite` |

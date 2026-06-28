# Agent Debugger Platform

AI-powered testing and diagnosis platform for conversational agents.
Discover architecture, generate tests, execute them, diagnose failures, and validate improvements — all from the CLI.

## Pipeline Architecture

```
 ┌──────────────┐    ┌──────────────────┐    ┌────────────────┐    ┌──────────────────┐    ┌──────────────────┐
 │   Phase A    │    │     Phase B      │    │    Phase C     │    │    Phase D       │    │    Phase E       │
 │   Analyze    │───▶│  Generate Tests   │───▶│  Execute Tests │───▶│  Diagnose        │───▶│  Improve         │
 │              │    │  (B1→B2→B3→B4)   │    │                │    │                  │    │                  │
 │ analyze.py   │    │ generate_tests.py │    │execute_tests.py│    │diagnose_failures │    │ improve_agent.py │
 └──────────────┘    └──────────────────┘    └────────────────┘    └──────────────────┘    └──────────────────┘
       │                     │                       │                      │                       │
  agent_map.json     test_suite.json         test_run_report.json   diagnosis_report.json    improvement/
                     persona_library.json    failure_inbox.json                               applied_fixes.json
                     scenario_catalog.json                                                    ab_test_results.json
                     test_configuration.json                                                  deployment/
```

## Quick Start: Full Pipeline

Run the entire A → B → C → D → E pipeline with a single command:

```bash
# Full pipeline — offline, mock agent
python run_pipeline.py /path/to/agent --mock --skip-ai --test-count 20 --count 10

# Stop after Phase C (no diagnosis or improvement)
python run_pipeline.py /path/to/agent --mock --skip-ai --stop-after c

# Resume from existing agent map (skip Phase A)
python run_pipeline.py /path/to/agent --agent-map agent_map.json --mock --skip-ai

# Resume from existing test suite (skip Phases A + B)
python run_pipeline.py /path/to/agent --agent-map agent_map.json --test-suite test_suite.json --mock
```

## Quick Start: Phase B (Test Generation)

Generate a complete test suite from an agent map in one command:

```bash
# Offline mode (no API key needed)
python generate_tests.py agent_map.json --skip-ai --count 20

# With AI enrichment
python generate_tests.py agent_map.json --count 250 --persona-count 8 --scenario-count 10

# Custom output directory
python generate_tests.py agent_map.json --skip-ai --output-dir my_tests/
```

## Quick Start: Phase C — Execute Tests

```bash
# Mock mode (no real agent API needed)
python execute_tests.py test_suite.json agent_map.json --mock --count 50

# Against a real endpoint
python execute_tests.py test_suite.json agent_map.json --workers 5
```

## Chaining Phases

### C → D: `--diagnose`

Run tests and auto-diagnose failures in one command:

```bash
python execute_tests.py test_suite.json agent_map.json --mock --count 50 --diagnose --skip-ai
```

### C → D → E: `--diagnose --improve`

Run tests, diagnose, and improve in one command:

```bash
python execute_tests.py test_suite.json agent_map.json --mock --count 50 --diagnose --improve --skip-ai

# With real fix application
python execute_tests.py test_suite.json agent_map.json --mock --diagnose --improve --apply-fixes
```

The `--improve` flag implies `--diagnose` (auto-enabled if not set).

### `--stop-after` (pipeline only)

Control how far the pipeline runs:

| Flag | Phases Run |
|------|-----------|
| `--stop-after a` | A only |
| `--stop-after b` | A → B |
| `--stop-after c` | A → B → C |
| `--stop-after d` | A → B → C → D |
| `--stop-after e` | A → B → C → D → E (default) |

## Skipping Phases

Use `--agent-map` and `--test-suite` to skip early phases and resume from the middle:

| Flag | Effect |
|------|--------|
| `--agent-map path/to/agent_map.json` | Skip Phase A; use existing agent map |
| `--test-suite path/to/test_suite.json` | Skip Phase B; use existing test suite |
| Both flags combined | Start directly at Phase C |

## GAN Mode (Adversarial Testing)

Phase C supports an optional **GAN-style architecture** inspired by Generative Adversarial Networks:

- **Generator (G)**: the persona simulator — generates test conversations
- **Critic (D)**: a second LLM that evaluates conversation quality, detects false positives, and coaches the Generator

Both agents use cheap models (Haiku) — they correct each other, so neither needs to be individually brilliant. This keeps costs low while improving test quality.

```bash
# Enable GAN mode
python execute_tests.py test_suite.json agent_map.json --mock --ai-personas --gan

# Customize Critic behavior
python execute_tests.py test_suite.json agent_map.json --mock --ai-personas --gan \
    --critic-model claude-haiku-4-5 --max-restarts 3 --quality-threshold 4.0
```

| Flag | Default | Description |
|------|---------|-------------|
| `--gan` | off | Enable Generator + Critic adversarial mode |
| `--critic-model` | `claude-haiku-4-5` | Model for the Critic agent |
| `--max-restarts` | `2` | Max times Critic can restart a conversation |
| `--quality-threshold` | `3.0` | Min quality score (0-10) to avoid restart |
| `--evaluate-every` | `2` | Critic evaluates every N agent turns (lower = more accurate but costlier) |

### Cost Impact

In GAN mode, each test makes **~2x the LLM calls** (Generator + Critic).
With `--max-restarts=2`, worst case is **~6x** for a single test.

| Scenario | LLM calls vs standard |
|----------|-----------------------|
| No restarts | ~2x |
| 1 restart | ~4x |
| 2 restarts (max) | ~6x |

Use `--evaluate-every 4` or higher to reduce Critic calls at the cost of less frequent intervention.

## Phase D — Diagnose Failures

```bash
# Offline heuristics only (no API key required)
python diagnose_failures.py results/failure_inbox.json results/test_run_report.json agent_map.json --skip-ai

# AI-powered analysis
python diagnose_failures.py results/failure_inbox.json results/test_run_report.json agent_map.json
```

### Performance Metrics

Phase D outputs metrics that measure testing quality (not just the agent):

| Metric | What it measures |
|--------|-----------------|
| Bug Discovery Rate | Unique bugs found per test executed (%) — testing efficiency |
| Redundancy Rate | Duplicate findings (%) — lower is better |
| Severity-Weighted Score | Average severity per failure (critical=5, high=3, medium=2, low=1) |

## Phase E — Improve & Validate

Apply fixes, run A/B tests, generate regression tests, and build deployment packages:

```bash
# Dry run (preview what would change)
python improve_agent.py results/diagnosis_report.json agent_map.json test_suite.json

# Apply fixes and run full pipeline
python improve_agent.py results/diagnosis_report.json agent_map.json test_suite.json --apply

# Tune A/B test parameters
python improve_agent.py results/diagnosis_report.json agent_map.json test_suite.json \
    --baseline-fail-rate 0.10 --fixed-fail-rate 0.02 --smoke-limit 20 --full-limit 100
```

### Phase E Options

| Flag | Default | Description |
|------|---------|-------------|
| `--apply` | off | Actually modify files (default is dry run) |
| `--agent-dir` | `.` | Agent source directory for file patching |
| `--baseline-fail-rate` | `0.05` | Baseline mock failure rate for A/B |
| `--fixed-fail-rate` | `0.01` | Fixed mock failure rate for A/B |
| `--smoke-limit` | `10` | Max tests in smoke test |
| `--full-limit` | `50` | Max tests in full test |
| `--workers` | `10` | Parallel workers for A/B test execution |

### Phase E Output

| File | Description |
|------|-------------|
| `applied_fixes.json` | Fixes applied with before/after diffs |
| `ab_test_results.json` | Baseline vs fixed comparison with p-values |
| `improvement_report.json` | Statistical validation and deploy readiness |
| `regression_tests.json` | Tests to prevent future regressions |
| `deployment/` | Ready-to-deploy package with changelog and rollback docs |

## Rate Limiting

All Anthropic API calls use exponential backoff with jitter.
Control the behaviour with CLI flags:

| Flag | Default | Description |
|------|---------|-------------|
| `--max-retries` | `3` | Maximum number of retry attempts per API call |
| `--backoff-base` | `2.0` | Base delay in seconds (doubled each retry) |
| `--backoff-max` | `60.0` | Maximum delay cap in seconds |
| `--ai-workers` | `1` | Parallel AI workers (reserved for future use) |
| `--skip-ai` | off | Bypass all AI calls; use offline heuristics only |

### Backoff Formula

```
delay = min(backoff_base * 2^attempt + random(0, 1), backoff_max)
```

On each retry the delay roughly doubles, plus a random jitter of 0–1 s to avoid
thundering-herd effects. Retryable errors:

- **HTTP 429** — Rate limit exceeded (`RateLimitError`)
- **HTTP 529** — API overloaded (`APIStatusError`)
- **Connection errors** — Transient network failures (`APIConnectionError`)

All other API errors are raised immediately.

### Recommended Settings by API Tier

| Tier | `--max-retries` | `--backoff-base` | `--backoff-max` |
|------|-----------------|-------------------|-----------------|
| Free / Build | `5` | `4.0` | `120.0` |
| Scale | `3` | `2.0` | `60.0` |
| Enterprise | `2` | `1.0` | `30.0` |

### Skipping AI

Pass `--skip-ai` to run diagnosis using offline heuristics only. This is useful for:

- CI pipelines where no API key is available
- Rapid iteration during development
- Avoiding API costs during testing

The offline mode uses TF-IDF clustering, pattern-matching root-cause analysis,
and template-based fix proposals. Results are deterministic and instant.

## Running Tests

```bash
# Phase D tests
pytest tests/test_diagnosis.py -v

# Phase E tests
pytest tests/test_improvement.py -v

# Pipeline integration tests
pytest tests/test_pipeline.py -v

# All tests
pytest tests/ -v
```

## AI Validation

Compare offline vs AI-powered diagnosis:

```bash
python run_ai_validation.py
```

This loads the existing offline report and Phase C outputs, runs a full
AI-powered diagnosis, and prints a side-by-side comparison table.

## Project Structure

```
src/
  analysis/           # Static code analysis (Tree-sitter)
  ai_analyzer/        # AI semantic analysis (Claude)
  coverage/           # Phase B3: coverage goals & sandbox config
  diagnosis/          # Phase D: failure diagnosis
    clustering.py     # TF-IDF / embedding-based failure clustering
    engine.py         # Main diagnosis orchestrator
    fix_generator.py  # Fix proposal generation (AI + offline)
    minimal_reproducer.py  # Minimal reproduction generation
    models.py         # Pydantic data models
    priority_ranker.py     # Impact-based cluster ranking
    retry.py          # Retry decorator for Anthropic API
    root_cause_analyzer.py # Root-cause identification
  execution/          # Phase C: test execution
  generator/          # Phase B4: test suite generation
  graph/              # Agent map generation
  improvement/        # Phase E: improvement & validation
    ab_testing.py     # A/B testing framework
    deployment_packager.py # Deployment package builder
    engine.py         # Main improvement orchestrator
    fix_applicator.py # Fix application engine
    models.py         # Pydantic data models
    regression_generator.py # Regression test generator
    validator.py      # Statistical improvement validator
  ingestion/          # Codebase scanning
  patterns/           # Framework & tool detection
  personas/           # Phase B1: persona management
  risk/               # Risk analysis
  scenarios/          # Phase B2: scenario management
```

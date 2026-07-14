# Research Workflow — Closing the Loop (RQ1–RQ4)

This is the end-to-end offline workflow that answers the dissertation's four
research questions. **There is no live connection between the production
TechRepair system and the simulator**: conversations are extracted once,
anonymised, and everything downstream — ground truth, seeds, generation,
measurement — runs on the anonymised corpus and compares it against
simulation results.

```
extract conversations (Supabase export JSON)
        │
        ▼
① anonymize_export.py            regex PII → Spanish NER → brand scrub
        │                        (drops phone/wa_id/customer name/ids,
        ▼                         media URLs, free-form metadata)
anonymised corpus  ──────────────────────────────┐
        │                                        │
        ▼                                        ▼
② ground truth (src/production)          ③ feedback seeds (train split only)
   structured signal scoring                 FailureSeed → re-seeded Phase B
   8 production categories                   generation (feedback arm)
   NO LLM judge anywhere                     + blind arm (no production data)
        │                                        │
        ▼                                        ▼
④ projection layer (src/evaluation/projection.py)
   both sources → frozen shared taxonomy (16 categories, v1.0-frozen-2026-07-14)
        │
        ▼
⑤ measurement engine (src/evaluation/measurement.py)
   RQ1 precision/recall per category · RQ2 coverage gaps
   RQ3 paired permutation test on held-out recall · RQ4 recall-vs-budget
```

## Commands

All commands run from `debugger-platforn/`.

### 1. Anonymise the extracted export

```bash
python3 anonymize_export.py \
    --input ../docs/tech_repair-conversations-export.json \
    --output ../docs/tech_repair-conversations-anonymized.json
```

Requires the anonymisation backend (`anonymization/backend`) importable for
the full 3-pass pipeline; falls back to regex-only redaction with a loud
warning otherwise. ~2 minutes for 24.5k messages (repeated templates are
cached).

### 2. Run the experiments

```bash
python3 run_experiments.py \
    --export ../docs/tech_repair-conversations-anonymized.json \
    --agent-map tech_repair_whatsapp_map.json \
    --budget 100
```

Outputs to `experiments_output/<timestamp>/`:

| Artefact | Contents |
|---|---|
| `results.json` | Full RQ1–RQ4 results, config, projection tables, ground-truth summary |
| `REPORT.md` | Human-readable report (tables + method notes) |
| `charts/*.png` | Per-category recall, recall-vs-budget, arm comparison, ground-truth distribution |
| `ground_truth.json` | Every ground-truth failure with score, categories, evidence |
| `suite_blind.json` / `suite_feedback.json` | The generated test suites per arm |

### 3. Modes

- `--mode static` (default): synthetic failures = categories each test is
  *designed to detect* (pre-execution approximation). Fully offline and
  deterministic. Measures suite **targeting**.
- `--mode execute --connector http://localhost:8099`: executes both suites
  against an agent endpoint (e.g. the sandbox bridge below), diagnoses
  failures with Phase D (offline mode), projects root causes onto the shared
  taxonomy. Measures observed **behaviour** of the agent under test.

### 4. Simulation endpoint + fidelity comparison (optional)

The sandbox bridge provides an offline stand-in agent endpoint and a replay
comparator between recorded production conversations and the simulation:

```bash
# Serve an offline simulated agent from the agent map
python3 sandbox_bridge.py serve --agent-map tech_repair_whatsapp_map.json \
    --mode echo --port 8099 --trace-dir sandbox_traces/

# Replay anonymised production conversations through it; fidelity report
python3 sandbox_bridge.py replay --agent-map tech_repair_whatsapp_map.json \
    --export ../docs/tech_repair-conversations-anonymized.json \
    --sample 50 --output fidelity_report.json
```

### 5. Web UI

The **Research** page in the web frontend drives the same workflow
(anonymise → ground-truth preview → run experiment → results and charts)
via `/api/research/*`.

## Methodological guarantees (enforced in code)

1. **No LLM judge in the criterion** — ground truth is built exclusively
   from human-process signals (escalations, human takeovers, explicit human
   requests, delivery failures, structured intent/confidence telemetry).
   `src/production/scoring.py` contains no model calls.
2. **Frozen shared taxonomy** — `src/evaluation/taxonomy.py` (16 categories,
   `TAXONOMY_VERSION`). Both projections
   (`src/evaluation/projection.py`) are total by construction: an unmapped
   root cause or production category raises at import time.
3. **Chronological holdout** — RQ3's feedback arm sees only failures that
   occurred before the held-out window (`time_split`).
4. **Leakage guard** — `verify_no_leakage` raises before any measurement if
   a held-out conversation influenced generation. It runs inside
   `run_experiment`, not as an optional check.
5. **Anonymisation before research use** — the batch anonymiser strips
   direct identifiers and passes all free text through the 3-pass pipeline;
   seeds additionally re-anonymise every snippet they embed
   (`src/production/anonymize.py` adapter, level recorded in results).

## Headline results on the current corpus (static mode, budget 100, seed 42)

Anonymised corpus of 1,299 conversations → 376 ground-truth failures
(259 train / 111 + signals held out):

- **RQ1**: blind synthetic testing recall of production failures **0.068**
  (95% CI 0.048–0.086), precision 0.571 — synthetic testing as-generated
  targets only a small slice of what actually fails in production.
- **RQ2**: systematic gaps = resolution_failure, comprehension_failure,
  data_gap, delivery_failure, infinite_loop, hallucination — dominated by
  long-horizon and backend-data failure modes.
- **RQ3**: production feedback lifts held-out recall **0.112 → 0.312**
  (Δ +0.200, p = 0.0001, sign-flip permutation) — grounding generation in
  real failures measurably improves prediction of *future* failures.
- **RQ4**: feedback > blind at every budget point (recall-per-budget curves
  in `charts/rq4_recall_vs_budget.png`).

Numbers regenerate deterministically with the same seed; they will shift as
the corpus grows or thresholds change. Treat `results.json` as the source of
truth for any citation.

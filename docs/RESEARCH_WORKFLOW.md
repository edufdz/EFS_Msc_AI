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

### 2b. Generation-method arms (RQ4)

All four generation strategies from the Background Report are implemented
(`src/experiments/arms.py`) and share the same suite assembler and budget:

```bash
python3 run_experiments.py \
    --export ../docs/tech_repair-conversations-anonymized.json \
    --agent-map tech_repair_whatsapp_map.json \
    --budget 100 --arms blind,feedback,naive_llm,gan
```

- `blind`/`template` — offline templates + structural coverage (no LLM)
- `naive_llm` — single-shot LLM persona/scenario generation (needs `ANTHROPIC_API_KEY`)
- `gan` — generator–critic loop: an LLM critic scores candidates on realism,
  specificity, and failure-provoking power; rejects are regenerated with the
  critic's objections in context
- `feedback` — production-failure-seeded generation (RQ3's treatment arm)

LLM arms are skipped with an explicit note when no API key is present.

### 2c. Sensitivity analysis (RQ3 robustness)

```bash
python3 run_sensitivity.py \
    --export ../docs/tech_repair-conversations-anonymized.json \
    --agent-map tech_repair_whatsapp_map.json
```

Re-runs the blind-vs-feedback comparison varying one analysis choice at a
time (ground-truth threshold `min_score` 2–5, holdout fraction 0.2–0.4, RNG
seeds 41–45) and writes `SENSITIVITY.md` + `sensitivity_deltas.png` with a
per-configuration Δ/p table and an overall robustness verdict.

### 2d. Ground-truth validation

Ground-truth labels can be checked against a read of the
transcripts. The harness makes this a ~1-hour task:

```bash
# Build the blind 50-conversation packet (40 flagged + 10 clean controls)
python3 run_validation.py sample \
    --export ../docs/tech_repair-conversations-anonymized.json \
    --output-dir validation_packet

# Annotate interactively in the terminal (resumable; q to save & quit)
python3 run_validation.py annotate --packet validation_packet

# Agreement statistics (Cohen's κ, per-category precision/recall)
python3 run_validation.py agree --packet validation_packet \
    --annotations validation_packet/annotations.json
```

The sample is blind (no scores or labels shown) and stratified across
production categories. `answer_key.json` holds the heuristic labels — do
not open it until annotation is finished.

An **LLM pilot** pass exists (`run_validation.py llm-annotate`) as a
preliminary consistency check only. On the current corpus it gives lenient
agreement 0.86 (κ=0.51) with heuristic precision 0.95 — but this number
must NEVER be reported as inter-annotator agreement: an LLM annotator
reintroduces exactly the circularity the ground-truth design excludes.
Agreement figures in this repository come from the LLM pilot only.

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
- **RQ4** (four arms, budget 100): **feedback > blind > naive_llm > gan** by
  held-out recall per budget — production grounding beats every ungrounded
  strategy, and naive LLM prompting does not beat structural templates in
  targeting terms (recall-per-budget curves in
  `charts/rq4_recall_vs_budget.png`).
- **Sensitivity**: the RQ3 delta is positive and significant in **10/10**
  analysis configurations (min_score 2–5, holdout 0.2–0.4, seeds 41–45;
  Δ +0.165…+0.288, all p = 0.0001). Note that seed variation does not move
  static-mode numbers: category-level targeting is invariant to pairing
  randomness, which is itself evidence the measure is stable.

Archived copies of the headline runs live in `docs/results/` (rq4_full +
sensitivity). Numbers regenerate deterministically with the same seed; they
will shift as the corpus grows or thresholds change. Treat `results.json`
as the source of truth for any citation.

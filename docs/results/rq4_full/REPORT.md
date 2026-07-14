# Predictive-Validity Experiment Report

Generated: 2026-07-14T15:57:36.382043+00:00  
Taxonomy: `1.0-frozen-2026-07-14`  
Mode: **static** (pre-execution approximation — measures suite targeting, not observed behaviour)
Anonymisation: `full`

## Ground truth

- Conversations analysed: **1299**
- Failures (score ≥ 3.0): **376** — train 263 / held-out 113 (holdout fraction 0.3)

| Production category | Conversations |
|---|---|
| loop_stall | 256 |
| resolution | 221 |
| comprehension | 153 |
| data_gap | 48 |
| delivery_infra | 14 |
| hallucination | 13 |
| missed_escalation | 11 |
| silent_abandonment | 9 |

## RQ1 — Predictive validity

Synthetic testing (blind arm, 100 tests) vs **all** 725 production signals:

- **Recall: 0.068** (95% CI 0.048–0.086)
- **Precision: 0.571**
- F1: 0.121

| Category | Severity | Production signals | Recall | Precision |
|---|---|---|---|---|
| infinite_loop | medium | 256 | 0.148 | 1.000 |
| resolution_failure | high | 221 | 0.000 | 0.000 |
| comprehension_failure | high | 153 | 0.000 | 0.000 |
| data_gap | medium | 48 | 0.000 | 0.000 |
| delivery_failure | medium | 14 | 0.000 | 0.000 |
| hallucination | high | 13 | 0.231 | 1.000 |
| escalation_failure | high | 11 | 0.364 | 1.000 |
| premature_exit | medium | 9 | 0.444 | 1.000 |

## RQ2 — Coverage gaps

Categories with recall < 0.25:

### infinite_loop (severity medium, 256 signals, recall 0.148)

- 256 conversations, avg 83.4 messages (long-horizon share 94%)
- escalated: 71%, avg failure score 9.84

### resolution_failure (severity high, 221 signals, recall 0.000)

- 221 conversations, avg 74.1 messages (long-horizon share 65%)
- escalated: 100%, avg failure score 11.52

### comprehension_failure (severity high, 153 signals, recall 0.000)

- 153 conversations, avg 87.2 messages (long-horizon share 85%)
- escalated: 59%, avg failure score 10.2

### data_gap (severity medium, 48 signals, recall 0.000)

- 48 conversations, avg 33.0 messages (long-horizon share 33%)
- escalated: 100%, avg failure score 4.29

### delivery_failure (severity medium, 14 signals, recall 0.000)

- 14 conversations, avg 48.4 messages (long-horizon share 57%)
- escalated: 64%, avg failure score 7.93

### hallucination (severity high, 13 signals, recall 0.231)

- 13 conversations, avg 89.0 messages (long-horizon share 92%)
- escalated: 92%, avg failure score 9.82

## RQ3 — Production feedback

Held-out window: 2026-05-28 18:17:33.682554+00:00 → 2026-06-27 18:50:50.573040+00:00 (215 signals). Both arms at the same budget (100 tests); feedback arm seeded ONLY with train-split failures (leakage guard passed).

| Arm | Held-out recall | 95% CI | Precision |
|---|---|---|---|
| blind | 0.112 | 0.070–0.153 | 0.429 |
| feedback | 0.312 | 0.251–0.372 | 0.545 |

**feedback_vs_blind**: Δrecall = +0.200, p = 0.0001 (significant; sign-flip permutation, 43 discordant signals)

## RQ4 — Recall per testing budget

Arm ranking at budget 100: feedback > blind > naive_llm > gan

| Budget | blind | naive_llm | gan | feedback |
|---|---|---|---|---|
| 5 | 0.112 | 0.098 | 0.098 | 0.177 |
| 10 | 0.112 | 0.112 | 0.098 | 0.177 |
| 20 | 0.112 | 0.112 | 0.098 | 0.177 |
| 30 | 0.112 | 0.112 | 0.098 | 0.177 |
| 50 | 0.112 | 0.112 | 0.098 | 0.191 |
| 75 | 0.112 | 0.112 | 0.098 | 0.191 |
| 100 | 0.112 | 0.112 | 0.098 | 0.312 |

## Method notes

- Ground truth is built exclusively from human-process signals (escalations, human takeovers, delivery failures, structured intent/confidence telemetry) — no LLM judge anywhere in the criterion.
- Both failure sources are projected onto the frozen shared taxonomy (see `projection` in results.json for the full mapping tables).
- The RQ3 split is chronological: the feedback arm only ever sees failures that occurred before the held-out window.
- **Static mode caveat**: synthetic failures are the categories each test is *designed to detect* (pre-execution approximation). Run with `--mode execute` against the sandboxed agent for behavioural results.
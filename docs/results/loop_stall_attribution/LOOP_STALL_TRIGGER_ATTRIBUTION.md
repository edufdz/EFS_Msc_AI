# `loop_stall` trigger-level attribution — real vs simulated corpora

**Written 2026-09-08.** Answers the pending check in the results chapter: *are the
simulated `loop_stall` flags an artefact of conversation length interacting with the
turn budget, or do they come from genuine verbatim cycling?*

**Answer: genuine cycling, without exception.** Every one of the 66 `loop_stall`
flags in the 390-conversation fixed-scale set and all 523 in the 2,560-conversation
scale study fired on the verbatim-agent-repetition disjunct alone. The length
disjunct fired **zero times in 2,950 simulated conversations**, and it *cannot*
fire: the length threshold is `> 40` messages and the simulator's hard ceiling is
exactly 40. The match is therefore mechanistically stronger than the weaker reading
you were guarding against — but see §7 for the mirror-image caveat, which is that
the *real* flags are overwhelmingly length-driven, so the two corpora reach the same
category through largely different signals.

Nothing under `docs/results/simulated_runs/`, `docs/results/real_vs_sim/`,
`debugger-platforn/results*/` or `pipeline_output/` was modified. All artefacts of
this analysis are new files in this directory.

---

## 1. The scorer and every signal that can trigger `loop_stall`

The labels come from the production rule-based scorer
**`debugger-platforn/src/production/scoring.py`**, function `score_conversation()`,
category block *"4. Loop / stall"*. It is LLM-free and is applied to both corpora
unchanged — `compare_real_vs_sim.py` imports it (`compare_real_vs_sim.py:52`) and
scores real and simulated conversations through the same call
(`compare_real_vs_sim.py:136`).

The category has exactly **two** triggering signals, joined by `or`:

```python
# debugger-platforn/src/production/scoring.py:229-240
ai_texts = [_norm(m.get("text_body") or "") for m in ai_msgs if (m.get("text_body") or "").strip()]
repeated_ai = 0
seen: Dict[str, int] = {}
for t in ai_texts:
    seen[t] = seen.get(t, 0) + 1
repeated_ai = max(seen.values()) if seen else 0
if score.message_count > 40 or repeated_ai >= 3:      # <- scoring.py:235
    categories.append("loop_stall")
```

| # | Signal | Exact predicate | Threshold | Counted in | Site |
|---|---|---|---|---|---|
| A | Conversation length | `score.message_count > 40` | **strictly greater than 40** | **messages** | `scoring.py:235` (left disjunct) |
| B | Verbatim agent repetition | `repeated_ai >= 3` where `repeated_ai = max(Counter(normalised non-empty agent texts).values())` | **≥ 3 occurrences** | **agent messages** | `scoring.py:229-235` (right disjunct) |

There is **no third signal**. The re-scoring script asserts, for every one of the
4,249 conversations scored here, that its independent re-derivation of `A or B`
agrees with the scorer's own `loop_stall` membership; the assertion never fired
(`loop_stall_attribution.py:105-109`). The "any other signal" bucket in §4 is
therefore **0 by construction**, not merely 0 empirically.

### Threshold units — the detail that matters

- **Signal A is in messages, not turns.** `message_count` is set at
  `scoring.py:121`: `int(conv.get("message_count") or len(messages))`. For the real
  export it is the export's own `message_count` field (all message rows, any
  `source`: `customer`, `ai_agent`, `human_agent`, `system`). For simulated
  conversations the adapter sets it explicitly to `len(messages)` after dropping
  non-dialogue entries (`compare_real_vs_sim.py:112`, and `:101` drops `system`-role
  chaos annotations, which have no production analogue).
- **Signal B is in agent messages**, and it is a **whole-conversation multiplicity,
  not a consecutive run.** Three identical agent replies at messages 2, 14 and 30
  trigger it exactly as three back-to-back ones do. Texts are compared after
  `_norm()` — lowercase plus accent-stripping (`scoring.py:25-28`) — so it is
  "verbatim modulo case and Spanish diacritics".
- Signal A does double duty: the *same* `> 40` threshold also adds `+2` to the
  continuous failure score at `scoring.py:189-190`. So in simulation the length
  signal contributes neither the category nor the score bonus (§3).
- A conversation is counted as a **failure** when `failure_score >= 3.0`
  (`src/production/ground_truth.py:26`, applied at `compare_real_vs_sim.py:137`).
  Category membership and failure status are distinct — §4 reports both gates.

---

## 2. What a "turn" is in Phase C, and how many messages the budget allows

**File: `debugger-platforn/src/execution/conversation_simulator.py`.**

```python
self.max_turns: int = self.exec_config.get("max_turns", 40)   # :75
...
while turn_count < self.max_turns:                            # :161
    turn_count += 1
```

One loop iteration = **one turn = exactly two messages**: a `user`
`ConversationTurn` (`:205-212`) and an `agent` `ConversationTurn` (`:225-233`), both
stamped with the same `turn_number`. The first persona message is generated *before*
the loop (`:139`) and consumed by iteration 1; no message is appended after the loop
exits. Early exits (agent error `:193-202`, terminal outcome `:286-292`, failure
condition `:295-298`, persona gives up `:301-304`, GAN restart `:276-283`) can only
shorten a conversation.

Two exceptions to the strict 2-messages-per-turn rule, both of which *reduce* the
message count:

- A chaos **timeout** appends a single `system` turn and `continue`s (`:171-182`) —
  it consumes an iteration but contributes 1 entry, and the adapter then discards it.
- An agent error appends only the `user` turn and breaks (`:193-202`).

### Three findings that change the premise of the question

**(a) The budget in these runs was 20 turns, not 40.** The `40` at `:75` is only the
fallback when a test case omits the setting. Every test case in every suite behind
every run in this study sets `execution_config.max_turns = 20`:

| Suite | Path | Tests | `max_turns` |
|---|---|---|---|
| v4 40-test | `debugger-platforn/generated_tech_repair/test_suite.json` | 40 | 20 (40/40) |
| web 150-test | `debugger-platforn/pipeline_output/session-636fc721/generated/test_suite.json` | 150 | 20 (150/150) |
| 200-test (tiled) | `debugger-platforn/pipeline_output/session-636fc721/generated/test_suite_200.json` | 200 | 20 (200/200) |
| scale ×7 | `debugger-platforn/results_scale_study/suites/suite_{0010…1000}.json` | 10…1000 | 20 (all) |

Suite→export linkage is confirmed by matching `test_suite_id`: v4 `c1ac0338…`,
web-150 and all seven scale batches `e06df8ce…`. The 200-run export carries the
synthetic id `pooled-commit-420f116` (it is the reconstruction from that commit's
traces), so its suite is identified instead by its 150 shared `test_id`s with
`test_suite_200.json` — which also sets `max_turns = 20` for all 200 cases.

So **a conversation that exhausts the budget contains 20 turns = 40 messages**
(fewer if any turn was a chaos timeout or an agent error).

**(b) `total_turns` in `conversations.json` is a message count, not a turn count.**
`runner.py:202` sets `result.total_turns = len(conv_result["turns"])` — the length of
the flat entry list. Confirmed empirically: `total_turns == len(turns)` in all
2,950 simulated conversations. Anything in the chapter that reads `total_turns` as
"turns" is off by a factor of two; the pairing is visible in the `turn_number` field,
which runs 1…20.

**(c) Therefore the length signal is structurally unreachable in simulation.**
Ceiling 40 messages vs. a predicate requiring `> 40` — it misses by exactly one
message. Observed maxima:

| Corpus | max turns (iterations) | max messages | hit the 20-turn budget | `message_count > 40` |
|---|---|---|---|---|
| Fixed-scale 390 | 19 | 38 | 0 | **0** |
| Scale study 2,560 | 20 | 40 | 9 (4 with `failure_reason = "Max turns exceeded (20)"`) | **0** |

Nine scale-study conversations sat exactly on the boundary at 40 messages and still
did not fire. Note that under the *code default* of 40 turns the ceiling would be 80
messages and Signal A would be reachable — but no run in this study used it.

---

## 3. Re-scoring with per-signal attribution — headline

Reproduction reconciles exactly with the published figures
(`docs/results/real_vs_sim/real_vs_sim.json`): real 376/1,299 failures with 256
`loop_stall` (68.1%); pooled sim 82/390 failures with 66 `loop_stall` (80.5%).

Buckets are mutually exclusive and gated on failure status (`failure_score >= 3.0`
**and** `loop_stall` present) — the basis of every published number.

| Corpus | convs | failures | `loop_stall` | length only | repetition only | both | other signal |
|---|---|---|---|---|---|---|---|
| **Real production** | 1,299 | 376 | 256 | **87 (34.0%)** | **16 (6.3%)** | **153 (59.8%)** | 0 (0.0%) |
| **Simulated — fixed 390** | 390 | 82 | 66 | **0 (0.0%)** | **66 (100.0%)** | **0 (0.0%)** | 0 (0.0%) |
| **Simulated — scale 2,560** | 2,560 | 623 | 523 | **0 (0.0%)** | **523 (100.0%)** | **0 (0.0%)** | 0 (0.0%) |

Restated per signal (a flag can involve both):

| Corpus | involves length | involves repetition |
|---|---|---|
| Real | 240/256 = **93.8%** (Wilson 95% 90.1–96.1) | 169/256 = **66.0%** (60.0–71.5) |
| Sim fixed 390 | 0/66 = **0%** | 66/66 = **100%** (Wilson lower bound 94.5) |
| Sim scale 2,560 | 0/523 = **0%** | 523/523 = **100%** (lower bound 99.3) |

The simulated proportions are a census of these corpora, not a sample, so the CIs
only bear on generalising to future runs; the §2(c) ceiling argument is the stronger
guarantee.

### Per-file breakdown

| Run | File | convs | failures | `loop_stall` | length only | repetition only | both |
|---|---|---|---|---|---|---|---|
| v4 40-test | `debugger-platforn/results_tech_repair_live_v4/conversations.json` | 40 | 9 | 8 | 0 | 8 (100%) | 0 |
| web 150-test | `docs/results/simulated_runs/run_web_150tests.json` | 150 | 39 | 29 | 0 | 29 (100%) | 0 |
| 200-test recovered | `docs/results/simulated_runs/run_200tests_recovered.json` | 200 | 34 | 29 | 0 | 29 (100%) | 0 |
| **fixed-scale pool** | — | **390** | **82** | **66** | **0** | **66 (100%)** | **0** |
| scale N=10 | `debugger-platforn/results_scale_study/N0010/conversations.json` | 10 | 3 | 1 | 0 | 1 (100%) | 0 |
| scale N=50 | `…/N0050/conversations.json` | 50 | 12 | 11 | 0 | 11 (100%) | 0 |
| scale N=100 | `…/N0100/conversations.json` | 100 | 24 | 22 | 0 | 22 (100%) | 0 |
| scale N=200 | `…/N0200/conversations.json` | 200 | 43 | 36 | 0 | 36 (100%) | 0 |
| scale N=400 | `…/N0400/conversations.json` | 400 | 90 | 74 | 0 | 74 (100%) | 0 |
| scale N=800 | `…/N0800/conversations.json` | 800 | 219 | 188 | 0 | 188 (100%) | 0 |
| scale N=1000 | `…/N1000/conversations.json` | 1000 | 232 | 191 | 0 | 191 (100%) | 0 |
| **scale pool** | — | **2,560** | **623** | **523** | **0** | **523 (100%)** | **0** |

Real corpus: `docs/tech_repair-conversations-anonymized.json` (1,299 conversations,
loaded via `src/production/loader.py::load_export`).

The scale batches and the v4 run are read straight from the platform originals,
`debugger-platforn/results_scale_study/N*/conversations.json` and
`debugger-platforn/results_tech_repair_live_v4/conversations.json`. The two
web-derived runs have no surviving platform original and are read from the rescued
copies in `docs/results/simulated_runs/`, which are authoritative for them — see §8.

### Ungated variant (category fired, failure threshold ignored)

Because Signal A never fires in simulation, its `+2` score bonus never applies
either, so a simulated conversation must reach `min_score = 3` on other signals
(escalation +3, human request +5, frustration +3, expiry +2, customer repeats +1
each). This leaves genuine verbatim loops below the failure threshold and thus
invisible in the published counts:

| Corpus | `loop_stall` category fired | of which counted as failures | **sub-threshold loops not in the published numbers** |
|---|---|---|---|
| Real | 357 (98 length-only, 70 repetition-only, 189 both) | 256 | 101 |
| Sim fixed 390 | 89 (all repetition-only) | 66 | **23** |
| Sim scale 2,560 | 681 (all repetition-only) | 523 | **158** |

The starkest instance is in §6.

---

## 4. Repetition-run distributions (repetition-triggered flags)

Two statistics per conversation: the scorer's own signal (`repeated_ai`, the
multiplicity of the most frequent agent message anywhere in the conversation) and
the **longest run of consecutive identical agent messages**, which the scorer does
not keep and which is the stricter reading of "cycling".

### Simulated — fixed-scale 390 (n = 66)

| `repeated_ai` | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| convs | 17 | 11 | 12 | 3 | 8 | 3 | 1 | 1 | 5 | 1 | 4 |

median 5, mean 5.92, IQR 3.25–7, max 13.

| longest consecutive run | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 9 | 10 | 11 | 12 | 13 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| convs | 1 | 9 | 15 | 12 | 12 | 1 | 7 | 1 | 4 | 2 | 1 | 1 |

median 4, mean 4.89, IQR 3–5.75, max 13. **56/66 (84.8%) have a consecutive run of
≥ 3** — i.e. they would still qualify under the stricter definition.

### Simulated — scale study 2,560 (n = 523)

| `repeated_ai` | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15 | 16 | 17 | 18 | 20 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| convs | 116 | 107 | 87 | 52 | 42 | 29 | 29 | 12 | 16 | 9 | 10 | 5 | 2 | 3 | 1 | 2 | 1 |

median 5, mean 5.86, IQR 4–7, max 20.

| longest consecutive run | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 16 | 20 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| convs | 67 | 125 | 99 | 74 | 49 | 46 | 19 | 13 | 13 | 9 | 1 | 1 | 2 | 4 | 1 |

median 4, mean 4.83, IQR 3–6, max 20. **456/523 (87.2%) have a consecutive run of
≥ 3.**

### Real production, for contrast (n = 169 repetition-involving)

`repeated_ai`: median 4, mean 4.66, max 16. Longest consecutive run: **median 2**,
mean 2.41, max 14, and 33 conversations have a longest run of 1 — the repetition is
scattered across the conversation (canned status boilerplate re-sent hours apart),
not a tight loop. Simulated repetition is roughly twice as *contiguous* as real
repetition (median consecutive run 4 vs 2).

---

## 5. Conversation length: flagged vs unflagged

Message counts (`message_count` as the scorer sees it).

| Corpus | group | n | min | Q1 | median | Q3 | max | mean |
|---|---|---|---|---|---|---|---|---|
| Fixed 390 | flagged `loop_stall` | 66 | 8 | 12 | **16** | 22 | 38 | 17.82 |
| Fixed 390 | not flagged | 324 | 2 | 2 | **2** | 6 | 32 | 4.69 |
| Scale 2,560 | flagged | 523 | 8 | 12 | **16** | 22 | 40 | 18.03 |
| Scale 2,560 | not flagged | 2,037 | 2 | 2 | **4** | 6 | 40 | 5.03 |
| Real | flagged | 256 | 16 | 50 | **69** | 101 | **809** | 83.36 |
| Real | not flagged | 1,043 | 0 | 2.5 | **10** | 21.5 | 94 | 14.26 |

- Simulated: `message_count > 40` = **0** in both corpora; `== 40` = 0 (fixed) and
  9 (scale). Flagged conversations are 3–4× longer than unflagged ones, but the
  entire flagged distribution sits inside the budget, and the shortest flagged
  conversation is 8 messages (4 turns) — length plays no part in the label.
- Real: 287 conversations exceed 40 messages and the flagged median is 69, with a
  809-message tail. This is the asymmetry to state in the chapter (§7).
- Simulated histograms are supported almost entirely on even values, as §2 predicts;
  odd values mark chaos-timeout or agent-error conversations.

Full histograms: `loop_stall_attribution.json` → `length_distributions`.

---

## 6. The 18-turn phone-number deflection case

**Confirmed present.** It is test **#26** of the recovered 200-test run,
`test_id = ae1fdcae-473e-434a-ae9d-73791588d9a3`, in
`docs/results/simulated_runs/run_200tests_recovered.json`. It is the only
conversation in that run that reached 18 loop iterations.

| Field | Value |
|---|---|
| Scenario | *Corrección de información de cliente incorrecta* |
| Turns (loop iterations) | **18** |
| Messages (`message_count`) | **36** (`total_turns` in the export also reads 36 — see §2(b)) |
| Signal A — length | **did not fire** (36 ≤ 40) |
| Signal B — repetition | **fired**: `repeated_ai = 13`, longest consecutive run **9** |
| Repeated text | `para consultar el estado de su orden por telefono, marque a la linea de atencion: *+525588…` |
| Failure score | 5.0 → counted as a failure |
| Categories | `loop_stall`, `missed_escalation`, `silent_abandonment` |
| Outcome | `user_abandoned` — `failure_reason: "Persona gave up after 18 turns"` |

**Signals fired: verbatim agent repetition only.** The case is exactly the
mechanistic match the chapter claims, and it owes nothing to the turn budget: the
persona quit at turn 18 of 20, two turns short of exhaustion.

The three repetition-loop failures on record for the 200-test run all check out
as repetition-only, with one correction to the record:

| Test | `test_id` | turns | msgs | `repeated_ai` | consec. run | score | counted? | signals |
|---|---|---|---|---|---|---|---|---|
| #26 | `ae1fdcae…` | 18 | 36 | 13 | 9 | 5.0 | yes | repetition only |
| #8 | `6025928f…` | 17 | 34 | 11 | 7 | 5.0 | yes | repetition only |
| #8 | `073cc8c9…` | 16 | 32 | **14** | **14** | **2.0** | **no** | repetition only |
| #147 | `ffa0234b…` | 14 | 28 | 11 | 10 | 5.0 | yes | repetition only |

`test_number` 8 occurs **twice** in this run (the 200 suite is the 150 suite tiled;
50 test numbers repeat, see §8). The second #8, `073cc8c9…`, is the **most severe
verbatim loop in the entire 390-conversation pool** — 14 consecutive identical phone
deflections before the persona gave up — and it **is not in the 82 failures**: it
scores 2.0, one point short of `min_score = 3`, because it escalated nothing,
triggered no frustration keyword, and gets no length bonus (which in production
would have supplied exactly the missing `+2`). It is one of the 23 sub-threshold
loops in §3. Worth a sentence in the chapter: the failure threshold, tuned on a
corpus where long conversations earn a bonus, systematically under-counts loops in a
budget-capped simulator.

In total, 20 conversations in the 200-test run repeat the phone-deflection template
≥ 3 times; 16 of the 20 are counted as failures (the other four score 2.0, 0.0, 0.0
and 0.0).

---

## 7. Reading for the results chapter

1. **The pending check resolves in your favour.** No simulated `loop_stall` flag
   anywhere in 2,950 conversations came from length. 100% came from verbatim agent
   repetition, and 85–87% would survive the stricter "≥ 3 *consecutive* identical
   replies" definition. The 68.1%-vs-80.5% `loop_stall` correspondence is not a
   budget artefact.
2. **State the asymmetry, though.** Real `loop_stall` is 93.8% length-involving and
   only 6.3% repetition-*only*; simulated is 100% repetition-only. The two corpora
   land in the same category through largely different signals — a length-dominated
   real signal cannot be reproduced by a 20-turn simulator by construction. The
   honest claim is "simulation reproduces the *repetition* mode of `loop_stall`
   (matching 66.0% of real flags on that signal) and cannot reach the length mode at
   all", which is more defensible than an unqualified distributional match and
   strictly stronger than the weak reading you feared.
3. **Fix the "forty-turn budget" wording.** The budget in every recorded run was
   **20 turns / 40 messages**; 40 is only the un-overridden code default. And
   `total_turns` in the exports is a message count, so any turn figure taken from it
   should be halved.
4. **Signal A is unreachable, not merely unobserved.** 40-message ceiling vs a `> 40`
   predicate. If a future run raises `max_turns` above 20, the two disjuncts
   entangle immediately (21 turns = 42 messages fires Signal A on length alone), and
   this analysis must be re-run before any comparison is quoted.
5. **Co-occurrence differs too.** Real flagged conversations pair `loop_stall` with
   `resolution` (149) and `comprehension` (134), and only 18/256 are `loop_stall`
   alone. Simulated: 41/66 and 352/523 are `loop_stall` alone, pairing mostly with
   `missed_escalation`/`resolution` and never with `comprehension` (consistent with
   the known zero-comprehension result — the personas never repeat themselves).

---

## 8. Chaos injection and the AI validation pass

### Chaos injection — configured and partly active, but inert for `loop_stall`

Chaos is a **per-test-case** setting (`execution_config.chaos_injection`), not a
global run flag, and it is **switched on for a minority of tests in every single
suite** behind these runs. Counts of test cases with each flag `true`:

| Run / suite | tests | `timeout` | `malformed_response` | `data_conflict` | any |
|---|---|---|---|---|---|
| v4 40-test | 40 | 5 | 3 | 3 | **11** |
| web 150-test | 150 | 17 | 5 | 13 | **35** |
| 200-test (tiled) | 200 | 28 | 6 | 19 | **53** |
| scale N=10 | 10 | 1 | 0 | 1 | **2** |
| scale N=50 | 50 | 7 | 2 | 3 | **12** |
| scale N=100 | 100 | 10 | 4 | 8 | **22** |
| scale N=200 | 200 | 23 | 8 | 18 | **49** |
| scale N=400 | 400 | 40 | 16 | 37 | **93** |
| scale N=800 | 800 | 93 | 24 | 68 | **185** |
| scale N=1000 | 1000 | 107 | 39 | 78 | **224** |

Firing is probabilistic per turn — 0.15 for `timeout`, 0.10 for the other two
(`conversation_simulator.py:1390-1412`). Two qualifications:

- **Only `timeout` has any effect.** It appends a `system` turn and skips the agent
  call (`:171-182`). `malformed_response` and `data_conflict` construct a
  `ChaosEvent`, which is recorded, and then fall through to a normal agent call —
  they change nothing about the conversation. Any chapter text implying three active
  chaos modes should be narrowed to one.
- **Observed `timeout` firings** (counted as `system`-role turns in the exports):
  v4 5 turns / 2 convs; web-150 10 / 5; 200-run 9 / 6; scale batches 0, 5, 5, 9, 15,
  35, 56 turns over 0, 3, 4, 7, 11, 23, 31 conversations. Totals: **24 firings
  across 13/390** fixed-scale conversations and **125 firings across 79/2,560**
  scale-study conversations.
- **Impact on this analysis: none.** `system` turns are dropped by the adapter
  (`compare_real_vs_sim.py:101`), so they enter neither `message_count` nor the
  agent-text multiset. A timeout can only *shorten* a conversation, which cannot
  create a length flag. No conversation in §6 involved a chaos event.

### AI validation pass — never ran against any of these ten runs

The LLM-based conversation validator is a **`run_pipeline.py`-only** step
(`aggregator.validate_and_save()`, `run_pipeline.py:435-469`, skippable with
`--skip-validation`). `execute_tests.py` — which produced the v4 40-test run, the
200-test run and all seven scale batches — has no validation stage at all, and none
of those result directories contains a `validation_report.json` or
`validated_failure_inbox.json`. Only two such reports exist anywhere in the platform:

| File | Summary | Belongs to |
|---|---|---|
| `debugger-platforn/pipeline_output/results/validation_report.json` | 9 failures reviewed, 8 genuine, 1 chaos-filtered | an older 10-test pipeline run — not in this study |
| `debugger-platforn/pipeline_output/session-636fc721/results/validation_report.json` | **0 failures reviewed, 10 passes**, nothing filtered | a 10-test re-run of 2026-07-29 that overwrote the session, **not the 150-test corpus** |

The second one is a trap: it sits in the directory the web 150-test run wrote to, but
that directory's `conversations.json` now holds 10 conversations exported
2026-07-29T15:59, whereas the authentic 150-conversation export
(2026-07-24T15:29) survives only as
`docs/results/simulated_runs/run_web_150tests.json`. **Cite
`docs/results/simulated_runs/run_web_150tests.json`, never the `pipeline_output/`
one.** (The v4 run and the scale batches are unaffected: their platform originals
under `debugger-platforn/results_tech_repair_live_v4/` and
`debugger-platforn/results_scale_study/` were never overwritten.)

Separately, the **LLM validation pilot** in `docs/results/validation_pilot/`
(κ 0.51 lenient, 50 items) annotates the **real** corpus — its items carry
`conversation_id`s and `[PERSON_n]` anonymisation placeholders
(`debugger-platforn/validation_packet/items.json`). It validates the rule-based
ground truth against an LLM annotator on production data; it has never been run
against any simulated corpus.

### Two provenance caveats on the corpus sizes

**The pooled 390 covers 240 distinct test cases, not 390.** The 200-test suite is the
150-test suite **tiled**: the two runs share all 150 `test_id`s, and the 200-run
repeats 50 `test_number`s (hence the two test #8s in §6). So 150 cases were executed
twice, yielding genuinely different transcripts — different timings, different agent
replies, materially different lengths (e.g. `931eac4d…` ran 4 messages in the web run
and 14 in the 200-run). The 390 conversations are distinct observations and the counts
above stand, but they are not 390 independent test cases and `id` is not unique across
the pool.

**The scale pool of 2,560 covers 1,950 distinct test cases.** The batches nest —
`gen_scale_suites.py` tiles from the same base suite, so N=10 ⊂ N=1000 and every
batch contains the same base 150 cases (`N0400 ∩ N0800 = 150`). Those 150 were
executed once per batch, i.e. 7×. Each batch is internally id-unique.

**The two corpora are not independent of each other:** the same base 150 test cases
appear in both (`fixed ∩ scale = 150` test_ids). Reporting them separately, as here,
is right; do not treat the 390 and the 2,560 as 2,950 independent observations of
distinct test cases.

---

## 9. Reproduction

Script: **`docs/results/loop_stall_attribution/loop_stall_attribution.py`** (new
file; read-only — it imports `score_conversation` and `adapt_sim_conversation`
verbatim and monkey-patches nothing).

```bash
cd /Users/eduardo7/Desktop/dos-agent-debugger/MSC_AI_Project
python3 docs/results/loop_stall_attribution/loop_stall_attribution.py \
    --out docs/results/loop_stall_attribution
```

System `python3` (pyenv 3.13.5). Runs in a few seconds; deterministic, no network,
no LLM.

Outputs in this directory:

| File | Contents |
|---|---|
| `LOOP_STALL_TRIGGER_ATTRIBUTION.md` | this report |
| `loop_stall_attribution.py` | the re-scoring script |
| `loop_stall_attribution.json` | all counts, per-file attribution, both gates, full histograms, budget check, case hunt |
| `loop_stall_flagged_conversations.json` | per-conversation audit trail for all 845 flagged conversations (256 real + 66 fixed + 523 scale), each with both signals, both repeat statistics, message count, loop iterations, outcome and failure reason |

Inputs (all read-only, none modified):

- `docs/tech_repair-conversations-anonymized.json`
- `debugger-platforn/results_tech_repair_live_v4/conversations.json` (the v4 40-test run)
- `docs/results/simulated_runs/run_web_150tests.json`
- `docs/results/simulated_runs/run_200tests_recovered.json`
- `debugger-platforn/results_scale_study/N{0010,0050,0100,0200,0400,0800,1000}/conversations.json`

Key source citations: `debugger-platforn/src/production/scoring.py:121,189-190,229-240`
· `src/production/ground_truth.py:26` · `compare_real_vs_sim.py:52,78-121,136-137`
· `src/execution/conversation_simulator.py:75,139,161,171-182,193-233,286-304,1390-1412`
· `src/execution/runner.py:202` · `src/execution/aggregator.py:197,221-225`.

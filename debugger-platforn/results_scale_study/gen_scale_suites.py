#!/usr/bin/env python3
"""
Regenerate the scale-study suites (results_scale_study/suites/) exactly as
used on 2026-07-24. Deterministic: seed = 42 + N per batch.

For N <= 150: seeded sample without replacement from the session suite.
For N  > 150: full suite + (N-150) resampled duplicates with fresh UUIDs
(UUIDs drawn from the same seeded RNG, so reruns byte-match).

Base suite: pipeline_output/session-636fc721/generated/test_suite.json
Run from debugger-platforn/:  python3 results_scale_study/gen_scale_suites.py
"""
import json
import os
import random
import uuid

BASE = "pipeline_output/session-636fc721/generated/test_suite.json"
NS = [10, 50, 100, 200, 400, 800, 1000]

base = json.load(open(BASE))
cases = base["test_cases"]
os.makedirs("results_scale_study/suites", exist_ok=True)
for n in NS:
    rng = random.Random(42 + n)
    if n <= len(cases):
        picked = rng.sample(cases, n)
    else:
        picked = list(cases)
        for tc in [rng.choice(cases) for _ in range(n - len(cases))]:
            dup = json.loads(json.dumps(tc))
            dup["test_id"] = str(uuid.UUID(int=rng.getrandbits(128)))
            picked.append(dup)
    suite = dict(base)
    suite["test_cases"] = picked
    path = f"results_scale_study/suites/suite_{n:04d}.json"
    json.dump(suite, open(path, "w"), ensure_ascii=False)
    print(path, len(picked), "cases")

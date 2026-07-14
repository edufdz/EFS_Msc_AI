# Sensitivity Analysis — RQ3 robustness

Generated: 2026-07-14T16:01:31.725190+00:00  
Configurations tested: 10  
Δ(feedback−blind) positive in **10/10**, significant (p<0.05) in **10/10**  
Δ range: +0.165 … +0.288; max p-value: 0.0001

**Verdict: ROBUST**

| Varied | Value | GT failures | Held-out signals | Blind recall | Feedback recall | Δ | p | sig |
|---|---|---|---|---|---|---|---|---|
| baseline | default | 376 | 215 | 0.112 | 0.312 | +0.200 | 0.0001 | ✓ |
| min_score | 2.0 | 487 | 266 | 0.113 | 0.297 | +0.184 | 0.0001 | ✓ |
| min_score | 4.0 | 296 | 167 | 0.108 | 0.335 | +0.228 | 0.0001 | ✓ |
| min_score | 5.0 | 275 | 158 | 0.095 | 0.310 | +0.215 | 0.0001 | ✓ |
| holdout_fraction | 0.2 | 376 | 132 | 0.159 | 0.447 | +0.288 | 0.0001 | ✓ |
| holdout_fraction | 0.4 | 376 | 291 | 0.093 | 0.258 | +0.165 | 0.0001 | ✓ |
| rng_seed | 41 | 376 | 215 | 0.112 | 0.312 | +0.200 | 0.0001 | ✓ |
| rng_seed | 43 | 376 | 215 | 0.112 | 0.312 | +0.200 | 0.0001 | ✓ |
| rng_seed | 44 | 376 | 215 | 0.112 | 0.312 | +0.200 | 0.0001 | ✓ |
| rng_seed | 45 | 376 | 215 | 0.112 | 0.312 | +0.200 | 0.0001 | ✓ |
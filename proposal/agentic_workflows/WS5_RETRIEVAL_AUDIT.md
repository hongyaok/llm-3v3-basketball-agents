# WS5 Phase B retrieval audit

## Step 1: Freeze and reproduce the baseline

The original MiniLM index had 119 clause chunks from the 74-page FIBA 3x3
PDF (`source_sha256` starts `215357ff`, original `chunks_sha256` starts
`96f5f39a`). With the unchanged 40-case
fixture and 26 independently labelled cases, the retrieval validation script
measured **14/26 hit@3 (53.8%)** and
**25/26 category eligibility (96.2%)**: 11 ranking misses and one category-filter
miss. This is the historical baseline, not the revised score.

## Step 2: Audit labels and article/category assignments before tuning

Every gold ID exists in the source-derived index, and the labels were kept
unchanged. The 12 baseline misses were checked against the labelled state and
the corresponding PDF clause:

| Baseline miss | Gold clause | Audit finding | Outcome |
| --- | --- | --- | --- |
| `drive_goaltending_marker` | R31.2.1 | Correct field-goal goaltending clause, but the fixture has a held ball and no ball-touch/trajectory evidence. | Still a ranking miss; fix fixture evidence before treating this as a realistic retrieval test. |
| `drive_shooting_a1` | R15.1.2 or R34.2.2 | Act-of-shooting definition and shooting-foul penalty are relevant; general contact chunks displaced them. | Hit after focused routing and correcting R34.2.1. |
| `drive_shooting_b1` | R15.1.2 or R34.2.2 | Same issue with teams reversed. | Hit. |
| `drive_ball_in_shot` | R15.1.2 or R34.2.2 | Ball is in shot, so the labelled clauses are relevant; general contact chunks displaced them. | Hit. |
| `drive_offensive_a1` | R33.8 | Charging is relevant to an offensive drive, but `offensive_contact` alone does not show a push into the defender's torso. | Still a ranking miss; add physical charge evidence to the fixture. |
| `drive_technical_marker` | R36.2.1 | Behavioural technical definition is relevant, but the case simultaneously has drive contact; the marker has decision priority. | Hit after focused routing; fixture remains synthetic. |
| `drive_interference_marker` | R31.2.4 | Correct interference clause, but the fixture lacks shot/rim-contact evidence and has a held ball. | Hit after focused routing; fixture needs physical evidence. |
| `drive_unsportsmanlike` | R37.1.1 | Definition requires excessive, hard, or dangerous contact; the fixture only has a Boolean marker. Retrieved penalty clauses are not interchangeable gold labels. | Still a ranking miss; add contact-severity evidence. |
| `reach_shooting` | R15.1.2 or R34.2.2 | Shooting clauses are relevant; general contact and non-shooting penalty chunks displaced them. | Hit after focused routing and correcting R34.2.1. |
| `reach_unsportsmanlike` | R37.1.1 | Same missing severity evidence as the drive case. | Still a ranking miss. |
| `screen_stalling_marker` | R29.1.1 | Stalling clause is relevant, but active-play/shot-clock evidence is absent and screen/contact rules ranked higher. | Hit after focused routing; fixture needs timing/play evidence. |
| `no_contact_screen` | R33.7 | Legal/illegal screening remains relevant without contact; the old filter selected only stalling. | Filter miss fixed. |

The other 14 labelled states were also checked for indexed IDs, category
eligibility, and clause relevance: R33.9 covers blocking on drives, R33.11
covers hand/arm contact on reaches, R33.7 covers screens, and R36.2.1 covers
technical conduct. R33.5 is a broad off-ball-guarding clause used for the three
rebound/box-out cases; it is plausible context but does not by itself establish
that a box-out was illegal. The benchmark tests clause retrieval, not referee
decision correctness. In particular, labels were **not** expanded to include
generic or penalty clauses merely because those chunks happened to rank highly.

The category audit found these source-text mismatches:

| Clause/article | Earlier category | Corrected treatment |
| --- | --- | --- |
| R33.6, airborne-player landing/contact | `loose_ball` | `personal_contact` |
| R33.13–R33.15, rear guarding/holding/pushing | `illegal_use_of_hands` | `personal_contact`; R33.11 remains hand/arm contact |
| R34.2 and R34.2.1, general/non-shooting contact penalties | `shooting_foul` | `personal_contact`; R34.2.2 remains shooting foul |
| Articles 38–39, disqualification/fighting | `unsportsmanlike` | Excluded: those call types are not supported by the referee schema |

R33.5 remains in `loose_ball` as the available off-ball-guarding clause for a
rebound/box-out; this is an approximation worth revisiting with fuller cases.
The rebuilt MiniLM index contains 95 chunks (`chunks_sha256` starts
`cc8eb0bb`); source PDF and model did not
change. The indexed JSONL and embedding matrix were regenerated together so
their manifest checksums remain aligned.

## Step 3: Change retrieval and remeasure

`categories_for_state` now gives explicit judgement markers first priority,
then a shooting-contact rule issue, then the contact-specific category; a
no-contact screen selects `screening`. Cosine similarity still ranks chunks
within the selected category, with at most three results. The deterministic
query text and the 26 gold labels were not changed. This limits broad contact
and penalty clauses from displacing a more specific rule issue. Team-foul
penalty categories remain available when the contact state reaches the team
foul threshold.

After rebuilding the index, the same evaluator measured **22/26 hit@3
(84.6%)** and **26/26 category eligibility (100%)**. All eight gained hits
came from the original 12 misses; none of the original 14 hits regressed.
The four remaining misses are `drive_goaltending_marker`,
`drive_offensive_a1`, `drive_unsportsmanlike`, and `reach_unsportsmanlike`.
All are ranking misses, not filter misses. This is an in-sample improvement on
synthetic states, not evidence of live-game decision accuracy.

## Reproduce

```bash
HF_HUB_OFFLINE=1 .venv/bin/python scripts/validate_referee_retrieval.py
HF_HUB_OFFLINE=1 .venv/bin/pytest -q tests/test_referee_index.py tests/test_referee_retriever.py tests/test_referee_retrieval_validation.py
```

The original 14/26 baseline is retained above and in `README.md`, even though
the checked-in index and routing now produce the revised 22/26 score.

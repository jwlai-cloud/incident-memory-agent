# 0004 — Match threshold calibrated to 0.45 against real embeddings

- Status: Accepted
- Date: 2026-07-26

## Context

`decide.py` treats a pattern as matched when cosine distance ≤ `MATCH_MAX_DISTANCE`.
The whole demo hinges on this number: seeded incidents must match, `novel_airflow`
must **not** (so it escalates and gets taught), and afterwards the taught pattern
must match its BigQuery and dbt cousins. We shipped a placeholder of 0.30 and
flagged it for calibration once real Titan embeddings existed.

`smoke_test.py --calibrate` initially compared only *pre-teach* distances and
suggested **0.297**. That looked clean — seeds at 0.000, drift ≥ 0.593 — but it
measured the wrong constraint.

## Decision

`MATCH_MAX_DISTANCE = 0.45`, and `--calibrate` now also measures post-teach
pollination distances and warns when the current default falls outside the safe
window.

Measured against Titan Text Embeddings v2 (512-d, normalized):

| pair | distance | requirement |
|---|---|---|
| seed signal → its own pattern | 0.000 | must match |
| taught drift pattern → `pollinate_bq` | 0.283 | must match |
| taught drift pattern → `pollinate_dbt` | **0.321** | must match |
| drift signal → nearest *seed* | 0.593 | must NOT match |
| unrelated pairs | 0.70–0.88 | must NOT match |

Safe window is therefore (0.321, 0.593). 0.45 sits mid-window.

## Consequences

- The suggested 0.297 — and our original 0.30 guess — sit **below** 0.321, so the
  dbt cross-system match would have silently failed on camera. The beat would have
  shown "no precedent" for an incident the agent had just been taught.
- A calibrator that measures only half the constraints is worse than none: it
  produces a confident wrong number. The lesson generalizes — calibrate against
  every requirement the value has to satisfy, not the convenient subset.
- Re-run `--calibrate` whenever `embed.signature()` changes; the window moves with
  the signature text.

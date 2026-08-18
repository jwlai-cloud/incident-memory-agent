# Demo script — 3-minute video

> **Superseded for recording.** This is the design-time storyboard: it fixes the incident
> cast and the beats the product had to support. The shot list actually recorded lives in
> [`VIDEO_SCRIPT.md`](VIDEO_SCRIPT.md), against the operator dashboard and its real button
> labels. Keep this file for the cast table and the recording rules; follow that one to
> shoot.

## Incident cast (produced by `scripts/simulate_incidents.py`)

| ID | System | What it is | Role |
|---|---|---|---|
| `seed_1..3` | mixed | Known incident types pre-seeded into memory | Beat 2 matches |
| `novel_airflow` | Airflow | Schema-drift task failure — no precedent | The teach moment |
| `pollinate_bq` | BigQuery | Same failure class, different system | Cross-system money shot |
| `pollinate_dbt` | dbt | Same class again, third system — a **model build error** (`run_results.json` `status:"error"`), not a test failure; see ADR 0003 | Optional reinforcement |
| `crdb_hot_range` | CockroachDB | Hot-range/contention on the agent's **own** `agent_decisions` table; see ADR 0005 | Beat 6 — all four tools |
| `trust_repeat` | Airflow | A repeat of a seed pattern, N-th time | Trust-ledger ask |

Timing of every injection is explicitly controlled in `replay.py` —
never natural order. Rehearse the full sequence before recording.

## Beat-by-beat

| Time | Beat |
|---|---|
| 0:00–0:15 | Problem + architecture diagram. One line: "incident memory that survives anything — including the incident." |
| 0:15–0:35 | **Memoryless counterfactual (the villain).** Flag off: incident stream runs, EVERY incident escalates, queue floods. One query on camera: escalation rate 100%. "This is on-call without memory." |
| 0:35–0:55 | Flip memory on, same stream: known incidents match instantly, precedents cited, queue melts. Same query: escalation rate collapses. Day-1 vs. now, in 20 seconds. |
| 0:55–1:15 | `novel_airflow` fires — schema drift, no confident match — agent **honestly escalates** instead of guessing. You diagnose live, write the root cause in your own words, approve. New pattern written (`source='promoted'`). |
| 1:15–1:40 | **Cross-system money shot:** `pollinate_bq` fires — different system, same failure class — matched instantly against the pattern taught 20 seconds ago. `applies_to` grows on camera. One lesson, two systems (add `pollinate_dbt` for three if pacing allows). |
| 1:40–2:05 | **Beat 6 — CockroachDB-native incident, all four tools:** `crdb_hot_range` fires on the memory cluster itself. Match → pattern's `remediation_channel='ccloud_skill'` → agent proposes the exact Agent Skill + ccloud command → you approve → live ccloud execution, JSON output in the UI. Voiceover: "the agent uses CockroachDB's own published expertise to keep its own memory healthy." |
| 2:05–2:25 | **Trust ledger:** `trust_repeat` fires — the agent notes "5 unchanged approvals on this pattern" and asks for pre-authorization. You grant it on camera. Show the runbook view: the row now reads `autonomy_granted = true`. |
| 2:25–2:45 | Open `runbook` (the self-written documentation view) + one MCP chat query: "which patterns earned autonomy, and what precedent does each cite?" |
| 2:45–3:00 | Tools recap (honest four-tool split), repo link. |

## Recording rules

- Rehearse from a clean checkout, full sequence, before the real take.
- Beat 6 fallback if live ccloud is flaky: show the exact proposed
  command, cut to a pre-recorded execution. Attempt live first.
- Never show more than ~6 items in the review queue — the point is
  the human sees almost nothing, not that they review everything.
- The counterfactual beat must visibly use the SAME incident stream
  both times — same IDs on screen — or it reads as staged.

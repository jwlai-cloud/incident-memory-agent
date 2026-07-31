# Architecture — Mimir incident-memory agent

*Snapshot of the current system. Replace, don't append.*

## One-paragraph shape

An incident-triage agent for data platforms (Airflow, BigQuery, dbt, and
CockroachDB itself). Its memory — every past incident pattern **and** the
per-pattern record of how much the human trusts its judgment — lives in
**CockroachDB**. Embeddings come from **AWS Bedrock** (Titan Text v2); the
decision step runs as an **AWS Lambda**. A lesson taught once from one system
is instantly matchable for a cousin incident in another, because one store holds
both the vectors and the structured trust/audit ledger with no replication lag.

## Components

| Component | File | Role |
|---|---|---|
| Incident simulator | `scripts/simulate_incidents.py` | Generates the 8-incident demo cast as `monitored_signals` rows with authentic payload shapes; deterministic injection order. |
| Signature + embedding | `scripts/embed.py` | `signature(signal)` → normalized NL string → Bedrock Titan v2 → 512-d vector. Shared by seeding and live decisions. |
| Pattern seeding | `scripts/seed_patterns.py` | Seeds the 4 pre-loaded patterns with human-written `root_cause`/`resolution` + trust preload. |
| Decision engine | `scripts/decide.py` | Lambda body: embed → cosine top-k (`<=>`) → deterministic action → `agent_decisions`. Honors `memory_enabled`. |
| Response / trust ledger | `scripts/respond.py` | approve/modify/reject → ledger updates; explicit earned autonomy; auto-revoke. |
| Teach | `scripts/teach.py` | Escalation → new pattern (`source='promoted'`), embedded from the signal so cousins match. |
| Beat-6 execution | `scripts/ccloud_wrapper.py` | Runs the `analyzing-range-distribution` Agent Skill's read-only diagnostic against the agent's own memory tables; captures JSON into the decision. |
| Reset / calibrate | `scripts/reset_demo.py`, `scripts/smoke_test.py` | Restore a clean baseline; measure real embedding distances and the counterfactual. |
| Demo console | `app.py`, `templates/index.html` | Flask layer over the scripts: guided 7-beat rail, incident timeline, trust/runbook panel, live-SQL proof panel. No business logic of its own. |

## Data model (CockroachDB — `schema/schema.sql`)

- **`monitored_signals`** — raw incidents: `source_system`, `signal_type`,
  `asset`, `payload` JSONB (`{demo, artifact, baseline}`), `observed_at`.
- **`incident_patterns`** — the memory. `embedding VECTOR(512)` indexed with
  `vector_cosine_ops`; `failure_class` (cross-system generalization axis);
  `applies_to STRING[]` (systems confirmed in); `root_cause`/`resolution`
  (human worked example); `risk_level`; `remediation_channel`/`skill_ref`; and
  the **trust ledger** columns (`approved_unchanged_count`, `modified_count`,
  `rejected_count`, `autonomy_granted`, `autonomy_granted_at`,
  `autonomy_revoked_at`); `source` (`seed` | `promoted`).
- **`agent_decisions`** — audit log: `matched_pattern_id`, `similarity`,
  `action`, **`memory_enabled`** (the counterfactual flag), `reasoning`,
  `human_response`, `outcome`. Indexed on `(memory_enabled, decided_at)` for the
  day-1-vs-now comparison.
- **`runbook`** — a VIEW over `incident_patterns`; self-writing documentation,
  always current, never hand-edited.

## Decision flow (`decide.py`)

```
signal ──▶ embed.signature() ──▶ Bedrock Titan ──▶ 512-d vector
                                                      │
                        cosine top-k  ORDER BY embedding <=> $1 LIMIT k
                                                      │
                                                classify() — DETERMINISTIC
   memory_enabled=false ............................ escalate (counterfactual)
   no row / distance > MATCH_MAX_DISTANCE ........... escalate (teach moment)
   matched, risk_level='high' ....................... escalate WITH precedent cited
   matched, low-risk, autonomy granted & !revoked ... auto_resolve
   matched, low-risk, otherwise ..................... propose
                                                      │
                                             write agent_decisions
```

The **action is pure rules** (testable, no LLM). Bedrock's Converse API writes
only the human-readable `reasoning` prose, with a template fallback.

## Trust ledger (`respond.py`)

Autonomy is **earned, explicit, revocable**:
- `approve_unchanged` → `approved_unchanged_count +1`, `confirm_count +1`, grow
  `applies_to` if the signal's system is new.
- `modify` → `modified_count +1` (does not advance the unchanged streak).
- `reject` → `rejected_count +1`; if currently granted, `autonomy_revoked_at=now`.
- `grant_autonomy` (explicit human action) is gated by `can_grant()`:
  low-risk, `approved_unchanged_count ≥ 5`, `rejected_count = 0`. High-risk is
  never grantable (schema/data always gets full human diagnosis).

All ledger writes are in-SQL (`col = col + 1`, conditional `array_append`,
single-UPDATE reject-revoke) → no read-modify-write race; CockroachDB's
serializable default makes concurrent responses safe.

## The honest four-tool split

- **Distributed Vector Indexing** + **MCP Server** — load-bearing for every
  incident, any system. The core memory and the analyst interface.
- **ccloud CLI** + **Agent Skills** — load-bearing only for the
  CockroachDB-native incident (beat 6): a matched pattern with
  `remediation_channel='ccloud_skill'` proposes the real
  `analyzing-range-distribution` skill from `cockroachlabs/cockroachdb-skills`,
  executed via ccloud. These do not diagnose Airflow/BigQuery/dbt.

## External dependencies

- **AWS Bedrock** — Titan Text Embeddings v2 (`amazon.titan-embed-text-v2:0`,
  512 dims, normalize=true) for embeddings; Converse API (default
  `amazon.nova-micro-v1:0`, env-configurable) for reasoning prose.
- **AWS Lambda** — hosts `decide.py` (`handler(event, context)`).
- **CockroachDB** (Cloud Basic, or self-hosted single-node) — memory +
  vectors + ledger. Vector index requires
  `SET CLUSTER SETTING feature.vector_index.enabled = true`.

## Verified behaviour (live cluster, 2026-07-28)

Measured on CockroachDB Cloud Basic v26.2.1 (AWS us-east-1) with Bedrock Titan v2:

| Claim | Observed |
|---|---|
| Memoryless counterfactual | escalation **100% → 38%** over the same 8 signals |
| Cross-system pollination | taught pattern matches `pollinate_bq` at 0.72 and `pollinate_dbt` at 0.68 similarity |
| `applies_to` growth | `[airflow]` → `[airflow, bigquery]` → `[airflow, bigquery, dbt]` |
| Rule 1 (high-risk) | drift matches cite the precedent yet still escalate |
| Trust ledger | 5th unchanged approval fires the ask; grant sticks; one rejection revokes |
| Beat 6 | skill diagnostic returns live range ids / replica counts for `agent_decisions` |

Match threshold `MATCH_MAX_DISTANCE = 0.45`, calibrated — see ADR 0004.

## Platform constraints (Cloud Basic)

- `SHOW RANGES … WITH DETAILS` is rejected (no node-level internals for serverless
  tenants), so beat 6 uses per-index range distribution instead of leaseholder
  counts — see ADR 0005.
- Placeholders inside `ANY()` / `array_append` need an explicit `::STRING` cast.
- The vector index requires `SET CLUSTER SETTING feature.vector_index.enabled = true`,
  which Basic does permit.

## Deployment topology

Demo: CockroachDB Cloud Basic (AWS us-east-1) · Flask console on localhost ·
scripts as CLI tools. `decide.handler` is Lambda-shaped and deploys unchanged.

Production shape: CockroachDB CDC on `monitored_signals` inserts → Lambda
(`decide.handler`) → review queue, rather than the demo's explicit invoke.

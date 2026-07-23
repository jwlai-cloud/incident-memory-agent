# Incident memory agent ("Mimir") — project context

## What this is

An agentic app for the **CockroachDB × AWS Hackathon** ("Build with
Agentic Memory"). An incident triage agent for data platforms
(Airflow, BigQuery, dbt, and CockroachDB itself) whose memory of past
incidents — and of how much the human trusts its judgment per pattern
— lives in CockroachDB. A lesson taught once, anywhere, is instantly
reusable everywhere, and survives any failure.

- Challenge page: https://cockroachdb-ai.devpost.com/
- Requirements: https://cockroachdb-ai.devpost.com/#challenge-requirements
- Rules: https://cockroachdb-ai.devpost.com/rules
- CockroachDB AI docs: https://www.cockroachlabs.com/docs/stable/cockroachdb-and-ai
- Agent Skills background: https://www.cockroachlabs.com/blog/cockroachdb-ai-agents-agent-ready-database/
- Deadline: **Aug 18, 2026** — submit days early.

Read `docs/DESIGN.md`, `docs/DEMO_SCRIPT.md`, `docs/HANDOVER.md`
before writing code. They contain the reasoning, not just decisions.
This project fully supersedes an earlier fraud-detection direction.

## The three differentiators (never cut; see DESIGN.md for detail)

1. **Trust ledger** — per-pattern memory of human responses
   (approved-unchanged / modified / rejected). Autonomy is earned by
   track record, granted only by explicit human action, revoked by a
   single rejection. The HITL gate is learned, not hardcoded.
2. **Memoryless counterfactual** — a `memory_enabled` flag that skips
   the vector lookup; same incident stream floods the queue. The demo
   villain. No infrastructure kill demos.
3. **Cross-system pollination** — `failure_class` + `applies_to`:
   the central demo pattern (schema drift) is taught once from an
   Airflow incident and then matches BigQuery/dbt incidents.

## Non-negotiable design rules

1. **HITL always** for anything not explicitly `autonomy_granted`;
   `risk_level='high'` (anything touching schema or data) escalates
   to full human diagnosis regardless of match confidence, always.
2. **Honest four-tool split** — Vector Indexing + MCP Server are
   load-bearing everywhere; ccloud CLI + Agent Skills apply ONLY to
   CockroachDB-native incidents (demo beat 6). Never imply ccloud
   fixes Airflow/BigQuery. Say the split plainly in submission text.
3. **Simulated incidents are declared, and authentic in shape** —
   real Airflow exception JSON shapes, real BigQuery job-error
   structure, real dbt test artifacts. No random-number payloads.
4. **No TrafficGuard-derived logic, data, or incident history.**
   Fresh public build.
5. `root_cause` is always the human's own written rationale at
   teach-time; it feeds the Bedrock reasoning call on future matches
   (the Spotify "worked example" principle — see DESIGN.md lineage).
6. Repo name stays descriptive; "Mimir" is a README tagline only.

## Current repo state

Scaffolding + docs only; no real CockroachDB/AWS calls yet.

```
schema/schema.sql        — monitored_signals, incident_patterns (trust ledger), agent_decisions (memory_enabled), runbook view
docs/DESIGN.md           — full rationale incl. beat-6 ccloud/skills design
docs/DEMO_SCRIPT.md      — 3-min storyboard, incident cast, recording rules
docs/HANDOVER.md         — build order + submission checklist
docs/architecture.svg
.env.example
```

## Build order (full detail in HANDOVER.md §2)

1. `scripts/simulate_incidents.py` — incident cast w/ authentic payloads, explicit injection order
2. `embed.py` — incident signature → Bedrock Titan embedding (shared by seed + live)
3. `seed_patterns.py`
4. `decide.py` — Lambda handler: embed → cosine_distance top-k → auto/propose/escalate; honor `memory_enabled`
5. `respond.py` — approve-unchanged/modify/reject; trust ledger updates; explicit autonomy grants; auto-revoke on rejection
6. `teach.py` — escalation resolution → new pattern (`source='promoted'`)
7. ccloud execution wrapper (beat-6 proposals only)
8. MCP wiring
9. Minimal UI — feed, review queue, trust/runbook view, chat, memory on/off toggle

## First task

Build `scripts/simulate_incidents.py` per HANDOVER.md §2.1, then
apply `schema/schema.sql` to a real CockroachDB Cloud cluster and
verify the `runbook` view works, then start `embed.py`.

# 0005 — Beat 6 targets the agent's own memory tables

- Status: Accepted
- Date: 2026-07-28

## Context

The CockroachDB-native beat fires a simulated hot-range signal, matches a pattern
whose `remediation_channel = 'ccloud_skill'`, and on approval runs the real
`analyzing-range-distribution` Agent Skill from `cockroachlabs/cockroachdb-skills`.

The simulated payload originally described a hotspot on `orders_db.order_events`
— a fictional table, consistent with the other simulated incidents. But unlike
Airflow or BigQuery payloads, this one is not merely *displayed*: the skill's
diagnostic SQL actually executes against our cluster. It failed with
`InvalidCatalogName: database "orders_db" does not exist`.

## Decision

The hot-range incident targets **`defaultdb.public.agent_decisions`** — one of the
agent's own memory tables — with the real range id and replica set observed on the
cluster.

The diagnostic also had to change. The skill's documented Query 3 groups by
`lease_holder`, which only exists under `SHOW RANGES ... WITH DETAILS`, and
CockroachDB Cloud **Basic rejects DETAILS** (serverless tenants get no node-level
range internals: `rpc error … connection reset by peer`). The wrapper runs the
tier-compatible half of the same analysis — per-index range distribution and
replica counts — which is what actually diagnoses a sequential-key hotspot.

## Consequences

- The claim in DESIGN.md — *"the agent uses CockroachDB's own published expertise
  to keep its own memory layer healthy"* — becomes literally true rather than
  narrative framing. `agent_decisions` is an append-only audit log with a
  `decided_at` index, so time-ordered inserts genuinely do concentrate on the
  newest range. The incident is simulated in its *metrics*, real in its *subject*.
- The skill's diagnostic returns live range ids, index names and replica counts
  from the demo cluster — unmistakably not mocked.
- Seed pattern text for `sequential-key-write-hotspot` was rewritten to describe
  the `decided_at` index rather than a fictional `order_events` primary key.
- Note for the submission: the skill as published assumes a tier that exposes
  leaseholder data. Worth reporting as feedback (the rules invite it).

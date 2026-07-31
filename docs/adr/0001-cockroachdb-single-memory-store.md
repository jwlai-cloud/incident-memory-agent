# 0001 — CockroachDB as the single memory + vector + ledger store

- Status: Accepted
- Date: 2026-07-23

## Context

The agent needs three kinds of memory: vector embeddings of incident patterns,
structured pattern metadata + a trust ledger, and an append-only decision audit
log. A common design splits these across a vector DB + an operational DB. This
is a CockroachDB × AWS hackathon; CockroachDB must be the persistent memory layer.

## Decision

Use one CockroachDB cluster for all of it. `incident_patterns` holds the
`VECTOR(512)` embedding, the `applies_to`/`failure_class` generalization fields,
the human-written `root_cause`/`resolution`, and the trust-ledger columns.
`agent_decisions` holds the audit log. A `runbook` VIEW exposes the memory as
self-writing documentation.

## Consequences

- No vector-DB ↔ operational-DB sync problem; a pattern taught from one system
  is instantly matchable for another (transactional freshness, no reindex lag).
- The "memory survives the incident" claim is credible because the memory and
  the operational state are the same fault-tolerant store.
- Requires CockroachDB v25.2+ for the vector index (preview) and the
  `feature.vector_index.enabled` cluster setting.
- Rejected: Postgres+pgvector — can do a single-node version but cannot make the
  freshness-under-distributed-failure claim.

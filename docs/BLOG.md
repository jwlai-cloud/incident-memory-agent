---
title: "Building an incident-memory agent that survives the incident (CockroachDB + AWS Bedrock)"
published: false
tags: [cockroachdb, aws, ai, agents]
canonical_url: ""
cover_image: ""
---

> Built for the CockroachDB × AWS "Build with Agentic Memory" hackathon.
> Repo: `incident-memory-agent` · **[Interactive walk-through](https://claude.ai/code/artifact/45d43973-9d2e-4b78-819d-a5acd2e5a872)** (the widgets run the real decision logic).

On-call at 3am, the question you actually ask is *"have we seen this before?"* — and that's exactly the moment your tooling is most likely to be on fire. An incident agent whose memory goes offline during an incident doesn't degrade gracefully; it stops. So I built the memory as the product, on a database designed to survive the failure it's remembering.

Meet **Mimir** — an incident-triage agent for data platforms (Airflow, BigQuery, dbt, and CockroachDB itself). Its memory of every past incident, *and* of how much the human trusts its judgment, lives in CockroachDB. A lesson taught once, in one system, is instantly reusable in the next.

## Everyone remembers incidents. Three things beyond that matter.

The easy version of this project is "an agent that stores incidents and retrieves similar ones." Here's what a *production* on-call agent needs on top — and each maps to a column in the schema:

**1. A trust ledger.** The agent remembers the outcome of its *own* judgment, per pattern. Every time you approve its proposal unchanged, a counter ticks up. At five unchanged approvals with zero rejections, it asks: *"I've proposed this fix five times and you approved it every time — pre-authorize this pattern?"* Autonomy is **earned** by track record, **granted** only by your explicit click, and **revoked** the instant you reject once. The human-in-the-loop gate is learned, not hardcoded — and anything touching schema or data is `risk_level='high'` and can *never* go autonomous.

**2. A memoryless counterfactual.** The demo villain is one boolean. `memory_enabled=false` skips the vector lookup entirely, and the same incident stream floods the review queue — every incident escalates, because the agent has amnesia. Flip it back on and the queue melts as precedents get cited. Before/after on-call life, for the cost of a single column, with no infrastructure to kill on camera.

**3. Cross-system pollination.** A `failure_class` taught from one Airflow incident matches its BigQuery and dbt cousins in embedding space. Upstream renames a column; the Airflow task throws a `KeyError`, BigQuery throws `Unrecognized name`, dbt throws `column does not exist`. Three different errors, one root cause — and one lesson, taught once, catches all three.

## How it's built

Six small Python programs around one CockroachDB database:

- **`simulate_incidents.py`** — the demo cast, with *authentic payload shapes* (real Airflow `TaskInstance` JSON, real BigQuery `ErrorProto`, real dbt `run_results.json`, the real CockroachDB hot-range status struct). Simulated, and declared — but authentic in shape.
- **`embed.py`** — turns a signal into a normalized natural-language *signature*, then an AWS Bedrock Titan v2 embedding (512 dims). The signature leads with a system-agnostic symptom, so the schema-drift trio clusters across platforms while keeping per-system detail — genuine semantic similarity, not string matching.
- **`seed_patterns.py`** — seeds the pre-loaded patterns with human-written `root_cause`/`resolution` (the "worked example" that feeds reasoning on future matches).
- **`decide.py`** — the engine. Embed → cosine `<=>` top-k against CockroachDB's C-SPANN vector index → **a deterministic rule matrix** picks one action. No LLM decides; Bedrock's Converse API only writes the human-readable *why*, with a template fallback.
- **`respond.py`** — the trust ledger. Approve/modify/reject; the explicit autonomy grant; auto-revoke. Every update is in-SQL and atomic, so CockroachDB's serializable isolation makes concurrent responses safe.
- **`teach.py`** — promotes an escalation into a new pattern, embedded from the escalated signal so its cousins match. This closes the teach → pollinate loop.

### Why CockroachDB specifically

One store holds the vectors *and* the structured trust/audit ledger — no vector-DB↔operational-DB sync, no reindex lag. A pattern taught from an Airflow incident is transactionally matchable for a BigQuery one the same second. And because it's a distributed, fault-tolerant store, the "memory survives the incident" claim is credible: the memory and the operational state are the same resilient thing. Postgres + pgvector can do a single-node version; it can't make the freshness-under-distributed-failure claim.

## The hardest calls

- **The decision is rules, the prose is the LLM.** It's tempting to let a model decide auto-resolve vs escalate. But that governs a *safety gate* — it has to be predictable, testable, auditable. So the branch is a pure function with a truth-table self-check; the LLM only explains. The hackathon's own judges confirmed deterministic coordination still counts as "agentic."
- **The single riskiest number is a distance threshold.** The whole demo hinges on: seeds match, a genuinely novel incident does *not* (so it escalates and you teach it), then its taught cousins *do* match. That threshold can only be calibrated against real embeddings — so it's an env var, flagged loudly, calibrated live.
- **Authenticity over convenience.** Every payload shape and every SDK call was verified against current vendor docs, not training-data memory — a hackathon's featured SDK is usually newer than any model's cutoff. That's how I caught that CockroachDB's cosine metric is set by an index opclass (`vector_cosine_ops`), not a query function, and that there's no `crdb_internal.hot_ranges` table (it's a status API).

## The self-referential kicker

The CockroachDB-native incident is a write hotspot on the memory cluster itself. The agent matches it, then proposes running CockroachDB's own published Agent Skill — the real [`analyzing-range-distribution`](https://github.com/cockroachlabs/cockroachdb-skills) skill — via the ccloud CLI. The agent uses CockroachDB's own expertise to keep its own memory layer healthy. Memory defending itself.

## Try it

The **[interactive walk-through](https://claude.ai/code/artifact/45d43973-9d2e-4b78-819d-a5acd2e5a872)** lets you toggle the counterfactual, teach the schema-drift pattern and watch it pollinate, and earn autonomy in the trust-ledger simulator — every widget runs the real decision logic described above.

*Consult what survived.*

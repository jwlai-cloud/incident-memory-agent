---
title: "Building an incident-memory agent that survives the incident (CockroachDB + AWS Bedrock)"
published: false
tags: [cockroachdb, aws, ai, agents]
canonical_url: ""
cover_image: ""
---

> Built for the CockroachDB × AWS "Build with Agentic Memory" hackathon.
> **[Live demo](https://incident-memory-agent.vercel.app)** · **[Interactive walk-through](https://incident-memory-agent.vercel.app/tutorial)** · **[Repo](https://github.com/jwlai-cloud/incident-memory-agent)**
>
> Every number below is measured on a real CockroachDB Cloud cluster in AWS us-east-1, not estimated.

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
- **The single riskiest number is a distance threshold** — and my calibrator got it confidently wrong. The demo hinges on three things at once: seeds match, a genuinely novel incident does *not* (so it escalates and you teach it), then its taught cousins *do*. I wrote a calibrator to derive the threshold from real embeddings. It measured seeds at 0.000 and un-taught drift at 0.593, and recommended **0.297**. It was measuring the wrong constraint: the distance that actually binds is *taught pattern → cross-system cousin*, and the dbt cousin sits at **0.321** — above the recommendation. Shipping that number would have shown "no precedent" for an incident the agent had been taught thirty seconds earlier, on camera. A calibrator that measures half the constraints is worse than none.
- **Authenticity over convenience.** Every payload shape and every SDK call was verified against current vendor docs, not training-data memory — a hackathon's featured SDK is usually newer than any model's cutoff. That's how I caught that CockroachDB's cosine metric is set by an index opclass (`vector_cosine_ops`), not a query function, and that there's no `crdb_internal.hot_ranges` table (it's a status API).

## What the real cluster taught me that offline tests could not

Every self-check passed for days before a cluster existed. Then the infrastructure
produced four findings none of them could have surfaced:

- **`TRUNCATE` is a schema change in CockroachDB.** It took **68.6 seconds** on tables
  holding a handful of rows, because it creates a new descriptor through a job.
  `DELETE` took the same reset to **2.8s**.
- **`sslrootcert=system` doesn't work.** CockroachDB Cloud signs with its own CA, so the
  CA has to be supplied explicitly — here through an env var rather than a committed file.
- **`SHOW RANGES … WITH DETAILS` is rejected on Cloud Basic.** Serverless tenants get no
  node-level range internals. The hot-range diagnostic uses per-index range distribution.
- **A placeholder inside `ANY()` / `array_append` needs an explicit `::STRING` cast** —
  which is the exact line that grows the list of systems a lesson applies to.

And the self-referential beat was fiction until it wasn't: the hot-range payload
originally described `orders_db.order_events`, which is fine for a payload that is only
*displayed* and fatal for one whose SQL actually *executes*. It died with
`InvalidCatalogName`. Pointing it at `agent_decisions` — the agent's own append-only log,
whose timestamp index genuinely concentrates writes on the newest range — made the beat
both work and mean what I'd claimed.

## What it does, measured

| | |
|---|---|
| Memoryless counterfactual | escalation **100% → 38%** across the same 8 signals |
| Cross-system pollination | taught pattern matches BigQuery at **0.72** and dbt at **0.68** similarity |
| `applies_to` growth | `[airflow]` → `+bigquery` → `+dbt`, from one lesson |
| Trust ledger | 5th unchanged approval fires the ask; the grant sticks; one rejection revokes |
| Hot-range beat | the skill returns **live range IDs** for the agent's own `agent_decisions` table |
| Reset latency | 68.6s → **2.8s** |
| Decision latency | 13.5s → **1.5s** for 8 concurrent decisions |

## The self-referential kicker

The CockroachDB-native incident is a write hotspot on the memory cluster itself. The agent matches it, then proposes running CockroachDB's own published Agent Skill — the real [`analyzing-range-distribution`](https://github.com/cockroachlabs/cockroachdb-skills) skill — via the ccloud CLI. The agent uses CockroachDB's own expertise to keep its own memory layer healthy. Memory defending itself.

## Try it

The **[live dashboard](https://incident-memory-agent.vercel.app)** is the operator view: per-source health, a queue ordered by what needs a human, and a "show the record" control on every incident that opens its actual `monitored_signals` row — id, timestamp, and the raw upstream error as stored. The incident *stream* is generated for the demo; the vector search, the decisions and the ledger are live, and that record view is there so the claim is checkable rather than asserted.

The **[interactive walk-through](https://incident-memory-agent.vercel.app/tutorial)** teaches the build: toggle the counterfactual, teach the schema-drift pattern and watch it pollinate, and earn autonomy in the trust-ledger simulator — every widget runs the real decision logic described above.

*Consult what survived.*

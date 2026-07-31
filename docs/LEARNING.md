# Learning — the tech behind Mimir, with primary sources

*Written to be read slowly, after the hackathon. What each piece actually does,
why it was chosen, and where the authoritative docs are.*

---

## 1. CockroachDB vector search

**What it does.** CockroachDB stores embeddings in a `VECTOR(n)` column (pgvector
type-compatible) and does approximate nearest-neighbour search with the
**C-SPANN** vector index. We match incidents by cosine distance.

**Key facts we verified:**
- `VECTOR(n)` type: since **v24.2**. The vector index (C-SPANN): **v25.2**, in
  preview. Needs `SET CLUSTER SETTING feature.vector_index.enabled = true`.
- Cosine is the **`<=>` operator** (`<->` = L2, `<#>` = inner product). There is
  no reliable `cosine_distance()` function — use the operator.
- The metric is fixed by an **opclass at index creation**: `vector_cosine_ops`
  for cosine (default is `vector_l2_ops` = L2). We had to correct our schema.
- A vector is inserted as a **string literal** `'[0.1,0.2,...]'` over pgwire —
  not a Postgres array, not JSON.
- Works on self-hosted single-node, not Cloud-only.

**Why CockroachDB.** An incident-response agent's memory going down *during* an
incident is the worst failure mode for this use case. One store holds the
vectors **and** the structured trust/audit ledger — no separate vector-DB +
operational-DB sync. Transactional freshness means a pattern taught from an
Airflow incident is instantly matchable for a BigQuery one, no reindex lag.

**Sources:**
- Vectors: https://www.cockroachlabs.com/docs/stable/vector
- Vector indexes: https://www.cockroachlabs.com/docs/stable/vector-indexes
- Distributed vector indexing (C-SPANN): https://www.cockroachlabs.com/blog/distributed-vector-indexing-cockroachdb/
- Reference sample we validated our query shape against: https://github.com/codingconcepts/crdb_ai_zero_to_hero

## 2. AWS Bedrock — Titan Text Embeddings v2

**What it does.** Turns the incident signature string into a 512-float vector.

**Key facts:**
- modelId `amazon.titan-embed-text-v2:0`; request `{inputText, dimensions, normalize}`.
- `dimensions` ∈ {256, 512, **1024** default}; we use 512 to match `VECTOR(512)`.
- `normalize=true` (default) returns unit vectors → cosine distance ≡ 1 − dot product.
- Response float array under key `embedding`. Embeddings go through
  `invoke_model` only (the Converse API is for chat models).

**Sources:**
- https://docs.aws.amazon.com/bedrock/latest/userguide/titan-embedding-models.html
- https://docs.aws.amazon.com/bedrock/latest/userguide/model-parameters-titan-embed-text.html

## 3. AWS Bedrock — Converse API (reasoning prose)

**What it does.** After a match, writes the human-readable "why I think this is
X" text from the matched pattern's `root_cause`. **The decision itself is not an
LLM** — Converse only generates prose, with a template fallback.

**Key facts:**
- `client.converse(modelId=…, messages=[{role,content:[{text}]}], system=[{text}], inferenceConfig={maxTokens,temperature})`.
- Assistant text at `response["output"]["message"]["content"][0]["text"]`.
- Default model `amazon.nova-micro-v1:0` (cheap/free-tier-friendly). Any Converse
  model works (DeepSeek `deepseek.r1-v1:0`, Claude Haiku). Some models require a
  **geo-profile prefix** (`us.`/`eu.`/`apac.`) for on-demand — we catch the
  `ValidationException` ("on-demand throughput isn't supported") and retry with `us.`.

**Sources:**
- https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-amazon-nova-micro.html
- boto3 converse: https://docs.aws.amazon.com/boto3/latest/reference/services/bedrock-runtime/client/converse.html

## 4. The signature — why embeddings, not rules

**What it does.** `signature(signal)` builds a normalized natural-language line
that leads with a **system-agnostic symptom**, then context, then a qualitative
deviation. For schema drift, all three systems surface the shared entity
(`customer_region`) and concept (`schema drift`, `missing`/`not found`) while
keeping per-system detail:

```
airflow:  schema drift: expected column 'customer_region' missing … KeyError …
bigquery: schema drift: column 'customer_region' not found - BigQuery invalidQuery …
dbt:      schema drift: column 'customer_region' does not exist - dbt model build error …
```

**Why.** Rule matchers don't cross-pollinate. A normalized symptom phrase makes
the *behavioral signature* of a failure rhyme across platforms in embedding
space — so a lesson taught from Airflow matches its BigQuery and dbt cousins.
We deliberately don't collapse the strings to be identical; Titan does the
semantic work, so it's genuine similarity, not string equality.

## 5. Authentic incident payloads

The demo is simulated, declared. Authenticity lives in payload **shape**,
verified against vendor docs:
- Airflow TaskInstance — apache/airflow 2.10.5 `TaskInstanceSchema` (`run_id`
  serializes as `dag_run_id`).
- BigQuery `Job.status.errorResult`/`errors[]` ErrorProto; schema drift =
  `reason:"invalidQuery"`, `"Unrecognized name: … at [line:col]"`.
- dbt `run_results.json` v6 — `status`, `failures`, `unique_id`, `relation_name`.
- CockroachDB hot range — the `/api/v2/ranges/hot/` `hotRangeInfo` struct (there
  is **no** `crdb_internal.hot_ranges` SQL table).

## 6. CockroachDB Agent Skills + ccloud (beat 6)

The CockroachDB-native incident proposes a real skill,
**`analyzing-range-distribution`**, from the official
`cockroachlabs/cockroachdb-skills` repo (hotspot / range-distribution triage via
`SHOW RANGES`), run via the ccloud CLI. The agent uses CockroachDB's own
published expertise to keep its own memory layer healthy.

- https://github.com/cockroachlabs/cockroachdb-skills

## 7. The differentiators (why this isn't "agent remembers incidents")

1. **Trust ledger** — memory about the human-agent relationship, per pattern.
   Autonomy is earned by an approval streak, granted only explicitly, revoked by
   one rejection. The HITL gate is learned, not hardcoded.
2. **Memoryless counterfactual** — one boolean (`memory_enabled`) skips the
   lookup; the same stream floods the queue. Before/after, no infrastructure kill.
3. **Cross-system pollination** — `failure_class` + `applies_to`: one schema-drift
   lesson taught from Airflow, caught in BigQuery and dbt.

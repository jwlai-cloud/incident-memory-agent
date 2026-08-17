# Devpost submission — Mimir (incident-memory-agent)

**Live demo:** https://incident-memory-agent.vercel.app (guided walkthrough at `/demo`)
**Repo:** https://github.com/jwlai-cloud/incident-memory-agent
**Tagline:** *Mimir — consult what survived.*

---

## Inspiration

At 3am, staring at a failed pipeline, the only question that matters is **"have we
seen this before?"** — and that is precisely the moment your tooling is least able to
answer it. The runbook is out of date. The person who fixed it last time is asleep or
gone. The Slack thread with the answer is four months deep.

The hackathon's own framing named the failure mode exactly: *an agent whose memory goes
offline doesn't degrade gracefully, it stops.* An incident-response agent has the
cruellest version of this problem, because the moment you most need "have we seen this
before" is the moment infrastructure is already misbehaving.

So we named it after Mímir — in Norse myth, the severed head Odin preserves *precisely
so its memory outlives the body's death*, and consults before every crisis. Memory that
survives the thing that killed everything around it.

## What it does

**The differentiator: Mimir remembers not just incidents, but the outcomes of its own
judgment — and it earns its autonomy from that record, one pattern at a time.**

An incident triage agent for data platforms (Airflow, BigQuery, dbt, and CockroachDB
itself). One pipeline, on every incident:

1. A signal arrives with an authentic payload — a real Airflow `TaskInstance` failure, a
   real BigQuery `ErrorProto`, a real dbt `run_results.json` entry.
2. `embed.py` reduces it to a normalized natural-language **signature** that leads with
   a *system-agnostic symptom*, then embeds it with AWS Bedrock Titan v2 (512-d).
3. `decide.py` finds the nearest known pattern by cosine distance (`<=>`) against a
   CockroachDB C-SPANN vector index.
4. A **deterministic rule matrix** — not an LLM — picks exactly one action:
   auto-resolve, propose, or escalate.
5. A human responds. `respond.py` writes that response into a **trust ledger** on the
   matched pattern.
6. An incident with no precedent is escalated honestly, and the human's diagnosis is
   promoted into a new pattern — which its cousins in other systems then match.

Three things make it more than recall:

- **A trust ledger.** Approve a proposal unchanged and a counter ticks. At five
  unchanged approvals with zero rejections the agent *asks* to be pre-authorized.
  Autonomy is **earned** by track record, **granted** only by an explicit human click,
  and **revoked** by a single rejection. The human-in-the-loop gate is learned, not
  hardcoded — and `risk_level='high'` (anything touching schema or data) can never
  become autonomous at all.
- **A memoryless counterfactual.** One boolean skips the vector lookup. The same eight
  incidents flood the queue: **100% escalation**. Flip it back: **38%**. Before and
  after memory, on the same stream, with no infrastructure killed for theatre.
- **Cross-system pollination.** A schema-drift lesson taught from one Airflow `KeyError`
  matches the BigQuery `Unrecognized name` and the dbt `column does not exist` — three
  different errors, one root cause, one lesson.

## How we built it

**CockroachDB is the whole memory layer, not a bolt-on.** One store holds the vectors
*and* the structured trust/audit ledger:

- `incident_patterns` — `VECTOR(512)` indexed with **C-SPANN** (`vector_cosine_ops`),
  plus `failure_class`, `applies_to STRING[]`, human-written `root_cause`, and the trust
  columns. Matching is `ORDER BY embedding <=> $1`.
- `agent_decisions` — the audit log, carrying the `memory_enabled` flag that makes the
  counterfactual a live SQL query rather than a claim.
- `runbook` — a VIEW. Team documentation as a side effect of using the tool: always
  current, never hand-edited.
- `usage_counters` — a durable cap on model-invoking endpoints, because the public demo
  URL needed a real gate rather than in-process rate limiting.

**AWS** does two jobs, and only two: **Bedrock Titan Text Embeddings v2**
(`amazon.titan-embed-text-v2:0`, 512-d, normalized) turns signatures into vectors, and
**Bedrock Converse** (Nova Micro) writes the human-readable reasoning *after* the
decision is already made. `decide.handler` is Lambda-shaped. The console runs on Vercel
in **us-east-1**, co-located with the cluster.

**The honest four-tool split**, stated plainly because overstating it would be the easy
lie: *Vector Indexing* is on every incident's decision path. *MCP Server* is
development-side — a coding assistant inspecting schema read-only; the runtime talks
pgwire directly. *ccloud CLI + Agent Skills* apply only to the CockroachDB-native
incident, where a matched hot-range pattern proposes the real
[`analyzing-range-distribution`](https://github.com/cockroachlabs/cockroachdb-skills)
skill. ccloud has no business fixing an Airflow task, and we don't pretend it does.

## Challenges we ran into

**The threshold calibrator confidently produced a number that breaks the demo.** A
pattern matches when cosine distance ≤ a threshold. We wrote a calibrator to derive it
from real embeddings; it measured seeds at 0.000 and un-taught drift at 0.593 and
suggested **0.297**. It was measuring the wrong constraint. The distance that actually
matters is *taught pattern → its cross-system cousin*, and `pollinate_dbt` sits at
**0.321** — above the suggestion. The dbt half of the flagship beat would have silently
shown "no precedent" for an incident the agent had been taught thirty seconds earlier. A
calibrator that measures half the constraints is worse than none. (ADR 0004)

**The self-referential beat was fiction until it wasn't.** Beat 6 proposes running
CockroachDB's own Agent Skill. The simulated payload described a hotspot on
`orders_db.order_events` — fine for a payload that is only *displayed*, fatal for one
whose SQL actually *executes*. It died with `InvalidCatalogName`. Pointing it at
`agent_decisions` — the agent's own append-only log, whose `decided_at` index genuinely
concentrates writes on the newest range — made the beat both work and mean what we'd
claimed. Simulated in its metrics, real in its subject. (ADR 0005)

**Four platform facts the docs don't lead with.** `SHOW RANGES … WITH DETAILS` is
rejected on Cloud Basic (serverless tenants get no node-level internals). CockroachDB
can't infer a placeholder's type inside `ANY()`/`array_append` — the exact line that
grows `applies_to`. `TRUNCATE` is a schema change, taking **68 seconds** on a
handful of rows; `DELETE` took Reset to 2.8s. And `sslrootcert=system` doesn't work,
because Cloud signs with its own CA.

**A code review caught a stored-XSS vector we'd shipped.** `/api/teach` lets a visitor
write pattern text rendered to every other visitor. Five render paths, one root cause,
now escaped and verified with a live payload. The same review caught the README claiming
MCP participates in every decision — an overclaim against our own stated honesty rule.

## Accomplishments we're proud of

Measured on the live cluster (CockroachDB Cloud Basic v26.2.1, us-east-1), not estimated:

| | |
|---|---|
| Memoryless counterfactual | escalation **100% → 38%** across the same 8 signals |
| Cross-system pollination | taught pattern matches BigQuery at **0.72** and dbt at **0.68** similarity |
| `applies_to` growth | `[airflow]` → `+bigquery` → `+dbt`, one lesson |
| Trust ledger | 5th unchanged approval fires the ask; grant sticks; one rejection revokes |
| Beat 6 | the skill returns **live range IDs** for the agent's own `agent_decisions` table |
| Reset latency | 68.6s → **2.8s** in production |
| Decision latency | 13.5s → **1.5s** for 8 concurrent decisions |
| Verification | 9 scripts, each with an offline `--check` that needs no network |

The part we're most pleased with is unglamorous: **the decision is a pure function.**
`classify()` takes (distance, risk, autonomy, revocation, memory flag) and returns one
action, with a truth-table test that runs with no network. The LLM writes prose; rules
decide. That is what makes the autonomy story credible rather than alarming.

## What we learned

**Offline tests prove the logic you thought to write down. Real infrastructure tells you
which constraints you never wrote down.** Every one of our self-checks passed for days
before a cluster existed — and the four findings that would have broken the demo on
camera were all invisible to them.

**A confident wrong number is worse than a missing one.** The threshold calibrator is
the sharpest lesson here: it was *more* dangerous than having no calibration, because it
produced an authoritative-looking value derived from a subset of the real constraints.

**Human-curated memory beats auto-mined memory.** Spotify's data-assistant team found
domain curators accepted only **12.5%** of examples auto-mined from real query history.
We took the same position by construction: `incident_patterns` only grows through a
confirmed human teach-moment, and `root_cause` is always the human's own words — which
is exactly what gets fed to the reasoning call on every future match.

## What's next for Mimir — incident memory that outlives the incident

- **Move embedding calls out of open transactions** — fine at demo scale, wrong under
  real concurrency.
- **CockroachDB CDC as the production trigger**: `monitored_signals` insert → changefeed
  → Lambda, instead of the demo's explicit invoke.
- **Per-session state**, so concurrent reviewers don't share one demo.
- **Real adapters** behind the existing interface. The dashboard, vector search, trust
  ledger and audit log are real; the incident stream that feeds them is generated, and
  each incident exposes its stored row so that claim is checkable rather than asserted.
- **Trust decay**: a pattern unconfirmed for months should lose standing, not coast on
  an old streak.

## Built with

`cockroachdb` · `cockroachdb-vector-search` · `cockroachdb-cloud` · `amazon-bedrock` ·
`amazon-titan` · `amazon-nova` · `aws-lambda` · `python` · `flask` · `psycopg3` ·
`vercel` · `sql` · `airflow` · `bigquery` · `dbt`

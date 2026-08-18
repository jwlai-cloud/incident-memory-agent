# Design doc — incident memory agent ("Mimir")

Built for the **CockroachDB × AWS Hackathon** ("Build with Agentic
Memory"). Repo name stays descriptive (`incident-memory-agent`); the
README tagline can carry the brand: *Mimir — consult what survived.*
(Norse mythology: the severed head Odin preserves precisely so its
memory outlives the body's death, consulted before every crisis.)

## One-sentence pitch

An incident triage agent for data platforms (Airflow, BigQuery, dbt,
and CockroachDB itself) whose memory of every past incident — and of
how much the human trusts its judgment — persists in CockroachDB,
so a lesson taught once, anywhere, is instantly reusable everywhere,
and survives any failure.

## The three differentiating ideas (do not cut these)

### 1. Trust ledger — memory about the human-agent relationship

Everyone will submit "agent remembers incidents." This project also
remembers *outcomes of the agent's own judgment*, per pattern:

- Human approves the agent's proposal unchanged → `approved_unchanged_count += 1`
- Human modifies before approving → `modified_count += 1`
- Human rejects → `rejected_count += 1`

When a low-risk pattern crosses a threshold (e.g. 5 unchanged
approvals, 0 rejections), the agent *asks*: "I've proposed this fix 5
times; you approved unchanged every time. Pre-authorize this pattern?"
Autonomy is granted only by explicit human action
(`autonomy_granted = true`), is visible in the runbook, and one
rejection after grant auto-revokes it (`autonomy_revoked_at`).

The HITL gate is therefore **learned, earned, and revocable** — not
hardcoded. This is the submission's strongest claim to novel "Agentic
Memory Design": memory about trust, not just about incidents.

### 2. Memoryless counterfactual — the villain demo

Do NOT demo resilience by killing infrastructure. Demo the
*counterfactual*: a feature flag (`memory_enabled = false` on
decisions) that skips the vector lookup entirely. Same incident
stream, every incident escalates, the review queue floods. Flip
memory on: the queue melts, precedents get cited. "This is on-call
life without persistent memory" — the hackathon's own tagline
("an agent whose memory goes offline doesn't degrade gracefully, it
stops") dramatized as a before/after, for the cost of one boolean.

The `memory_enabled` column on `agent_decisions` makes the comparison
queryable live on camera: escalation rate with vs. without memory.

### 3. Cross-system pattern pollination — `applies_to` is the star

The central demo incident family is **schema drift**: an upstream
schema change silently breaking a downstream assumption. It fires
first in Airflow (task failure), gets taught once, then gets caught
in BigQuery (query failure) and dbt (test failure) — one lesson,
three systems. `failure_class` is the generalization axis;
`applies_to` accumulates the systems a pattern has been confirmed in.

This quietly answers "why embeddings, why not rules?" — rule matchers
don't cross-pollinate; behavioral signatures of failures rhyme across
platforms in embedding space.

## Diagnose-and-improve vs. self-healing (settled)

Primarily a **diagnose-and-improve** agent (memory getting better is
the judged thing), with a bounded, HITL-gated action layer:

- The agent **proposes** the exact action + reasoning + cited
  precedent; a human approves; then it executes and logs the outcome.
- `risk_level = 'high'` patterns (anything touching schema or data)
  ALWAYS get full human diagnosis regardless of match confidence.
- Only `risk_level = 'low'`, `autonomy_granted = true` patterns may
  auto-execute — and only after the trust ledger earned it on camera.

"The agent auto-fixes everything" is a production-readiness red flag
to a technical judge. "The agent knows what it's allowed to decide
alone, and how it earned that" is the credible version.

## The honest tool split (do not blur this in submission text)

> **Outcome, recorded after build.** This section was the *design* intent for four
> tools. Two of them did not survive contact: `ccloud auth login` is
> interactive-browser and cannot run in a serverless function, so the deployed
> demo runs the skill's diagnostic over pgwire and the ccloud branch was never
> executed; the managed MCP endpoint was simply never wired. The submission
> claims **two** tools — Vector Indexing and Agent Skills. Applying this
> section's own rule to itself is the whole point of it existing.

- **Distributed Vector Indexing** — load-bearing for every incident, any source
  system. The core memory.
- **MCP Server** — intended as the analyst/development interface. Not wired; not
  claimed.
- **Agent Skills Repo** (and, as designed, **ccloud CLI**) — load-bearing specifically
  for the CockroachDB-native incident beat (see DEMO_SCRIPT beat 6).
  ccloud manages CockroachDB clusters; it has no natural role fixing
  an Airflow task. The Agent Skills repo encodes *CockroachDB*
  operational expertise (triaging live SQL activity, backup/DR
  posture, production readiness) — it does not diagnose BigQuery.
  Say this split plainly in the submission; don't imply all four
  tools uniformly cover everything.

### Beat 6 design: the CockroachDB-native incident

This is where all four tools are simultaneously real:

1. A simulated CockroachDB-native signal fires — e.g. a hot range /
   contention spike on the memory cluster itself
   (`source_system = 'cockroachdb'`, `signal_type = 'hot_range'`).
2. The agent embeds and matches it like any other incident
   (Vector Indexing).
3. The matched pattern's `remediation_channel = 'ccloud_skill'` and
   `skill_ref` names the relevant Agent Skill from the public
   `cockroachlabs/cockroachdb-skills` repo. For the write-hotspot
   incident the skill is **`analyzing-range-distribution`** (hotspot /
   range-distribution triage via `SHOW RANGES`); the live-activity
   alternate is `triaging-live-sql-activity`. Store the bare slug as
   `skill_ref`.
4. The agent proposes: "run this skill via ccloud" — showing the
   exact command it intends, JSON output mode.
5. Human approves → agent executes via **ccloud CLI**, captures the
   JSON result into the decision's reasoning, resolves.
6. The self-referential kicker for the video: *the agent is using
   CockroachDB's own published expertise to keep its own memory
   layer healthy.* Memory defending itself.

If live ccloud execution against the demo cluster proves flaky on
camera, the fallback is showing the exact proposed command + a
pre-recorded execution — but attempt live first; JSON-mode ccloud
output rendered in the UI is a strong moment.

## Why CockroachDB (the one-paragraph answer for the README)

An incident-response agent's memory going down *during* an incident
is the worst possible failure mode for this use case — the moment you
most need "have we seen this before" is precisely the moment
infrastructure is misbehaving. Transactional freshness means a
pattern taught from an Airflow incident is instantly matchable for a
BigQuery one — no replication lag, no reindex. And one store holds
the vectors AND the structured trust/audit ledger — no separate
vector DB + operational DB sync problem. Postgres+pgvector can do a
single-node version; it cannot make the freshness-under-failure
claim.

## Simulated incidents — legitimacy and realism

Simulated is fine here in a way it wasn't for a fraud demo: nobody
expects hackathon access to a real production fleet's outage history.
What matters is payload authenticity — match real Airflow
task-failure exception shapes, real BigQuery job-error JSON
structures, real dbt test-result schemas. `scripts/simulate_incidents.py`
generates 5–8 incidents across systems with explicit timing control
so the demo is rehearsable, never left to chance.

## Adapter interface (production-readiness signal)

Monitoring integration goes behind a small adapter interface
(`AirflowAdapter`, `BigQueryAdapter`, `DbtAdapter`,
`CockroachDBAdapter`). In the demo they read from the simulated
signal stream; the interface existing shows the design generalizes
past the demo. Do not fake more than this — the README should be
plain that demo signals are simulated.

## Design lineage (for "What we learned" in the submission)

The human-gated memory-write design is validated by production
experience elsewhere: Spotify's data assistant team found domain
curators accepted only **12.5%** of examples auto-mined from real
query history — the rest taught wrong patterns
(engineering.atspotify.com, June 2026, "Encoding Your Domain
Expert"). Same principle here: `incident_patterns` only grows through
a confirmed human teach-moment; `root_cause` is the human's own
written rationale (their "worked example"), fed into the reasoning
call whenever the pattern matches. Cite Spotify for the *principle*
(human-curated beats auto-mined), not as prior art for the
implementation — their stack and problem are different.

## Out of scope (do not reintroduce)

- Multi-node kill-a-node infrastructure demo (the memoryless
  counterfactual replaces it, cheaper and more dramatic).
- Autonomous remediation of high-risk actions under any circumstances.
- Real TrafficGuard data, logic, or incident history — this is a
  fresh public build; domain familiarity informs it, proprietary
  material does not.
- The previous fraud-detection direction (see repo history /
  jwlai-cloud/fraud-pattern-memory-agent if it was pushed) — fully
  superseded by this design.

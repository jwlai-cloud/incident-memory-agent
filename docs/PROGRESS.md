# Progress log

*Running log. Update at the end of every session, not just milestones.*

## Status: end-to-end working against real infrastructure

Every beat runs live against a CockroachDB Cloud Basic cluster (v26.2.1,
us-east-1) with real Bedrock Titan embeddings and Nova reasoning. The demo
console at `app.py` drives all seven beats; all nine scripts keep passing their
offline `--check`.

## Done

- [x] **Repo layout + hygiene** — `docs/`, `schema/`, `scripts/`; `CLAUDE.md`
      and `.claude/` gitignored; Python ignores; `.env.example` connection
      contract.
- [x] **`scripts/simulate_incidents.py`** — 8-incident cast, authentic payload
      shapes verified against vendor docs, deterministic injection order,
      `--inject` / dry-run / `--check`.
- [x] **`scripts/embed.py`** — signature builder + Bedrock Titan v2 embedding,
      shared by seed + live. Cross-system drift trio clusters; `seed_1` ≡
      `trust_repeat`.
- [x] **`schema/schema.sql`** — corrected the vector index to
      `vector_cosine_ops` (was defaulting to L2).
- [x] **`scripts/seed_patterns.py`** — 4 pre-loaded patterns, human root_cause/
      resolution, `seed_1` preloaded at 4 unchanged approvals, real `skill_ref`
      (`analyzing-range-distribution`).
- [x] **`scripts/decide.py`** — deterministic decision matrix, cosine `<=>`
      top-k, `memory_enabled` counterfactual, Bedrock Converse reasoning
      (env-configurable model + template fallback).
- [x] **`scripts/respond.py`** — trust ledger (approve/modify/reject), earned
      autonomy grant, auto-revoke; in-SQL atomic updates.
- [x] **`scripts/teach.py`** — escalation → promoted pattern; closes the
      teach→pollinate loop.
- [x] Living docs: `ARCHITECTURE.md`, `PROGRESS.md`, `LEARNING.md`, ADR 0001-0003;
      README rewrite; interactive tutorial artifact; `BLOG.md`.
- [x] **`scripts/reset_demo.py`** — truncate + re-seed + re-inject for repeatable
      runs; `--plan`; `BACKUP`/`RESTORE` video fallback documented in the docstring.
- [x] **`scripts/smoke_test.py`** — end-to-end runner + threshold calibrator.
      `--calibrate` prints nearest-pattern distances + a suggested
      `MATCH_MAX_DISTANCE`; `--e2e` runs the counterfactual live. Offline `--check`
      green; live run pending the cluster.
- [x] **`scripts/ccloud_wrapper.py`** (step 7) — beat-6 execution. Renders the
      `analyzing-range-distribution` skill's read-only leaseholder-distribution SQL
      (json_agg-wrapped) for the hot table, runs via `ccloud cluster sql` (or psycopg
      fallback), captures JSON into the decision. Mutation guard + `--check` green;
      `ccloud` subprocess path pending an installed/authed CLI + cluster.

- [x] **Live infrastructure** — CockroachDB Cloud Basic (AWS us-east-1, v26.2.1),
      `feature.vector_index.enabled=true`, schema + C-SPANN cosine index applied.
      Bedrock verified with real Titan and Nova calls; $200 credits, ~$0 used.
- [x] **Threshold calibrated** — `MATCH_MAX_DISTANCE = 0.45` from measured
      distances. The pre-teach-only calibration suggested 0.297, which would have
      silently broken the dbt cross-system match (0.321). See ADR 0004.
- [x] **Deployed** — https://pi5qzv7wstff2tdkq73odywisq0jxnwt.lambda-url.us-east-1.on.aws
      (AWS Lambda container image behind a Function URL, us-east-1, co-located with the
      cluster). Public, no login. Cluster CA supplied via
      `COCKROACH_CA_PEM`; model-invoking endpoints capped by a durable counter in
      CockroachDB (500/day global, 100/day per IP).
- [x] **Step 9 — demo console** (`app.py` + `templates/index.html`): guided
      7-beat rail, incident timeline, trust/runbook panel, live-SQL proof panel.
      Driven end-to-end with Playwright, zero console errors.

## Next (priority order)

Submission-blocking items only. Everything in the build order is done.

1. **Upload the demo video** (`capture/demo/mimir-demo.mp4`, 2:53) to YouTube or Vimeo
   as **public or unlisted** — a private video is unplayable for judges — and paste the
   URL into Devpost. Human-only step.
2. **Paste `docs/SUBMISSION.md`** into the Devpost story fields; upload the six gallery
   images. Human-only step.
3. **AWS budget action** on the Bedrock key — the slow backstop under the durable
   in-database cap. Console-only; the `mimir-bedrock` IAM user cannot create it.
4. **Step 8 — MCP wiring** is development-side only and stays that way: the cluster's
   Connect dialog gives a managed MCP endpoint (`https://cockroachlabs.cloud/mcp`,
   header `mcp-cluster-id`) used by a coding assistant for read-only schema inspection.
   The runtime talks pgwire directly. Stated plainly in README and SUBMISSION rather
   than implied to be on the decision path.

## Known gaps, declared

- **Demo state is global.** Reset / decide / teach / respond mutate shared rows, so two
  concurrent reviewers share one run and each browser keeps its own rail progress. A
  reviewer arriving mid-run sees a half-finished board. Scoping state to a session is
  the single highest-value remaining fix for a publicly judged demo; it is listed under
  "What's next" in SUBMISSION.md rather than quietly omitted.
- **Embedding calls happen inside open transactions.** Fine at demo scale, wrong under
  real concurrency.

## Done since the cluster came up

- Operator dashboard is the primary view at `/`; the guided console moved to `/demo`.
- Per-incident provenance: every row opens its real `monitored_signals` record.
- Incident rows are keyboard-operable (`role=button`, `aria-expanded`, delegated
  click/keydown) — the drawer holds the decision controls, so this was an access bug,
  not a nicety.
- The engineering walk-through is served from the app at `/tutorial`. It previously
  pointed at a private hosted artifact URL that only its author could open.
- Demo video recut to 12 beats at 2:53, with AWS/CockroachDB service names as on-screen
  overlays rather than narration alone.

## Open questions

- **Cluster longevity.** Basic's free tier recurs monthly (the $400 trial credit
  expires 2026-08-24), so the demo URL should survive judging — but confirm the
  cluster isn't paused for inactivity before submitting.

## Constraints discovered on the real cluster

- `SHOW RANGES ... WITH DETAILS` is **rejected on Cloud Basic** (serverless
  tenants get no node-level range internals): `rpc error ... connection reset`.
  The beat-6 diagnostic uses the tier-compatible per-index range distribution.
- CockroachDB cannot infer a placeholder's type inside `ANY()` / `array_append`
  — needs an explicit `::STRING` cast (`IndeterminateDatatype` otherwise).
- `TRUNCATE` is a schema change (new descriptor via a job): 68.6s on Basic for a
  handful of rows. `DELETE` is ~1s.
- CockroachDB Cloud signs with its own CA, so `sslrootcert=system` fails; the CA
  must be supplied explicitly (here via `COCKROACH_CA_PEM`).

## Decisions on record (see `docs/adr/`)

- 0001 — CockroachDB as the single memory + vector + ledger store.
- 0002 — Deterministic decision, LLM for prose only.
- 0003 — dbt schema-drift manifests as a model build error, not a test failure.
- 0004 — Match threshold calibrated to 0.45 against real embeddings.
- 0005 — Beat 6 targets the agent's own memory tables.

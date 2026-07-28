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
- [x] **Step 9 — demo console** (`app.py` + `templates/index.html`): guided
      7-beat rail, incident timeline, trust/runbook panel, live-SQL proof panel.
      Driven end-to-end with Playwright, zero console errors.

## Next (priority order)

1. **Deploy the console** to a public URL (the submission's "working demo URL").
   Flask dev server is local-only; needs a WSGI host + the connection string as a
   platform secret.
2. **Step 8 — MCP wiring.** The cluster's Connect dialog gives a managed MCP
   endpoint (`https://cockroachlabs.cloud/mcp`, header `mcp-cluster-id`).
   Dev-side use satisfies the requirement per the session FAQ.
3. **Record the demo video** (<3 min) following `DEMO_SCRIPT.md`; the console's
   beat rail is the shot list.
4. Submission writeup + regenerate `architecture.svg` for this design.

## Open questions

- **Hosting.** Where the console gets deployed, and how `COCKROACH_URL` is
  injected as a secret there.
- **Cluster longevity.** Basic's free tier recurs monthly (the $400 trial credit
  expires 2026-08-24), so the demo URL should survive judging — but confirm the
  cluster isn't paused for inactivity before submitting.
- `incident-memory-agent.zip` is a tracked repo-in-repo — drop before submission.

## Constraints discovered on the real cluster

- `SHOW RANGES ... WITH DETAILS` is **rejected on Cloud Basic** (serverless
  tenants get no node-level range internals): `rpc error ... connection reset`.
  The beat-6 diagnostic uses the tier-compatible per-index range distribution.
- CockroachDB cannot infer a placeholder's type inside `ANY()` / `array_append`
  — needs an explicit `::STRING` cast (`IndeterminateDatatype` otherwise).

## Decisions on record (see `docs/adr/`)

- 0001 — CockroachDB as the single memory + vector + ledger store.
- 0002 — Deterministic decision, LLM for prose only.
- 0003 — dbt schema-drift manifests as a model build error, not a test failure.
- 0004 — Match threshold calibrated to 0.45 against real embeddings.
- 0005 — Beat 6 targets the agent's own memory tables.

# Progress log

*Running log. Update at the end of every session, not just milestones.*

## Status: core complete, not yet run against real infra

The full memory + decision core is code-complete and offline-verified (every
script has a `--check` self-check that passes with no network/DB). Nothing has
run against a live CockroachDB cluster or AWS Bedrock yet.

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

## Next (priority order)

1. **Stand up CockroachDB Cloud + AWS creds** (in progress — user provisioning).
2. **Run `smoke_test.py --calibrate`** → set `MATCH_MAX_DISTANCE` from real
   embeddings (seeds match, `novel_airflow` doesn't). Then `--e2e` for the
   counterfactual. This is now one command each; exercises all write paths.
3. Step 8 — MCP wiring (dev-side inspection satisfies the requirement per the
   session FAQ; runtime analyst chat is optional polish).
4. Step 9 — minimal UI: feed, review queue, trust/runbook view, memory toggle,
   guided beat controls, "Backed by CockroachDB" proof panel.

## Open questions

- `MATCH_MAX_DISTANCE` value — deferred until real embeddings exist (item 3).
- Reasoning model — default Nova Micro; confirm Bedrock access/cost on the real
  account (FAQ: Bedrock Claude may not be free; DeepSeek/Nova are cheap).
- `incident-memory-agent.zip` is a tracked repo-in-repo — probably drop before
  submission (not for a public repo).

## Decisions on record (see `docs/adr/`)

- 0001 — CockroachDB as the single memory + vector + ledger store.
- 0002 — Deterministic decision, LLM for prose only.
- 0003 — dbt schema-drift manifests as a model build error, not a test failure.

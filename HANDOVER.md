# Handover — build order and submission checklist

Everything here is scaffolding + docs; no real CockroachDB or AWS
calls made yet. This project supersedes the earlier fraud-pattern
direction entirely.

## 1. Stand up CockroachDB

1. CockroachDB Cloud cluster — standard managed cluster is enough.
2. Run `schema/schema.sql` (three tables + the `runbook` view).
3. Set `COCKROACH_URL` (see `.env.example`).
4. From the Cloud console, grab: the MCP Server config snippet, and
   ccloud CLI auth set up with a service account whose RBAC is
   read-mostly (least privilege — this is a talking point, not just
   hygiene).
5. Clone the public cockroachdb-skills repo locally; identify 1–2
   skills relevant to the beat-6 incident (live SQL activity triage /
   hot range diagnosis territory) and record their exact names in
   `docs/DESIGN.md` beat-6 section.

## 2. Build order

1. **`scripts/simulate_incidents.py`** — generates the incident cast
   from `docs/DEMO_SCRIPT.md` with authentic payload shapes:
   - Airflow: real task-instance failure JSON shape (exception class,
     try_number, duration vs. historical mean)
   - BigQuery: real job-error JSON structure (reason, location,
     bytesProcessed anomaly vs. baseline)
   - dbt: real test-result artifact shape (test name, status,
     failures count, relation)
   - CockroachDB: hot-range-style signal (range id, QPS skew,
     replica distribution)
   Explicit injection-order control; no randomness in the demo path.
2. **`embed.py`** — incident signature dict → Bedrock Titan embedding.
   Signature = (source_system, signal_type, normalized payload
   features, deviation magnitude). One shared function for seeding
   and live decisions.
3. **`seed_patterns.py`** — seeds `seed_1..3` patterns with
   human-written root_cause/resolution text.
4. **`decide.py`** (Lambda handler body) — signal → embed →
   cosine_distance top-k against `incident_patterns` → decision:
   - confident match + `risk_level='low'` + `autonomy_granted` →
     auto-execute path
   - confident match otherwise → **propose** (await human)
   - no confident match → **escalate**
   - always honor `memory_enabled` flag (counterfactual mode skips
     the lookup and always escalates)
   Write every decision to `agent_decisions`.
5. **`respond.py`** — the human-response endpoint: approve-unchanged /
   modify / reject. Updates the trust ledger counters; grants
   autonomy only via the explicit pre-authorization action; one
   rejection after grant sets `autonomy_revoked_at`.
6. **`teach.py`** — the escalation-resolution path: human writes
   root_cause + resolution, picks risk_level and remediation_channel,
   pattern inserted with `source='promoted'`.
7. **ccloud execution wrapper** — for `remediation_channel='ccloud_skill'`
   proposals: render the exact command, execute on approval, capture
   JSON output into the decision record.
8. **MCP wiring** — config snippet from step 1.4 into the analyst
   chat backend.
9. **Minimal UI** — live incident feed, review queue, trust/runbook
   view, analyst chat, and the memory on/off toggle for the
   counterfactual beat. Polling is fine.

## 3. Submission checklist

- [ ] 2+ CockroachDB tools — this project uses all four; describe the
      honest split (see DESIGN.md) in the write-up
- [ ] 1+ AWS service — Bedrock + Lambda
- [ ] Public repo, OSS license visible in the About section
- [ ] README: setup, run, which tools used and HOW (what the agent
      actually did with each — the rules ask this explicitly)
- [ ] Architecture diagram (docs/architecture.svg — regenerate for
      this design before submitting; the current one is inherited)
- [ ] Demo video < 3 min, YouTube/Vimeo public
- [ ] Working demo URL
- [ ] Built fresh within the submission window (June 30 – Aug 18) —
      true by construction
- [ ] Deadline **Aug 18, 2026** — submit days early
- [ ] Optional but cheap: feedback on the CockroachDB tools (the
      rules invite it; you'll have real opinions by then)

## 4. Before recording

Run everything from a clean checkout once, end to end, including the
counterfactual toggle and the ccloud beat. The beat-6 live execution
is the only part with real external flakiness — have the fallback
recording ready.

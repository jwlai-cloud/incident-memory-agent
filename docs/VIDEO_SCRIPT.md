# Demo video — shot-by-shot script

**Target:** 2:50, hard cap 3:00. **Source:** https://incident-memory-agent.vercel.app
**Capture:** Playwright driving the live production console (`capture/` — gitignored).

Latency is measured in production, so the cut is built around real waits rather than
guesses: Reset **2.8s**, decide-all memory-off **0.7s**, memory-on **1.5s**. Nothing here
needs speeding up or faking; the only long beat is the teach form, which is human typing.

---

## Beat 0 — 0:00–0:12 · The problem

**Visual:** the architecture diagram (`docs/diagrams/architecture.html`), "Decision path"
guided view playing.

> "Three in the morning, a pipeline is down, and the only question that matters is:
> *have we seen this before?* That's exactly when your runbook is stale and the person
> who fixed it last time is asleep."

**Cut on:** the words "seen this before" → hard cut to the console.

## Beat 1 — 0:12–0:20 · What you're looking at

**Visual:** console at rest, 8 incidents in the stream, memory rail empty.

> "This is Mimir. Eight incidents across Airflow, BigQuery, dbt, and CockroachDB itself.
> Its memory lives in CockroachDB — and so does its record of how much I trust it."

**Action:** click **Reset to baseline** (2.8s — no dead air, it lands mid-sentence).

## Beat 2 — 0:20–0:45 · The villain: no memory

**Visual:** click **Run with memory OFF**. Every row turns red. Rail fills to 100%.

> "First, without memory. Same eight incidents. The agent has no precedent for any of
> them, so every single one escalates to a human. One hundred percent. This is on-call
> before the agent remembers anything."

**Hold** on the 100% for a beat. Let it be uncomfortable.

## Beat 3 — 0:45–1:05 · Memory on

**Visual:** click **Run with memory ON**. Rows flip to blue "propose". Rail drains to 38%.

> "Now the same stream, with memory. Five of the eight match a known pattern instantly —
> cosine search over a vector index — and come back with a proposed fix and a cited
> precedent. A hundred percent becomes thirty-eight."

**Callout overlay:** `100% → 38%` on the rail as it animates.

## Beat 4 — 1:05–1:30 · Honest escalation, then teaching

**Visual:** click the red `novel_airflow` row → drawer opens showing "no precedent".

> "Three still escalate — and this is the important part. The agent doesn't guess. It's
> never seen this schema-drift failure, so it says so."

**Action:** click **Teach the new pattern**. Show the root cause text.

> "So I teach it, in my own words. That sentence is what the agent will cite next time."

## Beat 5 — 1:30–2:00 · The money shot: one lesson, three systems

**Visual:** click **Pollinate to BigQuery + dbt**. Both rows change to
"matched upstream-schema-drift-dropped-column". Runbook `applies_to` grows to three pills.

> "Now watch. A BigQuery error and a dbt error — completely different vendors, completely
> different formats. Both match the pattern I taught thirty seconds ago from an *Airflow*
> failure. One lesson, three systems."

**Action:** open the `pollinate_bq` drawer, highlight the reasoning text.

> "And it cites where it learned it: *similar to previous issues in airflow*. Note it
> still escalates — schema changes are high-risk, so a human always confirms. Recognition
> isn't permission."

**Callout:** underline `[airflow, bigquery, dbt]` in the runbook.

## Beat 6 — 2:00–2:20 · Memory defending itself

**Visual:** click **Run the CockroachDB skill**. JSON appears with live range IDs.

> "One incident is CockroachDB's own. A write hotspot — on the agent's own decision log.
> It proposes running CockroachDB's published Agent Skill, and those are real range IDs
> from the live cluster. The agent is using CockroachDB's own expertise to keep its own
> memory healthy."

## Beat 7 — 2:20–2:40 · Earned autonomy

**Visual:** click **Earn autonomy**. The "grant autonomy" button appears in the runbook.

> "Last piece. This pattern has now been approved unchanged five times, so the agent asks
> to be pre-authorized. Autonomy is earned by track record, granted only by me — and one
> rejection takes it away. The human-in-the-loop gate is learned, not hardcoded."

**Action:** click **grant autonomy** → row flips to `autonomous`.

## Beat 8 — 2:40–2:50 · Close

**Visual:** scroll the "Backed by CockroachDB" panel — live SQL and results.

> "Every number you just saw is a live query against CockroachDB. Vector search, the trust
> ledger, and the audit log — one store, so memory survives the incident it's remembering.
> That's Mimir."

**End card:** URL + repo + "Consult what survived."

---

## Recording rules

- **Rehearse from a Reset.** The demo mutates state; a half-run looks broken on camera.
- **The counterfactual must show the same incident IDs** in beat 2 and beat 3, or it reads
  as staged. Don't crop the ID column.
- **Never show more than ~6 items in the queue.** The point is that the human sees almost
  nothing, not that they review everything.
- **Beat 6 fallback:** if the live skill call is slow, the JSON is already captured in the
  decision record — show that instead of waiting. Attempt live first.
- **Don't narrate the rate limit or the daily cap.** True, but not the story.
- **Say "simulated incidents" once**, in beat 1 or the end card. Declared, not hidden.

## Consistency check before publishing

The same three numbers must appear in the video, `docs/SUBMISSION.md`, and the README:
**100% → 38%**, **0.72 / 0.68** similarity, **three systems**. If any of them changes,
re-run `smoke_test.py --calibrate` and update all three together.

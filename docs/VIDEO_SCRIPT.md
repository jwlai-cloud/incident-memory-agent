# Demo video — shot-by-shot script

**Runtime:** 2:53 (hard cap 3:00). **Source:** https://incident-memory-agent.vercel.app —
the operator dashboard at `/`, not the guided console at `/demo`.
**Capture:** Playwright driving live production (`capture/`, gitignored):
`node narrate.mjs && node capture.mjs && node assemble.mjs`.

Narration is generated first, and the capture holds each scene for exactly its narration
slot — so this file's per-beat times come from `capture/demo/vo/durations.json` rather
than from a guess. The cut records at **3:43** and is compressed **1.28×** to land under
the cap; both tracks are slowed together, so nothing desyncs.

Latency is measured in production, so the beats are built around real waits: Reset
**2.8s**, decide-all memory-off **0.7s**, memory-on **1.5s**. Nothing is sped up or faked.

**Control labels below are the dashboard's actual `button.rstep` titles** in the demo
rail (opened once by `#railtoggle` at the top of the run). They are what `capture.mjs`
clicks; if you rename a button, this file and `capture.mjs` both need the new name.

---

## Beat 01 — hook · 12.8s

**Visual:** the dashboard at rest. No action.

> "Three in the morning. A data pipeline is down, and the only question that matters is:
> have we seen this before? That's the moment your runbook is stale and whoever fixed it
> last time is asleep."

## Beat 02 — what you're looking at · 19.2s

**Action:** `Reset` · **Highlight:** `.simchip` — the live-vs-demo-stream chip

> "So this is what the on-call engineer actually looks at. Failures from Airflow,
> BigQuery, dbt, and CockroachDB itself, in one queue. The incident stream is generated
> for this demo — everything downstream of it is live: the vector search, the decisions,
> the ledger. Every row will show you its database record."

## Beat 03 — the premise · 13.8s

**Visual:** no action. The hackathon's own framing, stated plainly.

> "And here's the hard part. The moment you most need to remember something is the moment
> your infrastructure is already misbehaving. An agent whose memory goes offline doesn't
> degrade gracefully. It stops."

## Beat 04 — the villain · 10.1s

**Action:** `Memory OFF` · **Highlight:** `#systems` — every source turns red

> "So, first — without memory. The agent has no precedent for anything. Every source turns
> red, and all eight incidents escalate to a human. One hundred percent."

## Beat 05 — memory on · 20.6s

**Action:** `Memory ON` · **Highlight:** `#chart` — the 100% → 38% panel

> "Same eight incidents, memory on. Each incident is embedded by Amazon Bedrock — Titan
> Text v2 — and matched by cosine search over CockroachDB's vector index. Most of them hit
> a known pattern instantly, and come back with a proposed fix and a cited precedent. A
> hundred percent becomes thirty-eight."

## Beat 06 — the receipts · 11.6s

**Action:** open the first queue row → `Show the record`, scroll
**Highlight:** `.prov:not([hidden])` — the actual `monitored_signals` row

> "And you don't have to take my word for any of it. Every incident opens onto its actual
> database row — the identifier, the timestamp, and the raw upstream error exactly as it
> was stored."

## Beat 07 — honest escalation, then teaching · 13.8s

**Action:** scroll to top, close the drawer, `Teach`

> "This one is different. The agent has never seen it, and it doesn't guess — it says so,
> and it escalates. I diagnose it once, in my own words. That sentence becomes the thing
> it cites next time."

## Beat 08 — one lesson, three systems · 23.9s

**Action:** `Pollinate`, scroll `#patterns` into view
**Highlight:** `#patterns .pat:has(.pill.new)` — `applies_to` grown to three

> "Now watch. A BigQuery query failure, and a dbt model error — different vendors,
> completely different error formats. Both match the pattern I taught thirty seconds ago
> from an Airflow task. One lesson, three systems — and you can see the pattern grow to
> cover all three. It still escalates, though: schema changes are high risk, so a human
> confirms. Recognition isn't permission."

## Beat 09 — the stack, and why this store · 36.2s

**Visual:** `docs/diagrams/architecture.html` overlaid across this window by
`assemble.mjs`. The longest beat, and the only one that is not the live app.

> "The shape is small. Bedrock embeds, a Lambda-shaped function classifies, CockroachDB
> remembers. And the decision is a pure rule matrix, not a model — Bedrock's Nova writes
> the explanation afterwards, it never picks the action. So why CockroachDB, and not
> Postgres with pgvector? Honestly, Postgres does this on one node. The difference is what
> happens when the node you're asking is the one that's on fire. And the trust ledger has
> to be transactional with the vector it describes — split those across two systems and
> you can grant autonomy that was never earned."

## Beat 10 — scale · 11.8s

**Visual:** scroll to top. No action.

> "Eight incidents today; a real platform has thousands across many teams. That's where
> this gets more valuable, not less — no replica lag between where a lesson was learned
> and where it's needed."

## Beat 11 — memory defending itself · 13.4s

**Action:** `CockroachDB skill` — live range IDs come back

> "One of these is CockroachDB's own — a write hotspot on the agent's decision log. It
> proposes running CockroachDB's published Agent Skill, and those are real range IDs from
> the live cluster. The memory is diagnosing itself."

## Beat 12 — earned autonomy · 13.2s

**Action:** `Earn autonomy`, then `grant autonomy` · **Highlight:** `#patterns` — the ask

> "Last piece. This pattern has been approved unchanged five times, so the agent asks to
> be pre-authorised. Autonomy is earned by track record, granted only by me, and one
> rejection takes it away."

## Beat 13 — close · 13.6s

**Action:** open `details.hood` · **Highlight:** `details.hood` — live SQL and results

> "Every number here is a live query against CockroachDB, every vector a live call to
> Bedrock in us-east-one. One store, so the memory outlives the thing that broke.
> That's Mimir."

---

## Recording rules

- **Rehearse from a Reset.** The demo mutates state; a half-run looks broken on camera.
- **The counterfactual must show the same incident IDs** in beats 04 and 05, or it reads
  as staged. Don't crop the asset column.
- **Beat 11 fallback:** if the live skill call is slow, the JSON is already captured in
  the decision record — show that instead of waiting. Attempt live first.
- **Don't narrate the rate limit or the daily cap.** True, but not the story.
- **Frame it accurately, early.** The incident *stream* is generated for the demo; the
  dashboard, vector search, decisions and ledger are live. Say that once, near the start,
  and let the record view carry the proof — don't label the product "simulated".
- **Name AWS out loud, not only in the docs.** This is a CockroachDB **×AWS** challenge
  and a judge watching the video may never open the repo. Bedrock/Titan on beat 05,
  Bedrock + the Lambda shape + "the model never picks the action" on beat 09, Bedrock
  again on beat 13. The first cut named neither AWS nor Bedrock once in thirteen beats —
  a scoring hole invisible from the written artifacts alone.
- **Keep compression under ~1.3×.** `assemble.mjs` fits the timeline to the cap
  automatically, but past roughly 1.3× the voice starts to read as processed. If a rewrite
  pushes narration over ~215s, cut a beat rather than let the ratio climb.

## Consistency check before publishing

The same three numbers must appear in the video, `docs/SUBMISSION.md`, and the README:
**100% → 38%**, **0.72 / 0.68** similarity, **three systems**. If any of them changes,
re-run `smoke_test.py --calibrate` and update all three together.

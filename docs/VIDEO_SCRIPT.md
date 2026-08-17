# Demo video — shot-by-shot script

**Runtime:** 2:53 (hard cap 3:00) · **12 beats**
**Source:** https://incident-memory-agent.vercel.app — the operator dashboard at `/`,
not the guided console at `/demo`.
**Capture:** Playwright driving live production (`capture/`, gitignored):
`node narrate.mjs && node capture.mjs && node assemble.mjs`.

Narration is generated first and the capture holds each scene for exactly its narration
slot, so the per-beat times below come from `capture/demo/vo/durations.json` rather than
from a guess. The cut records at **3:43** and is compressed **1.28×** to land under the
cap; both tracks are slowed together, so nothing desyncs.

Latency is measured in production, so the beats are built around real waits: Reset
**2.8s**, decide-all memory-off **0.7s**, memory-on **1.5s**. Nothing is sped up or faked.

**Control labels below are the dashboard's actual `button.rstep` titles** in the demo rail
(opened once by `#railtoggle` at the top of the run). They are what `capture.mjs` clicks;
rename a button and this file and `capture.mjs` both need the new name.

**Beat ids keep their original numbers.** There is no `03` — it was a static concept beat,
cut for the reason in the recording rules below. Renumbering would rename every
`demo/vo/*.mp3` for no gain.

Three overlay layers, all built in `assemble.mjs`:

| Layer | Where | What it carries |
|---|---|---|
| Prose card | bottom-centre, 46px | the claim being made right now |
| **Stack chip** | bottom-left, 30px amber | the **exact AWS service / CockroachDB feature** in use |
| Highlight box | on the element | coordinates captured live during the run |

---

## Beat 01 — hook · 19.0s

**Visual:** the dashboard at rest. No action — but the product is on screen from frame one,
and the first real click lands at **0:15**, inside the 20–30s window judges are told to
watch for.

> "Three in the morning, a data pipeline is down, and the on-call data engineer has exactly
> one question: have we seen this before? That's the moment the runbook is stale and
> whoever fixed it last time is asleep. This is Mimir — it answers that question from
> memory."

## Beat 02 — what you're looking at · 21.7s

**Action:** `Reset` · **Highlight:** `.simchip` — the live-vs-demo-stream chip

> "So this is what that engineer actually looks at. Failures from Airflow, BigQuery, dbt,
> and CockroachDB itself, in one queue. The incident stream is generated for this demo —
> everything downstream of it is live: the vector search, the decisions, the ledger. And
> here's the hard part: the moment you most need to remember something is the moment your
> infrastructure is already misbehaving."

## Beat 04 — the villain · 12.2s

**Action:** `Memory OFF` · **Highlight:** `#systems` — every source turns red

> "So, first — without memory. The agent has no precedent for anything. Every source turns
> red, and all eight incidents escalate to a human. One hundred percent."

## Beat 05 — memory on · 22.6s

**Action:** `Memory ON` · **Highlight:** `#chart` — the 100% → 38% panel
**Stack chips:** `Amazon Bedrock · Titan Text Embeddings v2 · 512-d`, then
`CockroachDB · C-SPANN vector index · cosine <=>`

> "Same eight incidents, memory on. Each incident is embedded by Amazon Bedrock — Titan
> Text v2 — and matched by cosine search over CockroachDB's vector index. Most of them hit
> a known pattern instantly, and come back with a proposed fix and a cited precedent. A
> hundred percent becomes thirty-eight."

## Beat 06 — the receipts · 11.8s

**Action:** open the first queue row → `Show the record`, scroll
**Highlight:** `.prov:not([hidden])` — the actual `monitored_signals` row
**Stack chip:** `CockroachDB · monitored_signals · JSONB payload`

> "And you don't have to take my word for any of it. Every incident opens onto its actual
> database row — the identifier, the timestamp, and the raw upstream error exactly as it
> was stored."

## Beat 07 — honest escalation, then teaching · 14.7s

**Action:** scroll to top, close the drawer, `Teach`

> "This one is different. The agent has never seen it, and it doesn't guess — it says so,
> and it escalates. I diagnose it once, in my own words. That sentence becomes the thing
> it cites next time."

## Beat 08 — one lesson, three systems · 24.5s

**Action:** `Pollinate`, scroll `#patterns` into view
**Highlight:** `#patterns .pat:has(.pill.new)` — `applies_to` grown to three
**Stack chip:** `CockroachDB · VECTOR(512) + applies_to STRING[]`

> "Now watch. A BigQuery query failure, and a dbt model error — different vendors,
> completely different error formats. Both match the pattern I taught thirty seconds ago
> from an Airflow task. One lesson, three systems — and you can see the pattern grow to
> cover all three. It still escalates, though: schema changes are high risk, so a human
> confirms. Recognition isn't permission."

## Beat 09 — the stack, and why this store · 34.8s

**Visual:** `docs/diagrams/architecture.html` overlaid across this window by
`assemble.mjs`, with a slow push-in. The longest beat, and the only one that is not the
live app. The diagram itself is the "slide naming the services" — `AWS Bedrock · Titan v2
embeds · Nova Micro explains` and `incident_patterns · VECTOR(512) C-SPANN + trust ledger`
are legible on it at 1080p.
**Stack chips:** `AWS Lambda · decide.handler`, then
`Amazon Bedrock Nova Micro · prose only, never the decision`

> "The shape is small. Bedrock embeds, a Lambda-shaped function classifies, CockroachDB
> remembers. And the decision is a pure rule matrix, not a model — Bedrock's Nova writes
> the explanation afterwards, it never picks the action. So why CockroachDB, and not
> Postgres with pgvector? Honestly, Postgres does this on one node. The difference is what
> happens when the node you're asking is the one that's on fire. And the trust ledger has
> to be transactional with the vector it describes — split those across two systems and
> you can grant autonomy that was never earned."

## Beat 10 — scale · 11.4s

**Visual:** scroll to top. No action.

> "Eight incidents today; a real platform has thousands across many teams. That's where
> this gets more valuable, not less — no replica lag between where a lesson was learned
> and where it's needed."

## Beat 11 — memory defending itself · 16.2s

**Action:** `CockroachDB skill` — live range IDs come back
**Stack chip:** `ccloud CLI · CockroachDB Agent Skills`

> "One of these is CockroachDB's own — a write hotspot on the agent's decision log. It
> proposes running CockroachDB's published Agent Skill, and those are real range IDs from
> the live cluster. The memory is diagnosing itself."

## Beat 12 — earned autonomy · 12.7s

**Action:** `Earn autonomy`, then `grant autonomy` · **Highlight:** `#patterns` — the ask
**Stack chip:** `CockroachDB · serializable trust ledger`

> "Last piece. This pattern has been approved unchanged five times, so the agent asks to be
> pre-authorised. Autonomy is earned by track record, granted only by me, and one rejection
> takes it away."

## Beat 13 — close · 12.6s

**Action:** open `details.hood` · **Highlight:** `details.hood` — live SQL and results

> "Every number here is a live query against CockroachDB, every vector a live call to
> Bedrock in us-east-one. One store, so the memory outlives the thing that broke.
> That's Mimir."

---

## Recording rules

- **Rehearse from a Reset.** The demo mutates state; a half-run looks broken on camera.
- **The counterfactual must show the same incident IDs** in beats 04 and 05, or it reads
  as staged. Don't crop the asset column.
- **Beat 11 fallback:** if the live skill call is slow, the JSON is already captured in the
  decision record — show that instead of waiting. Attempt live first.
- **Don't narrate the rate limit or the daily cap.** True, but not the story.
- **Frame it accurately, early.** The incident *stream* is generated for the demo; the
  dashboard, vector search, decisions and ledger are live. Say that once, near the start,
  and let the record view carry the proof — don't label the product "simulated".
- **Name AWS out loud *and* on screen.** This is a CockroachDB **×AWS** challenge and a
  judge may watch with the sound off, or never open the repo. The stack chips exist for
  exactly that: a service name pinned bottom-left while the thing is happening, so the use
  is confirmable from a paused frame. The first cut named neither AWS nor Bedrock once in
  thirteen beats — a scoring hole invisible from the written artifacts alone.
- **No static beat in the first 40 seconds.** The old `03` was pure narration over a
  motionless dashboard at 0:26–0:37 — precisely where a judge decides whether to keep
  watching. Its one load-bearing line ("the moment you most need to remember something is
  the moment your infrastructure is already misbehaving") moved into beat 02, where a Reset
  is running underneath it. Cutting the beat also bought ~14s back for the rest.
- **Keep compression under ~1.3×.** `assemble.mjs` fits the timeline to the cap
  automatically, but past roughly 1.3× the voice starts to read as processed. If a rewrite
  pushes narration over ~215s, cut a beat rather than let the ratio climb.

## Consistency check before publishing

The same three numbers must appear in the video, `docs/SUBMISSION.md`, and the README:
**100% → 38%**, **0.72 / 0.68** similarity, **three systems**. If any of them changes,
re-run `smoke_test.py --calibrate` and update all three together.

Upload as **public or unlisted** — a private video is unplayable for judges. Upload early;
Devpost lets you swap the link before the deadline.

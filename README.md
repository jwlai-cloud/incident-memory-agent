# incident-memory-agent

*Mimir — consult what survived.*

Built for the **CockroachDB × AWS Hackathon** ("Build with Agentic Memory"). An
incident-triage agent for data platforms — Airflow, BigQuery, dbt, and
CockroachDB itself — whose memory of every past incident, **and** of how much
the human trusts its judgment, persists in CockroachDB. A lesson taught once,
anywhere, is instantly reusable everywhere, and survives any failure — including
the incident itself.

![Architecture](docs/architecture.png)

*Interactive versions: [architecture](docs/diagrams/architecture.html) · [one incident end to end](docs/diagrams/sequence.html) — both have guided views, hover-to-trace and export.*

> **▶ [Interactive engineering walk-through](https://incident-memory-agent.vercel.app/tutorial)** — a live tutorial where the widgets run the real decision logic: toggle memory on/off, teach a schema-drift pattern and watch it pollinate across systems, and earn autonomy in the trust-ledger simulator.

## What makes it different

- **Trust ledger** — the agent remembers not just incidents but the outcomes of
  its own judgment, per pattern. Unchanged approvals earn autonomy; a single
  rejection revokes it. The human-in-the-loop gate is **learned, earned, and
  revocable** — not hardcoded.
- **Memoryless counterfactual** — flip one boolean (`memory_enabled`) and the
  same incident stream floods the review queue; flip it back and the queue
  melts. On-call life, before and after memory — no infrastructure kill needed.
- **Cross-system pattern pollination** — a `failure_class` taught from one
  Airflow incident matches its BigQuery and dbt cousins in embedding space. One
  lesson, three systems.
- **Self-writing runbook** — team documentation as a queryable VIEW over the
  agent's memory, always current, never hand-edited.

## How it works (30 seconds)

An incident fires → `embed.py` turns it into a normalized signature and a Bedrock
Titan vector → `decide.py` finds the nearest known pattern by cosine distance in
CockroachDB and picks **one** action with a deterministic rule matrix
(auto-resolve / propose / escalate) → the human responds → `respond.py` updates
the trust ledger → a never-seen incident is escalated and `teach.py` promotes the
human's diagnosis into a new pattern that its cross-system cousins then match.

See **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** for the full shape and
**[docs/LEARNING.md](docs/LEARNING.md)** for the tech breakdown with primary
sources.

## Tools used, and how

- **CockroachDB — Distributed Vector Indexing (C-SPANN):** incident patterns are
  stored as `VECTOR(512)` and matched with the cosine `<=>` operator
  (`vector_cosine_ops`). This is the core memory, and it *is* on every incident's
  decision path.
- **CockroachDB — MCP Server:** used **development-side**, not in the request path.
  The cluster exposes a managed MCP endpoint that a coding assistant queries read-only
  to inspect schema and memory while building. The runtime decision path
  (`decide.py`) talks to CockroachDB directly over pgwire and does not go through MCP.
  The session FAQ confirms dev-side usage satisfies the tool requirement; saying
  otherwise would overstate it.
- **CockroachDB — ccloud CLI + Agent Skills:** *only* for the CockroachDB-native
  incident. A matched hot-range pattern proposes the real
  [`analyzing-range-distribution`](https://github.com/cockroachlabs/cockroachdb-skills)
  skill, executed via ccloud. These do not diagnose Airflow/BigQuery/dbt — the
  split is deliberate and stated plainly.
- **AWS Bedrock:** Titan Text Embeddings v2 (`amazon.titan-embed-text-v2:0`, 512
  dims) for embeddings; the Converse API (default Nova Micro) for the reasoning
  prose on a match. The *decision* is deterministic; the LLM only explains.
- **AWS Lambda:** hosts the decision step (`decide.py`'s `handler`).

## Repo layout

```
scripts/
  simulate_incidents.py   incident cast -> monitored_signals (authentic payloads)
  embed.py                signature -> Titan embedding (shared by seed + live)
  seed_patterns.py        seed the 4 pre-loaded patterns + trust preload
  decide.py               embed -> cosine top-k -> deterministic action -> agent_decisions
  respond.py              trust ledger: approve/modify/reject, earned autonomy, revoke
  teach.py                escalation -> promoted pattern (closes teach->pollinate loop)
schema/schema.sql         monitored_signals, incident_patterns (trust ledger), agent_decisions, runbook view
docs/                     ARCHITECTURE, LEARNING, DESIGN, DEMO_SCRIPT, HANDOVER, adr/
```

## Quickstart

```sh
# 1. CockroachDB — Cloud Basic (free) or a local single node
cockroach start-single-node --insecure --listen-addr localhost:26257 --background
cockroach sql --insecure -e "SET CLUSTER SETTING feature.vector_index.enabled = true;"
cockroach sql --insecure < schema/schema.sql

# 2. Config
cp .env.example .env    # set COCKROACH_URL, AWS_REGION; AWS creds via your profile

# 3. Offline self-checks (no cluster / no AWS needed)
for s in simulate_incidents embed seed_patterns decide respond teach; do
  python3 scripts/$s.py --check
done

# 4. End-to-end (needs cluster + Bedrock)
python3 scripts/seed_patterns.py --seed
python3 scripts/simulate_incidents.py --inject
python3 scripts/decide.py --all --memory-off     # counterfactual: everything escalates
python3 scripts/decide.py --all                    # memory on: known incidents match
```

Dependencies: `psycopg[binary]` (v3), `boto3`.

## Status

Live: **https://incident-memory-agent.vercel.app** — an operator dashboard backed by a
real CockroachDB Cloud cluster with real Bedrock embeddings and reasoning. The incident
*stream* is generated for the demo; everything downstream of it — the vector search, the
decisions, the trust ledger, the audit log — is live. Every incident exposes its
underlying `monitored_signals` row so you can check that rather than take our word.
The original guided console is still at `/demo`. Nine scripts,
each with an offline `--check`. Measured on the live cluster: escalation
**100% → 38%** with memory on, and a pattern taught from Airflow matches its
BigQuery (0.72) and dbt (0.68) cousins. See **[docs/PROGRESS.md](docs/PROGRESS.md)**.

## Docs

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — current system shape
- [docs/LEARNING.md](docs/LEARNING.md) — tech breakdown + primary sources
- [docs/DESIGN.md](docs/DESIGN.md) — full rationale
- [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md) — 3-minute video storyboard
- [docs/HANDOVER.md](docs/HANDOVER.md) — build order + submission checklist
- [docs/adr/](docs/adr/) — architecture decision records

## License

MIT — see `LICENSE`.

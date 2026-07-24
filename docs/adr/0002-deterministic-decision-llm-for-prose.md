# 0002 — Deterministic decision; LLM writes prose only

- Status: Accepted
- Date: 2026-07-23

## Context

`decide.py` must choose auto-resolve / propose / escalate for each incident. The
tempting design is to let an LLM reason over the match and decide. But the
decision governs autonomy and a human-in-the-loop safety gate — it must be
predictable, testable, and auditable. The session FAQ confirmed that
deterministic coordination "still qualifies as agentic … as long as the system
is making decisions."

## Decision

The action is chosen by a pure `classify()` rule matrix over (cosine distance,
risk_level, autonomy_granted, autonomy_revoked_at, memory_enabled). Bedrock
(Converse API) is called only to write the human-readable `reasoning` prose, and
always has a deterministic template fallback.

## Consequences

- The safety-critical logic has a runnable truth-table self-check (`--check`)
  with no network — the HITL gate can't silently regress.
- The demo survives a Bedrock outage / rate limit (template fallback).
- The reasoning model is env-configurable (`BEDROCK_REASONING_MODEL`, default
  Nova Micro) because Bedrock Claude may not be free (per the session FAQ).
- Trade-off: the "intelligence" of the proposal text depends on the model, but
  the *decision* never does.

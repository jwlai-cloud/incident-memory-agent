#!/usr/bin/env python3
"""The decision engine: signal -> embed -> cosine top-k -> action -> record.

Lambda handler body + CLI. For each monitored signal it embeds the signature,
finds the nearest known pattern by cosine distance (the <=> operator), picks ONE
action with a DETERMINISTIC rule matrix, and writes agent_decisions.

    python scripts/decide.py --check              # decision matrix self-checks (no network)
    python scripts/decide.py --all                 # decide every signal, memory ON
    python scripts/decide.py --all --memory-off     # counterfactual: skip lookup, everything escalates
    python scripts/decide.py --signal <uuid>        # decide one signal

The ACTION (auto_resolved / proposed / escalated) is pure rules — testable, no
LLM. Bedrock (Converse) only writes the human-readable reasoning prose, with a
template fallback so the demo survives if the model is unavailable.

Honesty rules baked into classify():
  - memory disabled            -> escalate (the counterfactual villain)
  - no confident precedent     -> escalate (honest "new, you diagnose" / teach moment)
  - matched but risk_level=high -> escalate, but WITH the matched precedent cited
      (schema/data always gets full human diagnosis; this is the cross-system beat:
       pollinate_bq matches instantly yet still routes to a human)
  - matched, low-risk, autonomy granted & not revoked -> auto_resolve
  - matched, low-risk, otherwise                        -> propose (await human)
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import embed  # noqa: E402  (signature / embed_signal / to_vector_literal)

# The single riskiest number in the demo: seeds must match, novel_airflow must NOT
# (so it escalates and you teach it), then the taught schema_drift pattern must
# match pollinate_bq/dbt. CALIBRATE against real Titan embeddings once creds exist.
MATCH_MAX_DISTANCE = float(os.environ.get("MATCH_MAX_DISTANCE", "0.30"))
MATCH_TOP_K = int(os.environ.get("MATCH_TOP_K", "3"))
REASONING_MODEL = os.environ.get("BEDROCK_REASONING_MODEL", "amazon.nova-micro-v1:0")


def classify(distance, risk_level, autonomy_granted, autonomy_revoked_at,
             memory_enabled, max_distance=MATCH_MAX_DISTANCE) -> tuple[str, bool]:
    """Deterministic decision. Returns (action, use_match)."""
    if not memory_enabled:
        return "escalated", False                       # counterfactual: no lookup at all
    if distance is None or distance > max_distance:
        return "escalated", False                        # no confident precedent
    if risk_level == "high":
        return "escalated", True                          # rule 1 wins over any autonomy
    if autonomy_granted and not autonomy_revoked_at:
        return "auto_resolved", True
    return "proposed", True


# --- Bedrock reasoning (prose only; the action is already decided) ---

_bedrock_rt = None


def _bedrock_runtime():
    global _bedrock_rt
    if _bedrock_rt is None:
        import boto3
        _bedrock_rt = boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    return _bedrock_rt


def _converse(prompt: str, model_id: str | None = None) -> str:
    from botocore.exceptions import ClientError
    model_id = model_id or REASONING_MODEL
    kwargs = {
        "modelId": model_id,
        "messages": [{"role": "user", "content": [{"text": prompt}]}],
        "inferenceConfig": {"maxTokens": 400, "temperature": 0.2},
    }
    try:
        resp = _bedrock_runtime().converse(**kwargs)
    except ClientError as e:
        # some models require a geo inference-profile id for on-demand; retry with us.
        if (e.response["Error"]["Code"] == "ValidationException"
                and "on-demand throughput isn't supported" in str(e)
                and not model_id.startswith(("us.", "eu.", "apac."))):
            kwargs["modelId"] = "us." + model_id
            resp = _bedrock_runtime().converse(**kwargs)
        else:
            raise
    return resp["output"]["message"]["content"][0]["text"].strip()


def reason(signal: dict, pattern: dict) -> str:
    """LLM reasoning for a matched incident. Template fallback if Bedrock is down."""
    prompt = (
        "You are an incident-triage assistant. A new incident matched a known pattern.\n\n"
        f"New incident: {embed.signature(signal)}\n\n"
        f"Matched pattern '{pattern['label']}' (failure class {pattern['failure_class']}, "
        f"previously seen in {pattern['applies_to']}).\n"
        f"Documented root cause: {pattern['root_cause']}\n"
        f"Documented resolution: {pattern['resolution']}\n\n"
        "In 2-3 sentences, explain to an on-call engineer why this incident matches this "
        "pattern and what you propose. Cite the precedent."
    )
    try:
        return _converse(prompt)
    except Exception as e:  # noqa: BLE001 — never let reasoning prose break a decision
        return (f"Matches '{pattern['label']}' ({pattern['failure_class']}), previously seen in "
                f"{pattern['applies_to']}. Precedent root cause: {pattern['root_cause']} "
                f"Proposed resolution: {pattern['resolution']} "
                f"[reasoning model unavailable: {type(e).__name__}]")


def _reasoning_text(signal: dict, matched: dict | None, action: str, memory_enabled: bool) -> str:
    if not memory_enabled:
        return "Memory disabled (counterfactual): no precedent lookup performed; escalating to human."
    if matched is None:
        return (f"No confident precedent for: {embed.signature(signal)} "
                "Escalating for human diagnosis (teach moment).")
    sim = 1.0 - matched["distance"]
    body = reason(signal, matched)
    if action == "escalated":  # matched high-risk: recognized, but human must confirm
        return (f"Recognized precedent '{matched['label']}' (similarity {sim:.2f}), but "
                f"risk_level=high (schema/data) requires full human diagnosis. {body}")
    if action == "auto_resolved":
        return f"Auto-resolving under granted autonomy for '{matched['label']}' (similarity {sim:.2f}). {body}"
    return body  # proposed


# --- DB match + decide ---

def match(cur, vec_literal: str, k: int) -> list[dict]:
    cur.execute(
        "SELECT id, label, failure_class, applies_to, root_cause, resolution, "
        "remediation_channel, skill_ref, risk_level, confidence, autonomy_granted, "
        "autonomy_revoked_at, embedding <=> %s AS distance "
        "FROM incident_patterns ORDER BY embedding <=> %s LIMIT %s",
        (vec_literal, vec_literal, k),
    )
    return cur.fetchall()  # dict rows (see handler row_factory)


def decide(cur, signal_row: dict, memory_enabled: bool = True) -> dict:
    """Decide one signal, write agent_decisions, return a summary dict."""
    signal = {k: signal_row[k] for k in ("source_system", "signal_type", "asset", "payload")}

    matched, similarity = None, None
    if memory_enabled:
        rows = match(cur, embed.to_vector_literal(embed.embed_signal(signal)), MATCH_TOP_K)
        if rows:
            matched = rows[0]
            similarity = 1.0 - matched["distance"]

    action, use_match = classify(
        matched["distance"] if matched else None,
        matched["risk_level"] if matched else None,
        matched["autonomy_granted"] if matched else False,
        matched["autonomy_revoked_at"] if matched else None,
        memory_enabled,
    )
    if not use_match:
        matched, similarity = None, None

    reasoning = _reasoning_text(signal, matched, action, memory_enabled)

    cur.execute(
        "INSERT INTO agent_decisions "
        "(signal_id, matched_pattern_id, similarity, action, memory_enabled, reasoning) "
        "VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
        (signal_row["id"], matched["id"] if matched else None, similarity, action,
         memory_enabled, reasoning),
    )
    return {"decision_id": cur.fetchone()["id"], "action": action,
            "matched_pattern_id": matched["id"] if matched else None,
            "similarity": similarity, "memory_enabled": memory_enabled}


def handler(event: dict, context=None) -> dict:
    """Lambda entry. event: {signal_id} or {decide_all:true}, optional memory_enabled."""
    import psycopg
    from psycopg.rows import dict_row

    memory_enabled = event.get("memory_enabled", True)
    with psycopg.connect(os.environ["COCKROACH_URL"], row_factory=dict_row) as conn, conn.cursor() as cur:
        if event.get("decide_all"):
            cur.execute("SELECT id, source_system, signal_type, asset, payload "
                        "FROM monitored_signals ORDER BY observed_at")
        else:
            cur.execute("SELECT id, source_system, signal_type, asset, payload "
                        "FROM monitored_signals WHERE id = %s", (event["signal_id"],))
        signals = cur.fetchall()
        results = [decide(cur, s, memory_enabled) for s in signals]
        conn.commit()
    return {"decisions": results}


def self_check() -> None:
    md = 0.30
    cases = [
        # (distance, risk, autonomy, revoked_at, memory_on) -> (action, use_match)
        ((0.01, "low", False, None, False), ("escalated", False)),      # memory off
        ((None, None, False, None, True), ("escalated", False)),         # no rows
        ((0.50, "low", False, None, True), ("escalated", False)),        # too far
        ((0.05, "high", False, None, True), ("escalated", True)),        # high-risk matched
        ((0.05, "high", True, None, True), ("escalated", True)),         # high-risk beats autonomy
        ((0.05, "low", True, None, True), ("auto_resolved", True)),      # earned autonomy
        ((0.05, "low", True, "2026-01-01", True), ("proposed", True)),   # autonomy revoked -> propose
        ((0.05, "low", False, None, True), ("proposed", True)),          # low, not yet autonomous
    ]
    for args, expected in cases:
        got = classify(*args, max_distance=md)
        assert got == expected, f"classify{args} = {got}, expected {expected}"
    print("self-check OK: memory-off/no-match/too-far escalate; high-risk always escalates "
          "(with precedent, beats autonomy); low+autonomy auto; revoked/none propose")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Incident decision engine")
    ap.add_argument("--check", action="store_true", help="run decision-matrix self-checks (no network)")
    ap.add_argument("--signal", help="decide one monitored_signals row by id")
    ap.add_argument("--all", action="store_true", help="decide every signal in observed order")
    ap.add_argument("--memory-off", action="store_true", help="counterfactual: skip lookup, always escalate")
    args = ap.parse_args(argv)

    if args.check:
        self_check()
        return

    event = {"memory_enabled": not args.memory_off}
    if args.all:
        event["decide_all"] = True
    elif args.signal:
        event["signal_id"] = args.signal
    else:
        raise SystemExit("need --check, --all, or --signal <id>")

    for d in handler(event)["decisions"]:
        sim = f"{d['similarity']:.3f}" if d["similarity"] is not None else "-"
        print(f"{d['action']:13} match={d['matched_pattern_id']} sim={sim} mem={d['memory_enabled']}")


if __name__ == "__main__":
    main()

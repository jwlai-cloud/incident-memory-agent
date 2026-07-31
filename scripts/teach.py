#!/usr/bin/env python3
"""Promote a no-precedent escalation into a new pattern (the teach moment).

When decide.py escalates an incident it has never seen, a human diagnoses it and
writes the root cause + resolution. teach.py inserts that as a new pattern
(source='promoted'), embedded FROM the escalated signal — so future cousins in
other systems (the pollination) then match it.

    python scripts/teach.py --check                      # validation self-checks (no DB)
    python scripts/teach.py --decision <id> \
        --label upstream-schema-drift-dropped-column \
        --failure-class schema_drift \
        --risk-level high --remediation-channel manual \
        --root-cause "..." --resolution "..."

root_cause is the human's own worked example; it feeds the Bedrock reasoning call
whenever the pattern later matches.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import embed  # noqa: E402  (embed_signal / to_vector_literal)

VALID_CHANNELS = {"airflow_adapter", "bigquery_adapter", "ccloud_skill", "manual"}
VALID_RISK = {"low", "high"}


def validate_pattern_fields(risk_level: str, remediation_channel: str, skill_ref: str | None) -> None:
    if risk_level not in VALID_RISK:
        raise ValueError(f"risk_level must be one of {sorted(VALID_RISK)}, got {risk_level!r}")
    if remediation_channel not in VALID_CHANNELS:
        raise ValueError(f"remediation_channel must be one of {sorted(VALID_CHANNELS)}, got {remediation_channel!r}")
    if (skill_ref is not None) != (remediation_channel == "ccloud_skill"):
        raise ValueError("skill_ref must be set iff remediation_channel is 'ccloud_skill'")


def teach(cur, decision_id: str, label: str, failure_class: str, root_cause: str,
          resolution: str, risk_level: str, remediation_channel: str,
          skill_ref: str | None = None) -> dict:
    validate_pattern_fields(risk_level, remediation_channel, skill_ref)

    cur.execute(
        "SELECT d.matched_pattern_id, d.action, s.source_system, s.signal_type, s.asset, s.payload "
        "FROM agent_decisions d JOIN monitored_signals s ON s.id = d.signal_id WHERE d.id = %s",
        (decision_id,),
    )
    row = cur.fetchone()
    if row is None:
        raise SystemExit(f"no decision {decision_id}")
    if row["matched_pattern_id"] is not None:
        raise SystemExit("decision already matched a pattern; confirm via respond.py, don't re-teach")
    if row["action"] != "escalated":
        raise SystemExit(f"can only teach from an escalation, not '{row['action']}'")

    signal = {k: row[k] for k in ("source_system", "signal_type", "asset", "payload")}
    vec = embed.embed_signal(signal)  # embed the escalated signal -> cousins match this pattern

    cur.execute(
        "INSERT INTO incident_patterns "
        "(label, failure_class, embedding, applies_to, root_cause, resolution, "
        " remediation_channel, skill_ref, risk_level, confirm_count, source, first_seen, last_confirmed_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,1,'promoted',now(),now()) RETURNING id",
        (label, failure_class, embed.to_vector_literal(vec), [row["source_system"]],
         root_cause, resolution, remediation_channel, skill_ref, risk_level),
    )
    pattern_id = cur.fetchone()["id"]

    # resolve the escalation and link it to the pattern it produced (human_response stays
    # NULL — this was never a proposal to approve, it was diagnosed from scratch).
    cur.execute(
        "UPDATE agent_decisions SET matched_pattern_id=%s, outcome='confirmed', resolved_at=now() WHERE id=%s",
        (pattern_id, decision_id),
    )

    return {"pattern_id": pattern_id, "label": label,
            "applies_to": [row["source_system"]], "source": "promoted"}


def handler(event: dict, context=None) -> dict:
    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(os.environ["COCKROACH_URL"], row_factory=dict_row) as conn, conn.cursor() as cur:
        out = teach(cur, event["decision_id"], event["label"], event["failure_class"],
                    event["root_cause"], event["resolution"], event["risk_level"],
                    event["remediation_channel"], event.get("skill_ref"))
        conn.commit()
    return out


def self_check() -> None:
    validate_pattern_fields("high", "manual", None)                                  # ok
    validate_pattern_fields("low", "ccloud_skill", "analyzing-range-distribution")   # ok
    bad_cases = [
        ("medium", "manual", None),               # bad risk
        ("high", "slack", None),                   # bad channel
        ("low", "ccloud_skill", None),             # ccloud without skill_ref
        ("low", "manual", "some-skill"),           # skill_ref without ccloud
    ]
    for risk, channel, skill in bad_cases:
        try:
            validate_pattern_fields(risk, channel, skill)
            raise AssertionError(f"should have rejected ({risk}, {channel}, {skill})")
        except ValueError:
            pass
    print("self-check OK: pattern-field validation (risk, channel, skill_ref iff ccloud_skill)")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Promote an escalation into a new pattern")
    ap.add_argument("--check", action="store_true", help="run validation self-checks and exit (no DB)")
    ap.add_argument("--decision", help="escalated decision id to promote")
    ap.add_argument("--label")
    ap.add_argument("--failure-class")
    ap.add_argument("--root-cause")
    ap.add_argument("--resolution")
    ap.add_argument("--risk-level", choices=sorted(VALID_RISK))
    ap.add_argument("--remediation-channel", choices=sorted(VALID_CHANNELS))
    ap.add_argument("--skill-ref")
    args = ap.parse_args(argv)

    if args.check:
        self_check()
        return

    required = [args.decision, args.label, args.failure_class, args.root_cause,
                args.resolution, args.risk_level, args.remediation_channel]
    if not all(required):
        raise SystemExit("need --check, or all of: --decision --label --failure-class "
                         "--root-cause --resolution --risk-level --remediation-channel [--skill-ref]")

    print(handler({"decision_id": args.decision, "label": args.label,
                   "failure_class": args.failure_class, "root_cause": args.root_cause,
                   "resolution": args.resolution, "risk_level": args.risk_level,
                   "remediation_channel": args.remediation_channel, "skill_ref": args.skill_ref}))


if __name__ == "__main__":
    main()

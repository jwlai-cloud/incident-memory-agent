#!/usr/bin/env python3
"""Human response endpoint + the trust ledger.

A human responds to a decision; this records the response and updates the matched
pattern's trust ledger. Autonomy is earned by an unchanged-approval streak, granted
only by an explicit human action, and revoked by a single rejection.

    python scripts/respond.py --check                                   # self-checks (no DB)
    python scripts/respond.py --decision <id> --response approved_unchanged
    python scripts/respond.py --decision <id> --response modified --modified-text "..."
    python scripts/respond.py --decision <id> --response rejected
    python scripts/respond.py --grant <pattern_id>                        # explicit pre-authorization

Ledger updates are done in-SQL (counter = counter + 1; conditional array_append)
so there is no read-modify-write race; CockroachDB's serializable default makes
concurrent responses safe. The reject-revoke is a single UPDATE whose SET
expressions read pre-update values, so "revoke only if it was granted" is atomic.
"""
from __future__ import annotations

import argparse
import os

VALID_RESPONSES = {"approved_unchanged", "modified", "rejected"}
AUTONOMY_THRESHOLD = int(os.environ.get("AUTONOMY_THRESHOLD", "5"))


# --- pure trust-ledger policy (the branchy logic; tested by --check) ---

def can_grant(risk_level: str, approved_unchanged_count: int, rejected_count: int) -> bool:
    """Autonomy is grantable only when earned: low-risk, enough unchanged approvals,
    and never after a rejection. High-risk is never grantable (rule 1)."""
    return (risk_level == "low"
            and approved_unchanged_count >= AUTONOMY_THRESHOLD
            and rejected_count == 0)


def autonomy_ask_eligible(risk_level: str, approved_unchanged_count: int,
                          rejected_count: int, autonomy_granted: bool) -> bool:
    """Whether to surface the 'pre-authorize this pattern?' ask after an approval."""
    return can_grant(risk_level, approved_unchanged_count, rejected_count) and not autonomy_granted


def revoke_on_reject(autonomy_granted: bool) -> bool:
    """One rejection after a grant revokes autonomy."""
    return bool(autonomy_granted)


# --- DB operations ---

def respond(cur, decision_id: str, response_type: str, modified_text: str | None = None) -> dict:
    if response_type not in VALID_RESPONSES:
        raise SystemExit(f"invalid response {response_type!r}; one of {sorted(VALID_RESPONSES)}")

    cur.execute(
        "SELECT d.matched_pattern_id, s.source_system, p.risk_level, p.autonomy_granted AS was_granted "
        "FROM agent_decisions d JOIN monitored_signals s ON s.id = d.signal_id "
        "LEFT JOIN incident_patterns p ON p.id = d.matched_pattern_id WHERE d.id = %s",
        (decision_id,),
    )
    row = cur.fetchone()
    if row is None:
        raise SystemExit(f"no decision {decision_id}")

    outcome = "confirmed" if response_type in ("approved_unchanged", "modified") else "refuted"
    if response_type == "modified" and modified_text:
        cur.execute(
            "UPDATE agent_decisions SET human_response=%s, outcome=%s, resolved_at=now(), "
            # coalesce: NULL || text is NULL in SQL, which would erase the reasoning
            "reasoning = coalesce(reasoning, '') || %s WHERE id=%s",
            (response_type, outcome, f"\n[human modified] {modified_text}", decision_id),
        )
    else:
        cur.execute(
            "UPDATE agent_decisions SET human_response=%s, outcome=%s, resolved_at=now() WHERE id=%s",
            (response_type, outcome, decision_id),
        )

    result = {"decision_id": decision_id, "response": response_type,
              "pattern_id": row["matched_pattern_id"]}
    pid = row["matched_pattern_id"]
    if pid is None:
        result["note"] = "escalation with no precedent resolved; no ledger update (teach.py promotes a pattern)"
        return result

    src = row["source_system"]
    if response_type in ("approved_unchanged", "modified"):
        # col is whitelisted (never user input) -> safe to interpolate
        col = "approved_unchanged_count" if response_type == "approved_unchanged" else "modified_count"
        cur.execute(
            f"UPDATE incident_patterns SET {col} = {col} + 1, confirm_count = confirm_count + 1, "
            "last_confirmed_at = now(), "
            # explicit ::STRING casts: CockroachDB cannot infer a placeholder's type
            # inside ANY()/array_append (IndeterminateDatatype otherwise)
            "applies_to = CASE WHEN %s::STRING = ANY(applies_to) THEN applies_to "
            "ELSE array_append(applies_to, %s::STRING) END "
            "WHERE id = %s "
            "RETURNING risk_level, approved_unchanged_count, rejected_count, autonomy_granted, applies_to",
            (src, src, pid),
        )
        p = cur.fetchone()
        result["applies_to"] = p["applies_to"]
        result["autonomy_ask"] = autonomy_ask_eligible(
            p["risk_level"], p["approved_unchanged_count"], p["rejected_count"], p["autonomy_granted"])
    else:  # rejected
        cur.execute(
            "UPDATE incident_patterns SET rejected_count = rejected_count + 1, refute_count = refute_count + 1, "
            "autonomy_revoked_at = CASE WHEN autonomy_granted THEN now() ELSE autonomy_revoked_at END, "
            "autonomy_granted = false WHERE id = %s",
            (pid,),
        )
        result["autonomy_revoked"] = revoke_on_reject(row["was_granted"])
    return result


def grant_autonomy(cur, pattern_id: str) -> dict:
    cur.execute(
        "SELECT label, risk_level, approved_unchanged_count, rejected_count "
        "FROM incident_patterns WHERE id = %s",
        (pattern_id,),
    )
    p = cur.fetchone()
    if p is None:
        raise SystemExit(f"no pattern {pattern_id}")
    if not can_grant(p["risk_level"], p["approved_unchanged_count"], p["rejected_count"]):
        return {"granted": False, "pattern": p["label"],
                "reason": f"not earned: risk={p['risk_level']}, "
                          f"approvals={p['approved_unchanged_count']}/{AUTONOMY_THRESHOLD}, "
                          f"rejections={p['rejected_count']}"}
    cur.execute(
        "UPDATE incident_patterns SET autonomy_granted=true, autonomy_granted_at=now(), "
        "autonomy_revoked_at=NULL WHERE id = %s",
        (pattern_id,),
    )
    return {"granted": True, "pattern": p["label"]}


def handler(event: dict, context=None) -> dict:
    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(os.environ["COCKROACH_URL"], row_factory=dict_row) as conn, conn.cursor() as cur:
        if "grant_autonomy" in event:
            out = grant_autonomy(cur, event["grant_autonomy"])
        else:
            out = respond(cur, event["decision_id"], event["response"], event.get("modified_text"))
        conn.commit()
    return out


def self_check() -> None:
    t = AUTONOMY_THRESHOLD
    # can_grant
    assert can_grant("low", t, 0) is True
    assert can_grant("low", t - 1, 0) is False          # below threshold: must be earned
    assert can_grant("low", t, 1) is False               # a prior rejection blocks it
    assert can_grant("high", t, 0) is False               # high-risk never (rule 1)
    # ask eligibility
    assert autonomy_ask_eligible("low", t, 0, False) is True
    assert autonomy_ask_eligible("low", t, 0, True) is False    # already granted
    assert autonomy_ask_eligible("high", t, 0, False) is False
    # revoke
    assert revoke_on_reject(True) is True
    assert revoke_on_reject(False) is False
    # demo trust beat: seed_1 preloaded at 4 -> the on-camera approve makes 5
    assert autonomy_ask_eligible("low", 4, 0, False) is False    # before the 5th approval
    assert autonomy_ask_eligible("low", 5, 0, False) is True      # the ask fires
    print(f"self-check OK: grant earned (low-risk, >={t} approvals, 0 rejections); high-risk never; "
          "ask fires on the 5th approval; reject revokes iff granted")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Human response + trust ledger")
    ap.add_argument("--check", action="store_true", help="run policy self-checks and exit (no DB)")
    ap.add_argument("--decision", help="decision id to respond to")
    ap.add_argument("--response", choices=sorted(VALID_RESPONSES), help="the human response")
    ap.add_argument("--modified-text", help="edit text, used with --response modified")
    ap.add_argument("--grant", help="pattern id to grant autonomy (explicit pre-authorization)")
    args = ap.parse_args(argv)

    if args.check:
        self_check()
    elif args.grant:
        print(handler({"grant_autonomy": args.grant}))
    elif args.decision and args.response:
        print(handler({"decision_id": args.decision, "response": args.response,
                       "modified_text": args.modified_text}))
    else:
        raise SystemExit("need --check, --grant <pattern_id>, or --decision <id> --response <type>")


if __name__ == "__main__":
    main()

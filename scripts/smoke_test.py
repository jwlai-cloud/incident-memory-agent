#!/usr/bin/env python3
"""End-to-end smoke test + threshold calibration against a live cluster.

Run this the moment the CockroachDB cluster + AWS creds are ready. It exercises
every previously-untested write path at once and prints the numbers we need.

    python scripts/smoke_test.py --check       # offline wiring + partition asserts
    python scripts/smoke_test.py --calibrate    # reset, embed the cast, print nearest-pattern
                                                # distances + a SUGGESTED MATCH_MAX_DISTANCE
    python scripts/smoke_test.py --e2e          # reset, decide OFF then ON, print the
                                                # escalation-rate counterfactual live

Prereqs: schema/schema.sql applied, feature.vector_index.enabled=true, COCKROACH_URL
set, AWS creds with Bedrock access, AWS_REGION set.

--calibrate is the important one: seeds are embedded from the same signatures as
their patterns, so they should match at ~0 distance; the schema-drift incidents
(not yet seeded) should be far. The suggested threshold sits between those two
clusters — that resolves the one number the whole demo hinges on.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import embed  # noqa: E402
import decide  # noqa: E402
import reset_demo  # noqa: E402
from simulate_incidents import CAST  # noqa: E402

# Schema-drift is taught live, not seeded -> these should NOT match any pattern before the teach.
DRIFT_BEATS = {"teach", "pollinate"}


def _conn():
    import psycopg
    from psycopg.rows import dict_row
    url = os.environ.get("COCKROACH_URL")
    if not url:
        sys.exit("COCKROACH_URL not set (see .env.example).")
    return psycopg.connect(url, row_factory=dict_row)


def calibrate() -> None:
    reset_demo.reset()  # clean baseline: 4 patterns seeded, cast injected
    rows = []
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, source_system, signal_type, asset, payload "
                    "FROM monitored_signals ORDER BY observed_at")
        for s in cur.fetchall():
            vec = embed.embed_signal(s)
            near = decide.match(cur, embed.to_vector_literal(vec), 1)
            best = near[0] if near else None
            demo = s["payload"]["demo"]
            rows.append((demo["id"], demo["beat"],
                         best["label"] if best else "-",
                         best["distance"] if best else float("nan")))

    print("\n  incident            beat           nearest pattern                     distance")
    print("  " + "-" * 82)
    for did, beat, label, dist in sorted(rows, key=lambda r: r[3]):
        should = "match" if beat not in DRIFT_BEATS else "NO match (pre-teach)"
        print(f"  {did:<18}  {beat:<12}  {label:<34}  {dist:6.3f}  [{should}]")

    match_max = max((d for _, b, _, d in rows if b not in DRIFT_BEATS), default=None)
    nomatch_min = min((d for _, b, _, d in rows if b in DRIFT_BEATS), default=None)
    print()
    if match_max is not None and nomatch_min is not None and match_max < nomatch_min:
        suggested = round((match_max + nomatch_min) / 2, 3)
        print(f"  clean separation: seeds match <= {match_max:.3f}, drift sits >= {nomatch_min:.3f}")
        print(f"  SUGGESTED  MATCH_MAX_DISTANCE = {suggested}   "
              f"(current default {decide.MATCH_MAX_DISTANCE})")
    else:
        print(f"  WARNING: no clean separation (match_max={match_max}, nomatch_min={nomatch_min}). "
              "Signatures need tuning before the threshold will work.")


def e2e() -> None:
    reset_demo.reset()
    print("\n  running decide OFF (counterfactual) then ON over the same signals...")
    decide.handler({"decide_all": True, "memory_enabled": False})
    decide.handler({"decide_all": True, "memory_enabled": True})
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT memory_enabled, count(*) AS n, "
            "count(*) FILTER (WHERE action='escalated') AS escalated, "
            "round(100.0*count(*) FILTER (WHERE action='escalated')/count(*), 0) AS pct "
            "FROM agent_decisions GROUP BY memory_enabled ORDER BY memory_enabled")
        print("\n  memory_enabled   escalated / total   escalation rate")
        print("  " + "-" * 52)
        for r in cur.fetchall():
            print(f"  {str(r['memory_enabled']):<14}   {r['escalated']:>3} / {r['n']:<3}"
                  f"            {r['pct']:>3.0f}%")
    print("\n  ^ that gap is the memoryless counterfactual, live.")


def self_check() -> None:
    beats = {i.beat for i in CAST}
    assert DRIFT_BEATS <= beats, f"DRIFT_BEATS {DRIFT_BEATS} not all present in cast beats {beats}"
    assert {i.demo_id for i in CAST if i.beat in DRIFT_BEATS} == \
        {"novel_airflow", "pollinate_bq", "pollinate_dbt"}, "drift set drifted from the cast"
    # entry points exist on the reused modules
    for mod, fn in [(embed, "embed_signal"), (decide, "match"), (decide, "handler"),
                    (reset_demo, "reset")]:
        assert callable(getattr(mod, fn)), f"{mod.__name__}.{fn} missing"
    print("self-check OK: drift partition matches the cast; embed/decide/reset wiring intact")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="End-to-end smoke test + threshold calibration")
    ap.add_argument("--check", action="store_true", help="offline wiring + partition asserts")
    ap.add_argument("--calibrate", action="store_true", help="print nearest-pattern distances + suggested threshold")
    ap.add_argument("--e2e", action="store_true", help="run the counterfactual end to end")
    args = ap.parse_args(argv)
    if args.check:
        self_check()
    elif args.calibrate:
        calibrate()
    elif args.e2e:
        e2e()
    else:
        raise SystemExit("need --check, --calibrate, or --e2e")


if __name__ == "__main__":
    main()

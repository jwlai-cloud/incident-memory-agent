#!/usr/bin/env python3
"""Reset the demo to a clean baseline so it replays identically.

The demo mutates state (trust counters climb, applies_to grows, novel_airflow
gets promoted). Run this before each take / behind the UI "Reset" button.

    python scripts/reset_demo.py --plan     # print the steps (no network)
    python scripts/reset_demo.py             # execute (needs COCKROACH_URL + AWS creds)

Steps (in one pass):
  1. TRUNCATE monitored_signals CASCADE   -> also clears agent_decisions (FK)
  2. DELETE promoted patterns             -> undo any live teach
  3. seed_patterns.seed()                 -> re-seed the 4 patterns, fresh trust counters
  4. simulate_incidents.inject(now)       -> re-inject the 8-incident cast

Video fallback (grilled decision B): keep a pristine baseline as a CockroachDB
managed backup and RESTORE in seconds if a take corrupts state badly:
    BACKUP INTO 's3://<bucket>/mimir-baseline?AWS_...' AS OF SYSTEM TIME '-10s';
    RESTORE FROM LATEST IN 's3://<bucket>/mimir-baseline?AWS_...';
Slower than this re-seed, but a real CockroachDB tool and a safety net on camera.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import seed_patterns  # noqa: E402
import simulate_incidents  # noqa: E402

STEPS = [
    "TRUNCATE monitored_signals CASCADE            (clears agent_decisions via FK)",
    "DELETE FROM incident_patterns WHERE source='promoted'",
    "seed_patterns.seed()                          (re-seed 4 patterns, reset trust ledger)",
    "simulate_incidents.inject(now)                (re-inject the 8-incident cast)",
]


def reset() -> None:
    url = os.environ.get("COCKROACH_URL")
    if not url:
        sys.exit("COCKROACH_URL not set (see .env.example). Preview instead: --plan.")
    import psycopg

    with psycopg.connect(url) as conn, conn.cursor() as cur:
        # DELETE, not TRUNCATE: in CockroachDB TRUNCATE is a schema change (it swaps
        # in a fresh table descriptor via a job), which measured ~65s on a Cloud Basic
        # cluster even for a handful of rows. DELETE on tables this small is ~1s.
        # Children first — agent_decisions references monitored_signals.
        cur.execute("DELETE FROM agent_decisions WHERE true")
        cur.execute("DELETE FROM monitored_signals WHERE true")
        cur.execute("DELETE FROM incident_patterns WHERE source = 'promoted'")
        conn.commit()
    seed_patterns.seed()  # own connection + Bedrock embeds; DELETEs source='seed' first
    simulate_incidents.inject(datetime.now(timezone.utc))
    print("demo reset to baseline (signals + decisions cleared, patterns re-seeded, cast re-injected)")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Reset the demo to a clean baseline")
    ap.add_argument("--plan", action="store_true", help="print the reset steps and exit (no network)")
    args = ap.parse_args(argv)
    if args.plan:
        print("reset_demo plan:")
        for i, s in enumerate(STEPS, 1):
            print(f"  {i}. {s}")
        return
    reset()


if __name__ == "__main__":
    main()

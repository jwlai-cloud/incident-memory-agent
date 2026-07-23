#!/usr/bin/env python3
"""Seed the pre-loaded incident patterns into CockroachDB.

Four patterns exist in memory before the demo starts. The schema-drift pattern
is deliberately NOT seeded — it is taught live on camera (source='promoted').

    python scripts/seed_patterns.py            # dry-run: print patterns + signatures (no network)
    python scripts/seed_patterns.py --check     # self-checks and exit (no network)
    python scripts/seed_patterns.py --seed      # embed via Bedrock + INSERT ($COCKROACH_URL, AWS creds)

Each pattern's embedding is the Titan embedding of a *representative* incident's
signature (embed.signature), so the seed sits exactly where its live incident
lands — and trust_repeat (identical signature to seed_1) matches seed_1 hard.

root_cause / resolution are the human's own worked example: root_cause feeds the
Bedrock reasoning call whenever the pattern matches. seed_1 is pre-loaded with 4
unchanged approvals so the on-camera approve on trust_repeat is the 5th and
crosses the trust-ledger threshold live.
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import embed  # noqa: E402  (signature/embed_signal/to_vector_literal, shared with decide.py)

VALID_CHANNELS = {"airflow_adapter", "bigquery_adapter", "ccloud_skill", "manual"}
VALID_RISK = {"low", "high"}


@dataclass
class SeedPattern:
    label: str
    failure_class: str
    applies_to: list[str]
    root_cause: str            # human rationale — feeds the reasoning call on future matches
    resolution: str
    remediation_channel: str
    risk_level: str
    embed_from: str            # cast demo_id whose signature defines this pattern's embedding
    skill_ref: str | None = None
    confidence: float = 0.7
    confirm_count: int = 0
    approved_unchanged_count: int = 0
    first_seen_days_ago: int = 30
    last_confirmed_days_ago: int | None = None


PATTERNS: list[SeedPattern] = [
    SeedPattern(
        label="upstream-source-connection-timeout",
        failure_class="transient_connectivity",
        applies_to=["airflow"],
        root_cause=(
            "Source Postgres (orders-db) runs a nightly vacuum 02:00-02:15 UTC; a task "
            "starting inside that window races the vacuum lock and the first connect times "
            "out. Timing, not a code fault."
        ),
        resolution=(
            "Clear the task for retry - the 5-minute retry lands after the vacuum window and "
            "succeeds. If it fails 3x, page the DBA (the vacuum window overran)."
        ),
        remediation_channel="airflow_adapter",
        risk_level="low",
        embed_from="seed_1",
        confidence=0.9,
        confirm_count=4,
        approved_unchanged_count=4,   # 4 prior unchanged approvals -> trust_repeat is the 5th, live
        last_confirmed_days_ago=2,
    ),
    SeedPattern(
        label="unpruned-partition-full-scan",
        failure_class="resource_exhaustion",
        applies_to=["bigquery"],
        root_cause=(
            "The incremental model's WHERE is templated on {{ ds }}; a backfill run passed an "
            "empty ds, dropping partition pruning and full-scanning the multi-TB raw.events table."
        ),
        resolution=(
            "Re-run with an explicit date range; set require_partition_filter=true on the table; "
            "add a 500 GB/query cost alert."
        ),
        remediation_channel="bigquery_adapter",
        risk_level="low",
        embed_from="seed_2",
        confidence=0.8,
        confirm_count=2,
        last_confirmed_days_ago=9,
    ),
    SeedPattern(
        label="new-enum-value-upstream",
        failure_class="data_quality",
        applies_to=["dbt"],
        root_cause=(
            "The upstream app ships new order-status values without notice; the accepted_values "
            "test is stricter than reality. A recurring spec-lag, not a data bug."
        ),
        resolution=(
            "Confirm the new value with product, add it to the accepted_values list in schema.yml, "
            "and document the state."
        ),
        remediation_channel="manual",
        risk_level="low",
        embed_from="seed_3",
        confidence=0.8,
        confirm_count=3,
        last_confirmed_days_ago=6,
    ),
    SeedPattern(
        label="sequential-key-write-hotspot",
        failure_class="hot_range_contention",
        applies_to=["cockroachdb"],
        root_cause=(
            "order_events uses a monotonically increasing timestamp/serial primary key, so every "
            "insert targets the max range - a single-range write hotspot with no spread across "
            "replicas."
        ),
        resolution=(
            "Triage live via the CockroachDB 'analyzing-range-distribution' Agent Skill through "
            "ccloud (read-only SHOW RANGES) to confirm the range and leaseholder. Fix: hash-shard "
            "the index (USING HASH) or move to a UUID/composite primary key to distribute writes."
        ),
        remediation_channel="ccloud_skill",
        skill_ref="analyzing-range-distribution",   # cockroachlabs/cockroachdb-skills
        risk_level="low",
        embed_from="crdb_hot_range",
        confidence=0.85,
        confirm_count=1,
        last_confirmed_days_ago=14,
    ),
]


def _representative_signal(demo_id: str) -> dict:
    from simulate_incidents import CAST
    inc = next(i for i in CAST if i.demo_id == demo_id)
    return {"source_system": inc.source_system, "signal_type": inc.signal_type,
            "asset": inc.asset, "payload": inc.payload()}


def dry_run() -> None:
    for p in PATTERNS:
        sig = embed.signature(_representative_signal(p.embed_from))
        print(f"\n{p.label}  [{p.failure_class}, risk={p.risk_level}, {p.remediation_channel}"
              + (f", skill={p.skill_ref}" if p.skill_ref else "") + "]")
        print(f"  applies_to={p.applies_to}  approvals={p.approved_unchanged_count} "
              f"confirms={p.confirm_count} conf={p.confidence}")
        print(f"  signature: {sig}")
        print(f"  root_cause: {p.root_cause}")
        print(f"  resolution: {p.resolution}")


def seed() -> None:
    url = os.environ.get("COCKROACH_URL")
    if not url:
        sys.exit("COCKROACH_URL not set (see .env.example). Dry-run instead: omit --seed.")
    import psycopg

    now = datetime.now(timezone.utc)
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM incident_patterns WHERE source = 'seed'")  # idempotent re-seed
        for p in PATTERNS:
            vec = embed.embed_signal(_representative_signal(p.embed_from))
            cur.execute(
                "INSERT INTO incident_patterns "
                "(label, failure_class, embedding, applies_to, root_cause, resolution, "
                " remediation_channel, skill_ref, risk_level, confidence, confirm_count, "
                " approved_unchanged_count, source, first_seen, last_confirmed_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'seed',%s,%s)",
                (
                    p.label, p.failure_class, embed.to_vector_literal(vec), p.applies_to,
                    p.root_cause, p.resolution, p.remediation_channel, p.skill_ref,
                    p.risk_level, p.confidence, p.confirm_count, p.approved_unchanged_count,
                    now - timedelta(days=p.first_seen_days_ago),
                    None if p.last_confirmed_days_ago is None
                    else now - timedelta(days=p.last_confirmed_days_ago),
                ),
            )
        conn.commit()
    print(f"seeded {len(PATTERNS)} patterns into incident_patterns (source='seed')")


def self_check() -> None:
    from simulate_incidents import CAST
    ids = {i.demo_id for i in CAST}

    labels = [p.label for p in PATTERNS]
    assert len(labels) == len(set(labels)) == 4, "expected 4 unique seed patterns"

    for p in PATTERNS:
        assert p.remediation_channel in VALID_CHANNELS, f"{p.label}: bad channel"
        assert p.risk_level in VALID_RISK, f"{p.label}: bad risk_level"
        assert (p.skill_ref is not None) == (p.remediation_channel == "ccloud_skill"), \
            f"{p.label}: skill_ref must be set iff channel is ccloud_skill"
        assert p.embed_from in ids, f"{p.label}: embed_from '{p.embed_from}' not in cast"
        assert embed.signature(_representative_signal(p.embed_from)).strip(), f"{p.label}: empty signature"

    s1 = next(p for p in PATTERNS if p.embed_from == "seed_1")
    assert s1.approved_unchanged_count == 4, "seed_1 pattern must pre-load 4 unchanged approvals"

    # the schema-drift class must NOT be pre-seeded (it is taught live).
    assert not any(p.failure_class == "schema_drift" for p in PATTERNS), \
        "schema_drift is taught live, never seeded"

    print("self-check OK: 4 seed patterns, valid channels/risk, skill_ref iff ccloud_skill, "
          "seed_1 preload=4, no seeded schema_drift")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Seed pre-loaded incident patterns")
    ap.add_argument("--check", action="store_true", help="run self-checks and exit (no network)")
    ap.add_argument("--seed", action="store_true", help="embed via Bedrock + INSERT ($COCKROACH_URL)")
    args = ap.parse_args(argv)

    if args.check:
        self_check()
    elif args.seed:
        seed()
    else:
        dry_run()


if __name__ == "__main__":
    main()

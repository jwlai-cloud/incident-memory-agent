#!/usr/bin/env python3
"""Incident cast generator for the Mimir demo.

Produces the deterministic incident stream (DEMO_SCRIPT.md) as
`monitored_signals` rows with authentic payload shapes.

    python scripts/simulate_incidents.py            # dry-run: print cast as JSON (no DB)
    python scripts/simulate_incidents.py --inject    # INSERT into CockroachDB ($COCKROACH_URL)
    python scripts/simulate_incidents.py --check      # run self-checks and exit
    python scripts/simulate_incidents.py --beat teach # limit to one storyboard beat

Each payload is `{"demo": ..., "artifact": ..., "baseline": ...}`:
  demo     - simulation metadata (stable id, beat). NOT part of the embedding
             signature; embed.py reads artifact + baseline only.
  artifact - authentic upstream error/metric shape, verified against vendor docs.
  baseline - adapter-computed context so embed.py can derive deviation magnitude
             (there is no real incident history in a demo; this is honest enrichment).

Payload shapes verified against primary sources:
  Airflow TaskInstance ... apache/airflow 2.10.5 TaskInstanceSchema
                           (run_id serializes as `dag_run_id`)
  BigQuery Job.status .... cloud.google.com/bigquery/docs/reference/rest/v2/Job + ErrorProto
                           (schema drift -> reason 'invalidQuery', HTTP 400)
  dbt run_results.json ... schemas.getdbt.com/dbt/run-results/v6.json
  CockroachDB hot range .. /api/v2/ranges/hot/ hotRangeInfo
                           (there is NO crdb_internal.hot_ranges SQL table)

Incidents are simulated and declared as such: nobody has a real fleet's
outage history in a hackathon. Authenticity lives in payload *shape*.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

VALID_SYSTEMS = {"airflow", "bigquery", "dbt", "cockroachdb"}
BEATS = {"counterfactual", "teach", "pollinate", "crdb", "trust"}

# Shared exception text so seed_1 and its trust-ledger repeat share a signature.
_CONN_TIMEOUT = (
    'psycopg2.OperationalError: could not connect to server: Connection timed out\n'
    '\thost "orders-db.internal" port 5432'
)


@dataclass
class Incident:
    demo_id: str        # stable label used on screen ("seed_1", "novel_airflow", ...)
    beat: str           # storyboard beat (see BEATS)
    offset_s: int       # observed_at = base_time + offset_s (deterministic ordering)
    source_system: str
    signal_type: str
    asset: str
    artifact: dict      # authentic upstream shape
    baseline: dict      # adapter-computed deviation context

    def payload(self) -> dict:
        return {
            "demo": {"id": self.demo_id, "beat": self.beat},
            "artifact": self.artifact,
            "baseline": self.baseline,
        }


# Cast in injection order. Beats: counterfactual seeds first (matched with
# memory on, flooded with memory off), then the live teach, the cross-system
# pollination, the CockroachDB-native beat, and the trust-ledger repeat.
CAST: list[Incident] = [
    # --- counterfactual stream: three known types, one per system ---
    Incident(
        "seed_1", "counterfactual", 0, "airflow", "task_failure",
        "orders_etl.load_orders",
        artifact={
            "dag_id": "orders_etl", "task_id": "load_orders",
            "dag_run_id": "scheduled__2026-07-23T02:00:00+00:00",
            "operator": "PythonOperator", "state": "failed",
            "try_number": 1, "max_tries": 3, "duration": 8.3,
            "hostname": "airflow-worker-7c9f8b6d4-x2n4k",
            "exception_class": "OperationalError",
            "exception_msg": _CONN_TIMEOUT,
            "failed_at_step": "connect",
        },
        baseline={
            "mean_duration_s": 42.1, "success_rate_60d": 0.98, "typical_try": 1,
            "window_note": "fails only 02:00-02:15 UTC (source vacuum window)",
        },
    ),
    Incident(
        "seed_2", "counterfactual", 45, "bigquery", "cost_spike",
        "analytics.marts.fct_orders",
        artifact={
            "jobReference": {"jobId": "scheduled_query_fct_orders_20260723"},
            "status": {"state": "DONE"},  # succeeded, but 39x baseline bytes
            "statistics": {"query": {
                "totalBytesProcessed": "4617089836646",
                "totalBytesBilled": "4617089836646",
                "referencedTables": [{"datasetId": "raw", "tableId": "events"}],
            }},
        },
        baseline={"median_bytes_30d": 118111600640, "ratio": 39.1, "cost_alert_gb": 500},
    ),
    Incident(
        "seed_3", "counterfactual", 90, "dbt", "test_failure",
        "jaffle_shop.stg_orders",
        artifact={
            "unique_id": "test.jaffle_shop.accepted_values_stg_orders_status__placed__shipped__completed.9a1b2c",
            "status": "fail", "failures": 3,
            "message": "Got 3 results, configured to fail if != 0",
            "relation_name": "`analytics`.`dbt_test__audit`.`accepted_values_stg_orders_status`",
            "execution_time": 0.71,
            "adapter_response": {"_message": "OK", "code": "OK", "rows_affected": 3},
        },
        baseline={"flap_frequency": "~weekly", "last_fail_days_ago": 6},
    ),
    # --- teach moment: schema drift, no precedent -> agent escalates ---
    Incident(
        "novel_airflow", "teach", 150, "airflow", "task_failure",
        "orders_etl.transform_orders",
        artifact={
            "dag_id": "orders_etl", "task_id": "transform_orders",
            "dag_run_id": "scheduled__2026-07-23T02:00:00+00:00",
            "operator": "PythonOperator", "state": "failed",
            "try_number": 2, "max_tries": 2, "duration": 51.7,  # retries exhausted: not transient
            "hostname": "airflow-worker-7c9f8b6d4-x2n4k",
            "exception_class": "KeyError",
            "exception_msg": "'customer_region'",
            "traceback_tail": (
                '  File "transform.py", line 88, in enrich\n'
                "    df = df.assign(region=df['customer_region'].map(REGION_MAP))\n"
                "KeyError: 'customer_region'"
            ),
            "columns_expected": ["order_id", "customer_id", "customer_region", "amount"],
            "columns_received": ["order_id", "customer_id", "region_code", "amount"],
        },
        baseline={"success_rate_60d": 1.0, "first_failure": True, "typical_try": 1},
    ),
    # --- cross-system pollination: same schema_drift class, other systems ---
    Incident(
        "pollinate_bq", "pollinate", 210, "bigquery", "query_failure",
        "analytics.marts.fct_orders",
        artifact={
            "jobReference": {"jobId": "scheduled_query_fct_orders_20260723_1"},
            "status": {
                "state": "DONE",
                "errorResult": {
                    "reason": "invalidQuery", "location": "query",
                    "message": "Unrecognized name: customer_region at [4:8]",
                },
                "errors": [{
                    "reason": "invalidQuery", "location": "query",
                    "message": "Unrecognized name: customer_region at [4:8]",
                }],
            },
            "statistics": {"query": {"totalBytesProcessed": "0", "totalBytesBilled": "0"}},
        },
        baseline={"success_rate_30d": 1.0, "first_failure": True},
    ),
    Incident(
        "pollinate_dbt", "pollinate", 240, "dbt", "model_error",
        "jaffle_shop.fct_orders",
        artifact={
            "unique_id": "model.jaffle_shop.fct_orders",
            "status": "error", "failures": None,
            "message": (
                "Database Error in model fct_orders (models/marts/fct_orders.sql)\n"
                '  column "customer_region" does not exist\n'
                "  LINE 12: select o.customer_region, ..."
            ),
            "relation_name": "`analytics`.`marts`.`fct_orders`",
            "execution_time": 1.42,
            "adapter_response": {"_message": "column does not exist", "code": "ERROR"},
        },
        baseline={"success_rate_30d": 1.0, "first_failure": True},
    ),
    # --- CockroachDB-native beat: hot range on the memory cluster itself ---
    Incident(
        "crdb_hot_range", "crdb", 300, "cockroachdb", "hot_range",
        "orders_db.order_events:r4213",
        artifact={
            "range_id": 4213, "node_id": 3, "store_id": 3,
            "qps": 18432.7, "writes_per_second": 15200.4, "reads_per_second": 3231.9,
            "write_bytes_per_second": 41943040.0, "read_bytes_per_second": 5242880.0,
            "cpu_time_per_second": 812000000.0,  # ns/s ~= 0.81 CPU-sec/sec
            "leaseholder_node_id": 3, "replica_node_ids": [3, 1, 5],
            "databases": ["orders_db"], "tables": ["order_events"],
            "indexes": ["order_events_pkey"],
        },
        baseline={
            "median_qps_cluster": 451.0, "ratio": 40.9,
            "p99_latency_ms_baseline": 4.2, "p99_latency_ms_now": 118.6,
        },
    ),
    # --- trust-ledger repeat: identical signature to seed_1 (N-th time) ---
    Incident(
        "trust_repeat", "trust", 360, "airflow", "task_failure",
        "orders_etl.load_orders",
        artifact={
            "dag_id": "orders_etl", "task_id": "load_orders",
            "dag_run_id": "scheduled__2026-07-24T02:00:00+00:00",
            "operator": "PythonOperator", "state": "failed",
            "try_number": 1, "max_tries": 3, "duration": 7.9,
            "hostname": "airflow-worker-7c9f8b6d4-x2n4k",
            "exception_class": "OperationalError",
            "exception_msg": _CONN_TIMEOUT,
            "failed_at_step": "connect",
        },
        baseline={
            "mean_duration_s": 42.1, "success_rate_60d": 0.98, "typical_try": 1,
            "window_note": "fails only 02:00-02:15 UTC (source vacuum window)",
        },
    ),
]


def signals(base_time: datetime, beat: str | None = None) -> list[dict]:
    """Cast as monitored_signals rows, in deterministic injection order."""
    rows = []
    for inc in sorted(CAST, key=lambda i: i.offset_s):
        if beat and inc.beat != beat:
            continue
        rows.append({
            "source_system": inc.source_system,
            "signal_type": inc.signal_type,
            "asset": inc.asset,
            "payload": inc.payload(),
            "observed_at": base_time + timedelta(seconds=inc.offset_s),
        })
    return rows


def _jsonable(rows: list[dict]) -> list[dict]:
    return [{**r, "observed_at": r["observed_at"].isoformat()} for r in rows]


def inject(base_time: datetime, beat: str | None = None) -> None:
    url = os.environ.get("COCKROACH_URL")
    if not url:
        sys.exit("COCKROACH_URL not set (see .env.example). Dry-run instead: omit --inject.")
    import psycopg  # lazy: dry-run / --check need no driver installed
    from psycopg.types.json import Jsonb

    rows = signals(base_time, beat)
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        for r in rows:
            cur.execute(
                "INSERT INTO monitored_signals "
                "(source_system, signal_type, asset, payload, observed_at) "
                "VALUES (%s, %s, %s, %s, %s)",
                (r["source_system"], r["signal_type"], r["asset"],
                 Jsonb(r["payload"]), r["observed_at"]),
            )
        conn.commit()
    print(f"injected {len(rows)} signals into monitored_signals")


def self_check() -> None:
    ids = [i.demo_id for i in CAST]
    assert len(ids) == len(set(ids)) == 8, f"expected 8 unique incidents, got {len(ids)}"
    assert {i.source_system for i in CAST} <= VALID_SYSTEMS, "unknown source_system"
    assert {i.beat for i in CAST} <= BEATS, "unknown beat"

    offsets = [i.offset_s for i in sorted(CAST, key=lambda i: i.offset_s)]
    assert offsets == sorted(set(offsets)), "offsets must be strictly increasing (deterministic order)"

    for i in CAST:
        assert set(i.payload()) == {"demo", "artifact", "baseline"}, f"{i.demo_id} bad payload keys"
        assert i.artifact, f"{i.demo_id} empty artifact"

    # cross-system schema-drift cluster must share the drifted-column token, so
    # their embedding signatures rhyme across Airflow / BigQuery / dbt.
    drift = [i for i in CAST if i.beat in {"teach", "pollinate"}]
    assert len(drift) == 3, "expected 3 schema-drift incidents"
    for i in drift:
        assert "customer_region" in json.dumps(i.artifact), f"{i.demo_id} missing drift token"

    # trust_repeat must mirror seed_1's signature (so it matches seed_1's pattern).
    s1 = next(i for i in CAST if i.demo_id == "seed_1")
    tr = next(i for i in CAST if i.demo_id == "trust_repeat")
    assert (s1.source_system, s1.signal_type, s1.artifact["exception_class"]) == \
           (tr.source_system, tr.signal_type, tr.artifact["exception_class"]), \
           "trust_repeat must mirror seed_1 signature"

    print("self-check OK: 8 incidents, deterministic order, drift cluster + trust mirror intact")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Mimir incident cast generator")
    ap.add_argument("--inject", action="store_true", help="INSERT into CockroachDB ($COCKROACH_URL)")
    ap.add_argument("--check", action="store_true", help="run self-checks and exit")
    ap.add_argument("--beat", choices=sorted(BEATS), help="limit to one storyboard beat")
    ap.add_argument("--base-time", help="ISO8601 base for observed_at (default: now, UTC)")
    args = ap.parse_args(argv)

    if args.check:
        self_check()
        return

    base_time = (datetime.fromisoformat(args.base_time)
                 if args.base_time else datetime.now(timezone.utc))

    if args.inject:
        inject(base_time, beat=args.beat)
    else:
        print(json.dumps(_jsonable(signals(base_time, args.beat)), indent=2))


if __name__ == "__main__":
    main()

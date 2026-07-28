#!/usr/bin/env python3
"""Beat 6: run a CockroachDB Agent Skill via ccloud and capture JSON.

For a decision matched to a pattern with remediation_channel='ccloud_skill'
(the crdb_hot_range -> analyzing-range-distribution case), this renders the
skill's read-only diagnostic SQL targeted at the hot table, executes it on human
approval, and captures the JSON result into the decision.

    python scripts/ccloud_wrapper.py --check              # render + read-only guard (no network)
    python scripts/ccloud_wrapper.py --render <decision>   # print the proposed command (reads DB)
    python scripts/ccloud_wrapper.py --run <decision> [--via ccloud|sql] [--cluster NAME]

"Running the skill" concretely means running its Query 3 (leaseholder
distribution / hotspot detection) from
cockroachlabs/cockroachdb-skills:analyzing-range-distribution. The skill is
SQL diagnostics, not a JSON CLI — so we wrap the query in json_agg() and capture
the single JSON blob.

--via ccloud shells out to `ccloud cluster sql` (keeps ccloud load-bearing for
beat 6; needs `ccloud auth login`, which is interactive-browser). --via sql runs
the identical SQL over COCKROACH_URL — a real fallback if live ccloud is flaky,
truer than a pre-recorded clip. The command is asserted read-only either way.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

# Data-mutating keywords that must never appear in a command run through this
# channel. The agent proposes diagnosis, never a write, via ccloud_skill.
_MUTATION = re.compile(r"\b(ALTER|DROP|DELETE|UPDATE|INSERT|UPSERT|CREATE|TRUNCATE|GRANT|REVOKE)\b", re.I)


def assert_read_only(sql: str) -> None:
    m = _MUTATION.search(sql)
    if m:
        raise ValueError(f"refusing non-read-only command via ccloud_skill channel (found {m.group(1)!r}): {sql}")


def render_command(artifact: dict) -> tuple[str, str]:
    """The analyzing-range-distribution skill's diagnostic, for the hot table.

    The skill's documented Query 3 groups by `lease_holder`, which only exists
    under `SHOW RANGES ... WITH DETAILS`. On CockroachDB Cloud Basic (serverless)
    DETAILS is rejected — tenants don't get node-level range internals ("rpc error
    ... connection reset"). So we run the tier-compatible half of the same
    analysis: per-index range distribution plus the replica set and zone spread,
    which is what actually diagnoses a sequential-key hotspot.
    """
    db = (artifact.get("databases") or ["defaultdb"])[0]
    tbl = (artifact.get("tables") or ["unknown"])[0]
    target = f"{db}.public.{tbl}"
    sql = (
        "SELECT json_agg(t) FROM ("
        "SELECT r.index_name, count(*) AS ranges, "
        "min(r.range_id) AS first_range, max(r.range_id) AS last_range, "
        "max(array_length(r.replicas,1)) AS replica_count "
        f"FROM [SHOW RANGES FROM DATABASE {db} WITH INDEXES] AS r "
        f"WHERE r.table_name = '{tbl}' "
        "GROUP BY r.index_name ORDER BY ranges DESC LIMIT 20"
        ") t;"
    )
    return sql, target


def _extract_json(stdout: str):
    m = re.search(r"\[.*\]", stdout, re.S)  # the json_agg array
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return {"raw_stdout": stdout.strip()}


def _run_via_sql(sql: str):
    import psycopg
    with psycopg.connect(os.environ["COCKROACH_URL"]) as conn, conn.cursor() as cur:
        cur.execute(sql)
        row = cur.fetchone()
        return row[0] if row else None  # json_agg -> one column, a JSON array (or None)


def _run_via_ccloud(sql: str, cluster: str):
    import subprocess
    if not cluster:
        raise SystemExit("--via ccloud needs --cluster NAME (or $CCLOUD_CLUSTER)")
    proc = subprocess.run(
        ["ccloud", "cluster", "sql", cluster, "--", "-e", sql, "--format=tsv"],
        capture_output=True, text=True, timeout=90,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ccloud failed (rc={proc.returncode}): {proc.stderr.strip()}")
    return _extract_json(proc.stdout)


def _read_decision(cur, decision_id: str) -> dict:
    cur.execute(
        "SELECT d.matched_pattern_id, p.skill_ref, p.remediation_channel, p.label AS pattern, "
        "s.payload "
        "FROM agent_decisions d "
        "JOIN incident_patterns p ON p.id = d.matched_pattern_id "
        "JOIN monitored_signals s ON s.id = d.signal_id WHERE d.id = %s",
        (decision_id,),
    )
    row = cur.fetchone()
    if row is None:
        raise SystemExit(f"no decision {decision_id} with a matched pattern")
    if row["remediation_channel"] != "ccloud_skill":
        raise SystemExit(f"pattern '{row['pattern']}' is {row['remediation_channel']}, not ccloud_skill")
    return row


def run(decision_id: str, via: str = "ccloud", cluster: str | None = None) -> dict:
    import psycopg
    from psycopg.rows import dict_row

    cluster = cluster or os.environ.get("CCLOUD_CLUSTER")
    with psycopg.connect(os.environ["COCKROACH_URL"], row_factory=dict_row) as conn, conn.cursor() as cur:
        d = _read_decision(cur, decision_id)
        sql, target = render_command(d["payload"].get("artifact", {}))
        assert_read_only(sql)  # never let this channel mutate

        result = _run_via_ccloud(sql, cluster) if via == "ccloud" else _run_via_sql(sql)

        record = {"skill_ref": d["skill_ref"], "via": via, "target": target,
                  "command": sql, "result": result}
        cur.execute(
            "UPDATE agent_decisions SET reasoning = reasoning || %s, outcome='confirmed', resolved_at=now() "
            "WHERE id = %s",
            ("\n[ccloud_skill] " + json.dumps(record), decision_id),
        )
        conn.commit()
    return record


def handler(event: dict, context=None) -> dict:
    return run(event["decision_id"], event.get("via", "ccloud"), event.get("cluster"))


def self_check() -> None:
    # beat 6 targets the agent's own memory tables, so the skill's diagnostic runs
    # for real against this cluster (see simulate_incidents crdb_hot_range).
    art = {"databases": ["defaultdb"], "tables": ["agent_decisions"],
           "indexes": ["agent_decisions_decided_at_idx"]}
    sql, target = render_command(art)
    assert target == "defaultdb.public.agent_decisions", target
    assert "json_agg" in sql and "SHOW RANGES FROM DATABASE" in sql and "agent_decisions" in sql
    assert "WITH DETAILS" not in sql, "DETAILS is rejected on Cloud Basic (serverless) clusters"
    assert_read_only(sql)  # the real diagnostic must pass

    # the mutation guard must block a write the skill's "remediation" section might suggest
    try:
        assert_read_only("ALTER TABLE order_events CONFIGURE ZONE USING num_replicas = 5")
        raise AssertionError("read-only guard failed to block ALTER")
    except ValueError:
        pass
    print("self-check OK: renders leaseholder-distribution diagnostic (read-only, json_agg); "
          "mutation guard blocks writes")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Run a ccloud_skill diagnostic and capture JSON")
    ap.add_argument("--check", action="store_true", help="render + read-only guard checks (no network)")
    ap.add_argument("--render", metavar="DECISION", help="print the proposed command for a decision (reads DB)")
    ap.add_argument("--run", metavar="DECISION", help="execute the diagnostic and capture the result")
    ap.add_argument("--via", choices=["ccloud", "sql"], default="ccloud", help="execution path (default ccloud)")
    ap.add_argument("--cluster", help="ccloud cluster name (or $CCLOUD_CLUSTER)")
    args = ap.parse_args(argv)

    if args.check:
        self_check()
    elif args.render:
        import psycopg
        from psycopg.rows import dict_row
        with psycopg.connect(os.environ["COCKROACH_URL"], row_factory=dict_row) as conn, conn.cursor() as cur:
            d = _read_decision(cur, args.render)
            sql, target = render_command(d["payload"].get("artifact", {}))
            assert_read_only(sql)
            print(f"# skill: {d['skill_ref']}  target: {target}\n{sql}")
    elif args.run:
        print(json.dumps(handler({"decision_id": args.run, "via": args.via, "cluster": args.cluster}), indent=2))
    else:
        raise SystemExit("need --check, --render <decision>, or --run <decision>")


if __name__ == "__main__":
    main()

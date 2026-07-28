#!/usr/bin/env python3
"""Mimir demo UI — a thin Flask layer over the scripts.

    ./.venv/bin/python app.py        # http://localhost:5001

No business logic lives here: every endpoint delegates to the same modules the
CLI uses (decide / respond / teach / reset_demo / ccloud_wrapper), so what a
judge clicks is exactly what the scripts do.
"""
from __future__ import annotations

import os
import sys

from flask import Flask, jsonify, render_template, request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts"))
import ccloud_wrapper  # noqa: E402
import decide  # noqa: E402
import respond  # noqa: E402
import reset_demo  # noqa: E402
import teach  # noqa: E402

app = Flask(__name__)

# The taught pattern's content is the human's worked example. Pre-filled so the
# demo is rehearsable, editable in the UI so the teach moment stays honest.
TEACH_DEFAULTS = {
    "label": "upstream-schema-drift-dropped-column",
    "failure_class": "schema_drift",
    "root_cause": ("Upstream renamed customer_region -> region_code in v3 with no deprecation. "
                   "Every consumer hard-coding the old name breaks. Schema drift - retries won't help."),
    "resolution": ("Coordinate with the producer; add a compat shim mapping region_code->customer_region "
                   "until consumers migrate; add a source schema-contract test so drift is caught at ingestion."),
    "risk_level": "high",
    "remediation_channel": "manual",
}


def db():
    import psycopg
    from psycopg.rows import dict_row
    return psycopg.connect(os.environ["COCKROACH_URL"], row_factory=dict_row)


def _q(cur, sql, args=()):
    cur.execute(sql, args)
    return cur.fetchall()


@app.get("/")
def index():
    return render_template("index.html", teach=TEACH_DEFAULTS)


@app.get("/api/state")
def state():
    """Everything the page renders, in one round trip."""
    with db() as conn, conn.cursor() as cur:
        signals = _q(cur, """
            SELECT s.id, s.source_system, s.signal_type, s.asset, s.observed_at,
                   s.payload->'demo'->>'id' AS demo_id, s.payload->'demo'->>'beat' AS beat,
                   d.id AS decision_id, d.action, d.similarity, d.reasoning,
                   d.human_response, d.memory_enabled, p.label AS matched_label,
                   p.risk_level, p.remediation_channel, p.skill_ref, d.matched_pattern_id
            FROM monitored_signals s
            LEFT JOIN LATERAL (
                SELECT * FROM agent_decisions x WHERE x.signal_id = s.id
                ORDER BY x.decided_at DESC LIMIT 1) d ON true
            LEFT JOIN incident_patterns p ON p.id = d.matched_pattern_id
            ORDER BY s.observed_at""")
        runbook = _q(cur, """
            SELECT p.id, p.label, p.failure_class, p.applies_to, p.risk_level, p.root_cause,
                   p.resolution, p.confirm_count AS times_reused, p.approved_unchanged_count,
                   p.rejected_count, p.autonomy_granted, p.autonomy_revoked_at, p.source
            FROM incident_patterns p ORDER BY p.confirm_count DESC""")
        # latest decision PER SIGNAL per mode — re-deciding a signal (the pollination
        # beat) must not inflate the denominator and make memory look worse.
        counterfactual = _q(cur, """
            SELECT memory_enabled, count(*) AS n,
                   count(*) FILTER (WHERE action='escalated') AS escalated
            FROM (
              SELECT DISTINCT ON (signal_id, memory_enabled) memory_enabled, action
              FROM agent_decisions
              ORDER BY signal_id, memory_enabled, decided_at DESC
            ) latest
            GROUP BY memory_enabled ORDER BY memory_enabled DESC""")
        # which pattern is one approval away from earning autonomy
        asks = [r for r in runbook
                if respond.autonomy_ask_eligible(r["risk_level"], r["approved_unchanged_count"],
                                                 r["rejected_count"], r["autonomy_granted"])]
    return jsonify(signals=signals, runbook=runbook, counterfactual=counterfactual,
                   autonomy_asks=[a["id"] for a in asks],
                   threshold=decide.MATCH_MAX_DISTANCE)


@app.post("/api/reset")
def api_reset():
    reset_demo.reset()
    return jsonify(ok=True, message="baseline restored: patterns re-seeded, cast re-injected")


@app.post("/api/decide")
def api_decide():
    memory = bool(request.json.get("memory_enabled", True))
    only = request.json.get("demo_ids")  # optional subset, for the pollination beat
    with db() as conn, conn.cursor() as cur:
        if only:
            cur.execute("SELECT id, source_system, signal_type, asset, payload FROM monitored_signals "
                        "WHERE payload->'demo'->>'id' = ANY(%s::STRING[]) ORDER BY observed_at", (only,))
        else:
            cur.execute("SELECT id, source_system, signal_type, asset, payload FROM monitored_signals "
                        "ORDER BY observed_at")
        results = [decide.decide(cur, s, memory) for s in cur.fetchall()]
        conn.commit()
    return jsonify(ok=True, decided=len(results))


@app.post("/api/respond")
def api_respond():
    with db() as conn, conn.cursor() as cur:
        out = respond.respond(cur, request.json["decision_id"], request.json["response"],
                              request.json.get("modified_text"))
        conn.commit()
    return jsonify(ok=True, **{k: v for k, v in out.items() if k != "pattern_id"})


@app.post("/api/grant")
def api_grant():
    with db() as conn, conn.cursor() as cur:
        out = respond.grant_autonomy(cur, request.json["pattern_id"])
        conn.commit()
    return jsonify(ok=True, **out)


@app.post("/api/teach")
def api_teach():
    body = {**TEACH_DEFAULTS, **request.json}
    with db() as conn, conn.cursor() as cur:
        out = teach.teach(cur, body["decision_id"], body["label"], body["failure_class"],
                          body["root_cause"], body["resolution"], body["risk_level"],
                          body["remediation_channel"], body.get("skill_ref"))
        conn.commit()
    return jsonify(ok=True, **out)


@app.post("/api/ccloud")
def api_ccloud():
    """Beat 6: run the CockroachDB Agent Skill's read-only diagnostic."""
    decision_id = request.json["decision_id"]
    via = request.json.get("via", "sql")  # sql path needs no interactive ccloud auth
    try:
        return jsonify(ok=True, **ccloud_wrapper.run(decision_id, via=via))
    except Exception as e:  # surface the failure rather than a blank panel
        return jsonify(ok=False, error=f"{type(e).__name__}: {e}"), 500


@app.get("/api/proof")
def api_proof():
    """The 'this is really CockroachDB' panel: real queries, real results."""
    queries = [
        # same DISTINCT ON as /api/state so the panel can never contradict the headline
        ("counterfactual — escalation rate with vs without memory",
         "SELECT memory_enabled, count(*) AS decisions, "
         "count(*) FILTER (WHERE action='escalated') AS escalated, "
         "round(100.0*count(*) FILTER (WHERE action='escalated')/count(*),0) AS pct FROM ("
         "SELECT DISTINCT ON (signal_id, memory_enabled) memory_enabled, action "
         "FROM agent_decisions ORDER BY signal_id, memory_enabled, decided_at DESC"
         ") latest GROUP BY memory_enabled ORDER BY memory_enabled DESC"),
        ("cross-system pollination — one lesson, N systems",
         "SELECT label, failure_class, applies_to, array_length(applies_to,1) AS systems, source "
         "FROM incident_patterns WHERE source='promoted' OR array_length(applies_to,1) > 1"),
        ("vector index — the memory itself",
         "SELECT label, vector_dims(embedding) AS dims, risk_level, confirm_count "
         "FROM incident_patterns ORDER BY confirm_count DESC LIMIT 5"),
        ("trust ledger — autonomy earned by track record",
         "SELECT label, approved_unchanged_count AS approvals, rejected_count AS rejections, "
         "autonomy_granted, autonomy_revoked_at IS NOT NULL AS was_revoked "
         "FROM incident_patterns ORDER BY approved_unchanged_count DESC LIMIT 5"),
    ]
    out = []
    with db() as conn, conn.cursor() as cur:
        for title, sql in queries:
            try:
                out.append({"title": title, "sql": sql, "rows": _q(cur, sql)})
            except Exception as e:
                out.append({"title": title, "sql": sql, "error": str(e)})
    return jsonify(queries=out)


if __name__ == "__main__":
    if not os.environ.get("COCKROACH_URL"):
        sys.exit("COCKROACH_URL not set — run: set -a; . ./.env; set +a")
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5001")), debug=False)

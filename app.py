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
import uuid
import hmac
from urllib.parse import urlencode
from concurrent.futures import ThreadPoolExecutor

from flask import Flask, jsonify, redirect, render_template, request, send_from_directory

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts"))

# `sslmode=verify-full` makes libpq look for ~/.postgresql/root.crt, which exists on a
# developer machine (the Cloud console tells you to download it) but not in a serverless
# sandbox — connections there fail with "root certificate file ... does not exist".
# `sslrootcert=system` does NOT work either: CockroachDB Cloud signs with its own CA, not
# a publicly-trusted one, so the OS trust store rejects it ("certificate verify failed").
# So the cluster CA travels with the code. It is a public certificate — no private key —
# fetched from the same unauthenticated URL the Cloud console gives you. Normalised here,
# before the scripts are imported, so every module reading COCKROACH_URL is corrected.
def _ca_path() -> str | None:
    """Where to find the cluster CA, in preference order.

    1. `COCKROACH_CA_PEM` — the certificate as an env var, materialised to /tmp. Keeps
       it out of the repo; the only writable path in a serverless sandbox is /tmp.
    2. `certs/cockroach-ca.crt` — a committed copy, for local dev or a self-hosted run.
    3. None — fall through to libpq's own default (~/.postgresql/root.crt), which is
       what a developer machine already has.
    """
    pem = os.environ.get("COCKROACH_CA_PEM", "").strip()
    if pem:
        tmp = "/tmp/cockroach-ca.crt"
        if not os.path.exists(tmp):
            # tolerate a value pasted with literal \n instead of real newlines
            with open(tmp, "w") as fh:
                fh.write(pem.replace("\\n", "\n") + "\n")
        return tmp
    bundled = os.path.join(os.path.dirname(os.path.abspath(__file__)), "certs", "cockroach-ca.crt")
    return bundled if os.path.exists(bundled) else None


_CA = _ca_path()
_url = os.environ.get("COCKROACH_URL", "")
if _url and "sslrootcert=" not in _url and _CA:
    os.environ["COCKROACH_URL"] = _url + ("&" if "?" in _url else "?") + f"sslrootcert={_CA}"

import ccloud_wrapper  # noqa: E402
import decide  # noqa: E402
import respond  # noqa: E402
import reset_demo  # noqa: E402
import teach  # noqa: E402

_ROOT = os.path.dirname(os.path.abspath(__file__))
# explicit absolute template path: on Vercel this module is imported from api/index.py,
# so Flask's default module-relative lookup is not something to rely on.
app = Flask(__name__, template_folder=os.path.join(_ROOT, "templates"))

# --- abuse guards for the public demo URL -----------------------------------------
# Judges must be able to click the beats without credentials, so this is rate limiting
# rather than auth. Two layers, because they fail differently:
#
#   burst  — per-instance memory. Cheap, catches hammering, but on serverless each
#            instance has its own copy and a cold start wipes it. Not a real ceiling.
#   daily  — a counter in CockroachDB. Durable, shared across every instance, and the
#            actual cap on how much Bedrock a stranger can spend. Applied only to the
#            endpoints that invoke a model.
#
# An AWS budget action is the slow backstop underneath both (billing data lags hours),
# so it cannot be the gate — this is.
_HITS: dict[str, list[float]] = {}
BURST_LIMIT = int(os.environ.get("WRITE_LIMIT_PER_MIN", "20"))
DAILY_GLOBAL = int(os.environ.get("MODEL_CALLS_PER_DAY", "500"))     # ~60 full demo runs
DAILY_PER_IP = int(os.environ.get("MODEL_CALLS_PER_DAY_PER_IP", "100"))
MODEL_ENDPOINTS = {"/api/reset", "/api/decide", "/api/teach"}  # these call Bedrock

# Optional passcode. Unset (the default) leaves the app fully open, so local dev and any
# existing deployment keep working untouched; set DEMO_PASSCODE in the Vercel dashboard to
# turn it on. It gates only the endpoints that MUTATE the demo — reading is always free, so
# the app still loads and tells its story to anyone.
#
# The real risk here isn't Bedrock spend (the counters above cap that); it's that demo state
# is global, so one stranger mid-run leaves the board looking broken for the next visitor.
# Judges get a ?key=... link rather than a passcode to type: one click, cookie set, clean URL
# from then on. A wall you have to type at is a wall some judge bounces off.
DEMO_PASSCODE = os.environ.get("DEMO_PASSCODE", "").strip()
MUTATING_ENDPOINTS = MODEL_ENDPOINTS | {"/api/respond", "/api/grant", "/api/ccloud"}
_COOKIE = "mimir_key"


def _has_key() -> bool:
    """True when this request carries the passcode, by cookie or header.

    Both sources are checked independently: `cookie or header` would let a stale
    cookie (left over from a rotated passcode) mask a valid header and 401 the
    documented scripted path.
    """
    return any(hmac.compare_digest(v, DEMO_PASSCODE) for v in
               (request.cookies.get(_COOKIE, ""), request.headers.get("X-Demo-Passcode", "")) if v)


def _bump(cur, bucket: str) -> int:
    """Atomically increment today's counter and return the new value."""
    cur.execute(
        "INSERT INTO usage_counters (day, bucket, n) VALUES (current_date(), %s, 1) "
        "ON CONFLICT (day, bucket) DO UPDATE SET n = usage_counters.n + 1 RETURNING n",
        (bucket,),
    )
    return cur.fetchone()["n"]


@app.before_request
def _guard():
    if request.method != "POST":
        return None
    if DEMO_PASSCODE and request.path in MUTATING_ENDPOINTS and not _has_key():
        return jsonify(ok=False, needs_key=True,
                       error="This demo is running with a reviewer key. Open the link from "
                             "the submission (it ends in ?key=...) and the controls unlock."), 401
    ip = (request.headers.get("x-forwarded-for", "") or request.remote_addr or "?").split(",")[0].strip()

    import time
    now = time.time()
    recent = [t for t in _HITS.get(ip, []) if now - t < 60]
    if len(recent) >= BURST_LIMIT:
        return jsonify(ok=False, error=f"Slow down — {BURST_LIMIT} actions per minute."), 429
    recent.append(now)
    _HITS[ip] = recent

    if request.path not in MODEL_ENDPOINTS:
        return None
    try:
        with db() as conn, conn.cursor() as cur:
            per_ip = _bump(cur, f"ip:{ip}")
            total = _bump(cur, "global")
            conn.commit()
    except Exception:  # never let the meter itself take the demo down
        app.logger.exception("usage counter unavailable; allowing request")
        return None
    if per_ip > DAILY_PER_IP:
        return jsonify(ok=False, error=f"Daily limit reached for this address "
                                       f"({DAILY_PER_IP} model-backed actions). Resets at UTC midnight."), 429
    if total > DAILY_GLOBAL:
        return jsonify(ok=False, error=f"The demo's shared daily budget ({DAILY_GLOBAL} model-backed "
                                       "actions) is spent. Resets at UTC midnight."), 429
    return None

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


@app.errorhandler(Exception)
def _json_errors(e):
    """Return the failure as JSON. A blank 500 tells a judge nothing, and tells us
    nothing either — the UI surfaces this text in its toast."""
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException):
        return jsonify(ok=False, error=e.description), e.code
    # Do NOT return str(e): psycopg embeds the cluster hostname and every resolved IP in
    # its connection errors, and this endpoint is public. Full detail goes to the log;
    # the client gets the exception type and an id to quote.
    ref = uuid.uuid4().hex[:8]
    app.logger.exception("unhandled [%s]", ref)
    return jsonify(ok=False, error=f"{type(e).__name__} (ref {ref}) — see server logs"), 500


@app.before_request
def _reviewer_link():
    """Exchange ?key=... for a cookie, then redirect to the clean URL.

    Two reasons this is a redirect rather than an after_request hook. The page is
    rendered before an after_request runs, so the first click on a reviewer link
    would have rendered the read-only notice despite the key being valid — the exact
    bad first impression the link was meant to avoid. And stripping the key from the
    URL keeps it out of the address bar, out of the Referer of every later request,
    and out of anything the reviewer copies. It is still a long-lived passcode rather
    than a single-use token, and it will appear in this app's own access log; for a
    gate whose worst case is resetting a demo board, that is a deliberate trade.
    """
    if not DEMO_PASSCODE or request.method != "GET":
        return None
    supplied = request.args.get("key", "")
    if not supplied or not hmac.compare_digest(supplied, DEMO_PASSCODE):
        return None
    rest = {k: v for k, v in request.args.items(multi=True) if k != "key"}
    target = request.path + (("?" + urlencode(rest)) if rest else "")
    resp = redirect(target, code=303)
    resp.set_cookie(_COOKIE, DEMO_PASSCODE, max_age=60 * 60 * 24 * 30,
                    httponly=True, samesite="Lax",
                    secure=request.headers.get("x-forwarded-proto") == "https")
    return resp


@app.get("/")
def dashboard():
    """The operator view — what an on-call engineer would actually keep open."""
    return render_template("dashboard.html", teach=TEACH_DEFAULTS,
                           locked=bool(DEMO_PASSCODE) and not _has_key())


@app.get("/demo")
def demo_console():
    """The original guided console. Kept as a verified fallback."""
    return render_template("index.html", teach=TEACH_DEFAULTS)


@app.get("/tutorial")
def tutorial():
    """The engineering walk-through, served from the app so the link needs no login.

    It lived as a private hosted artifact, which meant the README pointed judges at a
    URL only its author could open. Static file, no DB touch, no rate limit.
    """
    return send_from_directory(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs"),
        "tutorial.html",
    )


@app.get("/api/state")
def state():
    """Everything the page renders, in one round trip."""
    with db() as conn, conn.cursor() as cur:
        signals = _q(cur, """
            SELECT s.id, s.source_system, s.signal_type, s.asset, s.observed_at, s.payload,
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
        signals = cur.fetchall()

    # Each decision does an embedding call plus (on a match) a reasoning call, so
    # sequentially this took ~13s for 8 signals — long enough to read as a sluggish
    # agent on camera and to threaten a serverless request timeout. One connection
    # per signal lets them run concurrently; wall time becomes the slowest single
    # decision. Each thread owns its connection, so no cursor is shared.
    def one(signal):
        with db() as c, c.cursor() as cur2:
            out = decide.decide(cur2, signal, memory)
            c.commit()
            return out

    with ThreadPoolExecutor(max_workers=min(8, len(signals) or 1)) as pool:
        results = list(pool.map(one, signals))
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

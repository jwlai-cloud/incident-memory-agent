#!/usr/bin/env python3
"""Incident signature -> AWS Bedrock Titan embedding.

One signature function, shared by seeding (seed_patterns.py) and live decisions
(decide.py), so patterns and signals land in the same 512-d space.

    python scripts/embed.py --check              # self-checks (no network)
    python scripts/embed.py --demo-id novel_airflow   # print the signature (no network)
    python scripts/embed.py --demo-id seed_1 --embed  # + call Bedrock, print the vector

The signature is a normalized natural-language line built from a signal's
artifact + baseline. It leads with a system-agnostic *symptom* so that the same
failure class rhymes across Airflow / BigQuery / dbt in embedding space (the
cross-system pollination the demo turns on) — while keeping per-system detail,
so matching is genuine semantic similarity, not string equality.

Bedrock: amazon.titan-embed-text-v2:0, dimensions=512, normalize=true (unit
vectors -> cosine distance). Store into a VECTOR(512) column as a '[..]' string
literal; match with `ORDER BY embedding <=> %s LIMIT k` (schema index uses
vector_cosine_ops).
"""
from __future__ import annotations

import argparse
import json
import os
import re
from functools import lru_cache

MODEL_ID = "amazon.titan-embed-text-v2:0"
EMBED_DIMS = 512


# --- per-(system, signal_type) feature extractors: (artifact, baseline) -> (symptom, deviation) ---

def _airflow_task_failure(art: dict, base: dict) -> tuple[str, str]:
    exc = art.get("exception_class", "")
    expected, received = art.get("columns_expected"), art.get("columns_received")
    if expected and received and expected != received:
        missing = [c for c in expected if c not in received] or ["?"]
        added = [c for c in received if c not in expected]
        symptom = (f"schema drift: expected column '{missing[0]}' missing from upstream data "
                   f"(received {added or received}); {exc} in {art.get('task_id', 'task')}")
        dev = "first occurrence, retries exhausted" if base.get("first_failure") else "retries exhausted"
        return symptom, dev
    # transient / operational failure — kept qualitative so a repeat (trust_repeat)
    # produces an identical signature to the original (seed_1) and matches it hard.
    first_line = (art.get("exception_msg", "").splitlines() or [""])[0]
    symptom = first_line or exc or "task failed"
    dev = f"transient connect failure, recovers on retry; {base.get('window_note', '')}".strip("; ")
    return symptom, dev


def _bq_cost_spike(art: dict, base: dict) -> tuple[str, str]:
    q = art.get("statistics", {}).get("query", {})
    processed = int(q.get("totalBytesProcessed", "0"))
    ratio = base.get("ratio")
    symptom = (f"cost spike: query scanned {_human_bytes(processed)}"
               + (f" ({ratio}x median)" if ratio else "")
               + ", likely full scan / dropped partition filter")
    med = base.get("median_bytes_30d")
    dev = (f"{ratio}x median bytes" + (f" ({_human_bytes(med)} baseline)" if med else "")) if ratio else ""
    return symptom, dev


def _bq_query_failure(art: dict, base: dict) -> tuple[str, str]:
    err = art.get("status", {}).get("errorResult", {})
    reason, msg = err.get("reason", ""), err.get("message", "")
    col = _re_col(r"Unrecognized name:?\s+([A-Za-z_]\w*)", msg) or _re_col(r"Name (\w+) not found", msg)
    if col:
        symptom = f"schema drift: column '{col}' not found - BigQuery {reason}, unrecognized name"
    else:
        symptom = f"BigQuery {reason}: {msg}"
    return symptom, "first failure" if base.get("first_failure") else ""


def _dbt_test_failure(art: dict, base: dict) -> tuple[str, str]:
    symptom = f"data quality: {_dbt_test_type(art.get('unique_id', ''))} test failed ({art.get('failures')} rows)"
    dev = ""
    if base.get("flap_frequency"):
        dev = f"recurring ({base['flap_frequency']})"
        if base.get("last_fail_days_ago") is not None:
            dev += f", last {base['last_fail_days_ago']}d ago"
    return symptom, dev


def _dbt_model_error(art: dict, base: dict) -> tuple[str, str]:
    msg = art.get("message", "")
    col = _re_col(r'column "([^"]+)" does not exist', msg)
    if col:
        symptom = f"schema drift: column '{col}' does not exist - dbt model build error"
    else:
        symptom = f"dbt model build error: {(msg.splitlines() or ['error'])[0]}"
    return symptom, "first failure" if base.get("first_failure") else ""


def _crdb_hot_range(art: dict, base: dict) -> tuple[str, str]:
    tbl = (art.get("tables") or ["?"])[0]
    idx = (art.get("indexes") or ["?"])[0]
    symptom = (f"hot range: single-range write hotspot on {tbl} via {idx} "
               f"(qps {float(art.get('qps', 0)):.0f}), likely sequential/monotonic key")
    ratio = base.get("ratio")
    dev = ""
    if ratio:
        dev = f"{ratio}x median QPS"
        if base.get("p99_latency_ms_baseline") and base.get("p99_latency_ms_now"):
            dev += f", p99 {base['p99_latency_ms_baseline']}->{base['p99_latency_ms_now']}ms"
    return symptom, dev


def _generic(art: dict, base: dict) -> tuple[str, str]:
    return str(art.get("status") or art.get("state") or "signal"), ""


_EXTRACTORS = {
    ("airflow", "task_failure"): _airflow_task_failure,
    ("bigquery", "cost_spike"): _bq_cost_spike,
    ("bigquery", "query_failure"): _bq_query_failure,
    ("dbt", "test_failure"): _dbt_test_failure,
    ("dbt", "model_error"): _dbt_model_error,
    ("cockroachdb", "hot_range"): _crdb_hot_range,
}


def _re_col(pattern: str, text: str) -> str | None:
    m = re.search(pattern, text or "")
    return m.group(1) if m else None


def _human_bytes(n) -> str:
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if n < 1024 or unit == "PB":
            return f"{int(n)}B" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024


def _dbt_test_type(unique_id: str) -> str:
    parts = unique_id.split(".")
    name = parts[2] if len(parts) > 2 else unique_id
    for p in ("accepted_values", "not_null", "unique", "relationships"):
        if name.startswith(p):
            return p.replace("_", " ")
    return "generic"


# --- public API ---

def signature(signal: dict) -> str:
    """Canonical signature string for a monitored_signals row.

    `signal` = {source_system, signal_type, asset, payload:{artifact, baseline}}.
    Pure and deterministic; no network. embed.py's own villain: get this right
    and pollination works; get it wrong and nothing matches across systems.
    """
    system, stype, asset = signal["source_system"], signal["signal_type"], signal["asset"]
    payload = signal.get("payload", {})
    symptom, deviation = _EXTRACTORS.get((system, stype), _generic)(
        payload.get("artifact", {}), payload.get("baseline", {}))
    parts = [symptom.rstrip("."), f"source={system}, signal={stype}, asset={asset}"]
    if deviation:
        parts.append(deviation)
    return ". ".join(parts) + "."


_client = None  # cached across warm Lambda invocations


def _bedrock():
    global _client
    if _client is None:
        import boto3  # lazy: signature() and --check need no boto3 / no creds
        _client = boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    return _client


@lru_cache(maxsize=256)
def embed(text: str) -> list[float]:
    """Titan v2 embedding (512 unit-normalized floats) for a signature string.

    Cached: signatures are deterministic, so the UI re-deciding the same cast
    repeatedly costs one Bedrock call per distinct signature, not per click.
    """
    resp = _bedrock().invoke_model(
        body=json.dumps({"inputText": text, "dimensions": EMBED_DIMS, "normalize": True}),
        modelId=MODEL_ID, accept="application/json", contentType="application/json")
    vec = json.loads(resp["body"].read())["embedding"]
    if len(vec) != EMBED_DIMS:
        raise ValueError(f"expected {EMBED_DIMS} dims, got {len(vec)}")
    return vec


def embed_signal(signal: dict) -> list[float]:
    return embed(signature(signal))


def to_vector_literal(vec: list[float]) -> str:
    """Format a float list for a CockroachDB VECTOR column: '[0.1,0.2,...]'."""
    return "[" + ",".join(map(repr, vec)) + "]"


def _signal_from_incident(inc) -> dict:
    return {"source_system": inc.source_system, "signal_type": inc.signal_type,
            "asset": inc.asset, "payload": inc.payload()}


def self_check() -> dict:
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from simulate_incidents import CAST  # test-only coupling: verify signatures on the real cast

    sigs = {inc.demo_id: signature(_signal_from_incident(inc)) for inc in CAST}

    # cross-system schema-drift trio must share the entity + the concept.
    for did in ("novel_airflow", "pollinate_bq", "pollinate_dbt"):
        assert "customer_region" in sigs[did], f"{did}: lost the drifted-column entity"
        assert "schema drift" in sigs[did].lower(), f"{did}: lost the drift concept"

    # a repeat of a known incident must reduce to the same signature (so trust_repeat
    # matches seed_1's pattern hard, driving the trust-ledger ask).
    assert sigs["seed_1"] == sigs["trust_repeat"], "seed_1 and trust_repeat must share a signature"

    # transient (seed_1) and schema-drift (novel_airflow) are both airflow task_failure
    # but must NOT collapse together.
    assert sigs["seed_1"] != sigs["novel_airflow"], "transient vs schema-drift must differ"

    for inc in CAST:
        assert signature(_signal_from_incident(inc)) == sigs[inc.demo_id], "signature not deterministic"
        assert sigs[inc.demo_id].strip(), f"{inc.demo_id}: empty signature"

    print("self-check OK: drift trio shares entity+concept, seed_1==trust_repeat, transient!=drift, deterministic")
    return sigs


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Incident signature + Titan embedding")
    ap.add_argument("--check", action="store_true", help="run self-checks and exit (no network)")
    ap.add_argument("--demo-id", help="print the signature for a cast incident (no network)")
    ap.add_argument("--embed", action="store_true", help="also call Bedrock and print the vector (needs AWS creds)")
    args = ap.parse_args(argv)

    if args.check or not args.demo_id:
        self_check()
        return

    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from simulate_incidents import CAST
    inc = next((i for i in CAST if i.demo_id == args.demo_id), None)
    if inc is None:
        raise SystemExit(f"unknown --demo-id {args.demo_id!r}; try: " + ", ".join(i.demo_id for i in CAST))

    sig = signature(_signal_from_incident(inc))
    print(f"[{inc.demo_id}] {sig}")
    if args.embed:
        vec = embed(sig)
        print(f"dims={len(vec)} first5={[round(x, 4) for x in vec[:5]]}")
        print("vector_literal=" + to_vector_literal(vec)[:60] + "...")


if __name__ == "__main__":
    main()

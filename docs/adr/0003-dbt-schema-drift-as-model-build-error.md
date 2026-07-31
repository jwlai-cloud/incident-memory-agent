# 0003 — dbt schema-drift manifests as a model build error

- Status: Accepted
- Date: 2026-07-23

## Context

The cross-system pollination demo teaches a schema-drift pattern from an Airflow
incident, then catches its cousins in BigQuery and dbt. For the dbt cousin
(`pollinate_dbt`, dropped/renamed `customer_region`), there were two authentic
manifestations: a `not_null` **data test failure** on the column, or a **model
build error** when a model selects the dropped column.

## Decision

Use the **model build error** (`run_results.json` `status:"error"`,
`failures:null`, message `column "customer_region" does not exist`,
`signal_type='model_error'`).

## Consequences

- Stronger literal rhyme with the Airflow `KeyError` and BigQuery
  "Unrecognized name" → tighter clustering in embedding space for the
  schema-drift class.
- Semantically truer: a *dropped/renamed* column makes a downstream model fail
  to compile, whereas a `not_null` failure implies the column exists but is null
  (a different failure class — data quality, which is what `seed_3` already is).
- `docs/DEMO_SCRIPT.md` labelled `pollinate_dbt` a "test failure"; the HANDOVER
  dbt bullet was corrected to reflect `run_results.json` / model build error.
- Rejected: `not_null` test failure — looser semantic fit and it would collide
  with the existing `data_quality` seed pattern.

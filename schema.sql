-- Incident memory agent — CockroachDB schema
-- Memory layer for a cross-system incident triage agent
-- (Airflow / BigQuery / dbt / CockroachDB-native incidents).

CREATE TABLE IF NOT EXISTS monitored_signals (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_system STRING NOT NULL,      -- 'airflow' / 'bigquery' / 'dbt' / 'cockroachdb'
  signal_type STRING NOT NULL,        -- 'task_failure' / 'cost_spike' / 'test_failure' / 'hot_range' / ...
  asset STRING NOT NULL,              -- DAG.task, project.dataset.table, model/test name, or cluster/range id
  payload JSONB NOT NULL,             -- realistic raw error/metric detail (see scripts/simulate_incidents.py)
  observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  INDEX (source_system, observed_at)
);

CREATE TABLE IF NOT EXISTS incident_patterns (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  label STRING NOT NULL,              -- e.g. 'upstream-schema-drift', 'transient-quota-exhaustion'
  failure_class STRING NOT NULL,      -- the cross-system generalization, e.g. 'schema_drift', 'resource_exhaustion'
  embedding VECTOR(512) NOT NULL,
  applies_to STRING[] NOT NULL,       -- source systems this pattern has been seen/confirmed in
  root_cause STRING NOT NULL,         -- human-written at teach-time (the "rationale" — feeds the reasoning call)
  resolution STRING NOT NULL,         -- human-written resolution steps
  remediation_channel STRING NOT NULL, -- 'airflow_adapter' / 'bigquery_adapter' / 'ccloud_skill' / 'manual'
  skill_ref STRING,                   -- for ccloud_skill: which Agent Skill from the CockroachDB skills repo
  risk_level STRING NOT NULL DEFAULT 'low',  -- 'low' = proposable, 'high' = always full human diagnosis

  -- feedback / decay
  confidence FLOAT8 NOT NULL DEFAULT 0.7,
  confirm_count INT8 NOT NULL DEFAULT 0,
  refute_count INT8 NOT NULL DEFAULT 0,

  -- TRUST LEDGER: memory about the human-agent relationship, per pattern.
  -- Approving the agent's proposal unchanged earns autonomy; rejecting or
  -- modifying it spends autonomy. Autonomy is earned, visible, and revocable.
  approved_unchanged_count INT8 NOT NULL DEFAULT 0,
  modified_count INT8 NOT NULL DEFAULT 0,
  rejected_count INT8 NOT NULL DEFAULT 0,
  autonomy_granted BOOL NOT NULL DEFAULT false,   -- set only by explicit human pre-authorization
  autonomy_granted_at TIMESTAMPTZ,
  autonomy_revoked_at TIMESTAMPTZ,                -- one rejection after grant auto-revokes

  first_seen TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_confirmed_at TIMESTAMPTZ,
  source STRING NOT NULL DEFAULT 'seed',          -- 'seed' or 'promoted' (taught live)
  -- cosine metric declared via opclass at index creation; matched with the <=>
  -- operator. Requires: SET CLUSTER SETTING feature.vector_index.enabled = true;
  VECTOR INDEX (embedding vector_cosine_ops)
);

CREATE TABLE IF NOT EXISTS agent_decisions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  signal_id UUID REFERENCES monitored_signals(id),
  matched_pattern_id UUID REFERENCES incident_patterns(id),
  similarity FLOAT8,
  action STRING NOT NULL,             -- 'auto_resolved' / 'proposed' / 'escalated' / 'ignored'
  memory_enabled BOOL NOT NULL DEFAULT true,  -- false during the memoryless counterfactual demo
  reasoning STRING NOT NULL,
  decided_at TIMESTAMPTZ NOT NULL DEFAULT now(),

  -- human response to a proposal (the trust ledger's raw material)
  human_response STRING,              -- NULL / 'approved_unchanged' / 'modified' / 'rejected'
  outcome STRING,                     -- NULL / 'confirmed' / 'refuted'
  resolved_at TIMESTAMPTZ,
  INDEX (decided_at),
  INDEX (action, outcome),
  INDEX (memory_enabled, decided_at)  -- for the day-1-vs-now counterfactual comparison query
);

-- The self-writing runbook is a VIEW, not a table — documentation as a
-- side effect of using the tool, always current, never manually edited.
CREATE VIEW IF NOT EXISTS runbook AS
SELECT
  p.label,
  p.failure_class,
  p.applies_to,
  p.root_cause,
  p.resolution,
  p.risk_level,
  p.confidence,
  p.confirm_count AS times_reused,
  p.approved_unchanged_count,
  p.autonomy_granted,
  p.source,
  p.first_seen,
  p.last_confirmed_at
FROM incident_patterns AS p
ORDER BY p.confirm_count DESC;

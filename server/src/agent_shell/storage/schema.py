from __future__ import annotations


SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA secure_delete = ON;

-- The application database owns operational diagnostics only. LangGraph Dev
-- owns Assistant, Thread, Run, State, history, and Store persistence.
DROP TABLE IF EXISTS runtime_command_observations;
DROP TABLE IF EXISTS runtime_model_requests;
DROP TABLE IF EXISTS runtime_protocol_events;
DROP TABLE IF EXISTS runtime_run_graphs;
DROP TABLE IF EXISTS runtime_node_attempts;
DROP TABLE IF EXISTS runtime_run_monitoring;
DROP TABLE IF EXISTS runtime_workflow_runs;
DROP TABLE IF EXISTS runtime_lifecycles;
DROP TABLE IF EXISTS workflow_model_requests;
DROP TABLE IF EXISTS workflow_protocol_events;
DROP TABLE IF EXISTS workflow_run_events;
DROP TABLE IF EXISTS workflow_run_records;
DROP TABLE IF EXISTS workflow_lifecycles;
DROP TABLE IF EXISTS workflow_runs;
DROP TABLE IF EXISTS agent_session_run_outputs;
DROP TABLE IF EXISTS agent_session_runs;
DROP TABLE IF EXISTS api_message_history_outputs;
DROP TABLE IF EXISTS api_message_history;
DROP TABLE IF EXISTS media_output_assets;
DROP TABLE IF EXISTS runtime_diagnostics;

CREATE TABLE IF NOT EXISTS runtime_diagnostic_events (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    diagnostic_id TEXT NOT NULL UNIQUE,
    occurred_at TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('warning', 'error')),
    code TEXT NOT NULL CHECK (length(code) > 0),
    summary TEXT NOT NULL,
    component TEXT NOT NULL CHECK (
        component IN (
            'api', 'workflow_runtime',
            'persistence', 'observability', 'security'
        )
    ),
    request_id TEXT,
    lifecycle_id TEXT,
    run_id TEXT,
    thread_id TEXT,
    entry_workflow_id TEXT,
    entry_workflow_name TEXT,
    subject_kind TEXT CHECK (
        subject_kind IS NULL OR subject_kind IN (
            'workflow', 'agent', 'workflow_node', 'model', 'tool',
            'api', 'persistence'
        )
    ),
    subject_id TEXT,
    subject_name TEXT,
    workflow_node_id TEXT,
    node_invocation_id TEXT,
    exception_type TEXT,
    detail_available INTEGER NOT NULL CHECK (detail_available IN (0, 1))
);

CREATE INDEX IF NOT EXISTS idx_runtime_diagnostic_events_occurred
ON runtime_diagnostic_events(occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_runtime_diagnostic_events_request
ON runtime_diagnostic_events(request_id);

CREATE INDEX IF NOT EXISTS idx_runtime_diagnostic_events_lifecycle
ON runtime_diagnostic_events(lifecycle_id, occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_runtime_diagnostic_events_run
ON runtime_diagnostic_events(run_id, occurred_at DESC);
"""

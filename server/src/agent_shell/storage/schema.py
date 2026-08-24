from __future__ import annotations

SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA secure_delete = ON;

-- Removed legacy single-agent/API history. There is no user data contract to migrate yet.
DROP TABLE IF EXISTS agent_session_run_outputs;
DROP TABLE IF EXISTS agent_session_runs;
DROP TABLE IF EXISTS api_message_history_outputs;
DROP TABLE IF EXISTS api_message_history;
DROP TABLE IF EXISTS workflow_runs;

-- Runtime diagnostics are operational failure records, not successful Run history.
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
            'api', 'workflow_runtime', 'background_runtime',
            'persistence', 'observability', 'security'
        )
    ),
    request_id TEXT,
    lifecycle_id TEXT,
    run_id TEXT,
    thread_id TEXT,
    parent_workflow_id TEXT,
    parent_workflow_name TEXT,
    subject_kind TEXT CHECK (
        subject_kind IS NULL OR subject_kind IN (
            'workflow', 'agent', 'workflow_node', 'model', 'tool',
            'background_task', 'api', 'persistence'
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

CREATE TABLE IF NOT EXISTS workflow_lifecycles (
    lifecycle_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    parent_run_id TEXT NOT NULL,
    workflow_id TEXT NOT NULL,
    workflow_name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    lifecycle_status TEXT NOT NULL CHECK (
        lifecycle_status IN ('active', 'deleting')
    ),
    parent_status TEXT NOT NULL CHECK (
        parent_status IN ('running', 'completed', 'failed', 'cancelled')
    ),
    parent_finished_at TEXT,
    deletion_started_at TEXT,
    messages_sha TEXT NOT NULL,
    message_count INTEGER NOT NULL CHECK (message_count >= 0)
);

CREATE INDEX IF NOT EXISTS idx_workflow_lifecycles_created
ON workflow_lifecycles(created_at DESC, lifecycle_id DESC);

CREATE INDEX IF NOT EXISTS idx_workflow_lifecycles_parent_status
ON workflow_lifecycles(parent_status);

CREATE TABLE IF NOT EXISTS workflow_run_records (
    run_id TEXT PRIMARY KEY,
    lifecycle_id TEXT NOT NULL,
    request_id TEXT NOT NULL,
    checkpoint_thread_id TEXT UNIQUE,
    run_kind TEXT NOT NULL CHECK (run_kind IN ('workflow', 'agent')),
    target_id TEXT NOT NULL,
    target_name TEXT NOT NULL,
    parent_run_id TEXT,
    launcher_id TEXT,
    background_task_id TEXT,
    run_depth INTEGER NOT NULL CHECK (run_depth >= 0),
    status TEXT NOT NULL CHECK (
        status IN (
            'pending', 'running', 'completed', 'failed',
            'cancelled', 'interrupted'
        )
    ),
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    finish_reason TEXT NOT NULL DEFAULT '',
    error_code TEXT NOT NULL DEFAULT '',
    input_tokens INTEGER NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
    output_tokens INTEGER NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
    total_tokens INTEGER NOT NULL DEFAULT 0 CHECK (total_tokens >= 0),
    observation_status TEXT NOT NULL CHECK (
        observation_status IN ('available', 'partial')
    ),
    FOREIGN KEY (lifecycle_id) REFERENCES workflow_lifecycles(lifecycle_id)
        ON DELETE CASCADE,
    FOREIGN KEY (parent_run_id) REFERENCES workflow_run_records(run_id)
        ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_workflow_run_records_lifecycle
ON workflow_run_records(lifecycle_id, created_at, run_id);

CREATE INDEX IF NOT EXISTS idx_workflow_run_records_parent
ON workflow_run_records(parent_run_id);

CREATE INDEX IF NOT EXISTS idx_workflow_run_records_status
ON workflow_run_records(status);

CREATE TABLE IF NOT EXISTS workflow_run_events (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    lifecycle_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    event_type TEXT NOT NULL,
    phase TEXT NOT NULL CHECK (
        phase IN ('created', 'started', 'completed', 'failed', 'cancelled')
    ),
    span_id TEXT,
    parent_span_id TEXT,
    subject_kind TEXT NOT NULL CHECK (
        subject_kind IN ('run', 'workflow_node', 'agent', 'model', 'tool')
    ),
    subject_id TEXT,
    subject_name TEXT,
    workflow_node_id TEXT,
    node_invocation_id TEXT,
    status TEXT NOT NULL DEFAULT '',
    error_code TEXT NOT NULL DEFAULT '',
    input_tokens INTEGER NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
    output_tokens INTEGER NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
    total_tokens INTEGER NOT NULL DEFAULT 0 CHECK (total_tokens >= 0),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (lifecycle_id) REFERENCES workflow_lifecycles(lifecycle_id)
        ON DELETE CASCADE,
    FOREIGN KEY (run_id) REFERENCES workflow_run_records(run_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_workflow_run_events_lifecycle
ON workflow_run_events(lifecycle_id, sequence);

CREATE INDEX IF NOT EXISTS idx_workflow_run_events_run
ON workflow_run_events(run_id, sequence);

CREATE INDEX IF NOT EXISTS idx_workflow_run_events_node
ON workflow_run_events(run_id, node_invocation_id, sequence);

CREATE TABLE IF NOT EXISTS workflow_model_requests (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    lifecycle_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    model_run_id TEXT NOT NULL UNIQUE,
    parent_span_id TEXT,
    agent_type TEXT NOT NULL CHECK (
        agent_type IN ('main_agent', 'subagent')
    ),
    agent_id TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    parent_agent_id TEXT,
    parent_agent_name TEXT,
    workflow_node_id TEXT,
    payload_json TEXT NOT NULL,
    FOREIGN KEY (lifecycle_id) REFERENCES workflow_lifecycles(lifecycle_id)
        ON DELETE CASCADE,
    FOREIGN KEY (run_id) REFERENCES workflow_run_records(run_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_workflow_model_requests_lifecycle
ON workflow_model_requests(lifecycle_id, sequence);

CREATE INDEX IF NOT EXISTS idx_workflow_model_requests_run
ON workflow_model_requests(run_id, sequence);

CREATE INDEX IF NOT EXISTS idx_workflow_model_requests_agent
ON workflow_model_requests(lifecycle_id, agent_type, agent_id, sequence);

CREATE TABLE IF NOT EXISTS media_output_assets (
    id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    block_index INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    media_type TEXT NOT NULL CHECK (media_type IN ('image', 'audio', 'video', 'file')),
    mime_type TEXT NOT NULL,
    relative_path TEXT NOT NULL UNIQUE,
    byte_size INTEGER NOT NULL CHECK (byte_size >= 0),
    original_filename TEXT NOT NULL,
    finalized INTEGER NOT NULL CHECK (finalized IN (0, 1))
);

CREATE INDEX IF NOT EXISTS idx_media_output_assets_request
ON media_output_assets(request_id);

"""

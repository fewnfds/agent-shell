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
DROP TABLE IF EXISTS media_output_assets;

-- Runtime diagnostics are operational failure records, not monitoring facts.
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

-- The development line has no runtime-history migration contract. Remove the
-- obsolete synthetic Journal schema, while keeping the current runtime_*
-- schema stable across every startup.
DROP TABLE IF EXISTS workflow_model_requests;
DROP TABLE IF EXISTS workflow_protocol_events;
DROP TABLE IF EXISTS workflow_run_events;
DROP TABLE IF EXISTS workflow_run_records;
DROP TABLE IF EXISTS workflow_lifecycles;

CREATE TABLE IF NOT EXISTS runtime_lifecycles (
    lifecycle_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    root_run_id TEXT NOT NULL UNIQUE,
    workflow_id TEXT NOT NULL,
    workflow_name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    lifecycle_status TEXT NOT NULL CHECK (
        lifecycle_status IN ('active', 'purge_pending', 'deleting')
    ),
    monitoring_capture_enabled INTEGER NOT NULL CHECK (
        monitoring_capture_enabled IN (0, 1)
    ),
    fully_terminal_at TEXT,
    deletion_started_at TEXT,
    messages_sha TEXT NOT NULL,
    message_count INTEGER NOT NULL CHECK (message_count >= 0)
);

CREATE INDEX IF NOT EXISTS idx_runtime_lifecycles_created
ON runtime_lifecycles(created_at DESC, lifecycle_id DESC);

CREATE INDEX IF NOT EXISTS idx_runtime_lifecycles_terminal
ON runtime_lifecycles(fully_terminal_at DESC, lifecycle_id DESC);

CREATE TABLE IF NOT EXISTS runtime_workflow_runs (
    run_id TEXT PRIMARY KEY,
    lifecycle_id TEXT NOT NULL,
    request_id TEXT NOT NULL,
    checkpoint_thread_id TEXT UNIQUE,
    workflow_id TEXT NOT NULL,
    workflow_name TEXT NOT NULL,
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
    FOREIGN KEY (lifecycle_id) REFERENCES runtime_lifecycles(lifecycle_id)
        ON DELETE CASCADE,
    FOREIGN KEY (parent_run_id) REFERENCES runtime_workflow_runs(run_id)
        ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_runtime_workflow_runs_lifecycle
ON runtime_workflow_runs(lifecycle_id, created_at, run_id);

CREATE INDEX IF NOT EXISTS idx_runtime_workflow_runs_parent
ON runtime_workflow_runs(parent_run_id);

CREATE INDEX IF NOT EXISTS idx_runtime_workflow_runs_status
ON runtime_workflow_runs(status);

CREATE TABLE IF NOT EXISTS runtime_run_transitions (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    lifecycle_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    phase TEXT NOT NULL CHECK (
        phase IN ('created', 'started', 'completed', 'failed', 'cancelled', 'interrupted')
    ),
    status TEXT NOT NULL,
    error_code TEXT NOT NULL DEFAULT '',
    finish_reason TEXT NOT NULL DEFAULT '',
    usage_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (lifecycle_id) REFERENCES runtime_lifecycles(lifecycle_id)
        ON DELETE CASCADE,
    FOREIGN KEY (run_id) REFERENCES runtime_workflow_runs(run_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_runtime_run_transitions_lifecycle
ON runtime_run_transitions(lifecycle_id, sequence);

CREATE INDEX IF NOT EXISTS idx_runtime_run_transitions_run
ON runtime_run_transitions(run_id, sequence);

CREATE TABLE IF NOT EXISTS runtime_run_monitoring (
    run_id TEXT PRIMARY KEY,
    lifecycle_id TEXT NOT NULL,
    graph_status TEXT NOT NULL CHECK (
        graph_status IN ('capturing', 'available', 'partial', 'not_applicable')
    ),
    protocol_status TEXT NOT NULL CHECK (
        protocol_status IN ('capturing', 'available', 'partial', 'not_applicable')
    ),
    model_status TEXT NOT NULL CHECK (
        model_status IN ('capturing', 'available', 'partial', 'not_applicable')
    ),
    command_status TEXT NOT NULL CHECK (
        command_status IN ('capturing', 'available', 'partial', 'not_applicable')
    ),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (lifecycle_id) REFERENCES runtime_lifecycles(lifecycle_id)
        ON DELETE CASCADE,
    FOREIGN KEY (run_id) REFERENCES runtime_workflow_runs(run_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_runtime_run_monitoring_lifecycle
ON runtime_run_monitoring(lifecycle_id, run_id);

CREATE TABLE IF NOT EXISTS runtime_run_graphs (
    run_id TEXT PRIMARY KEY,
    lifecycle_id TEXT NOT NULL,
    workflow_id TEXT NOT NULL,
    workflow_name TEXT NOT NULL,
    document_sha TEXT NOT NULL,
    document_json TEXT NOT NULL,
    node_sources_json TEXT NOT NULL,
    edge_classes_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (lifecycle_id) REFERENCES runtime_lifecycles(lifecycle_id)
        ON DELETE CASCADE,
    FOREIGN KEY (run_id) REFERENCES runtime_workflow_runs(run_id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS runtime_protocol_events (
    lifecycle_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    event_sequence INTEGER NOT NULL CHECK (event_sequence > 0),
    method TEXT NOT NULL CHECK (length(method) > 0),
    captured_at TEXT NOT NULL,
    envelope_json TEXT NOT NULL,
    origin_json TEXT NOT NULL,
    PRIMARY KEY (run_id, event_sequence),
    FOREIGN KEY (lifecycle_id) REFERENCES runtime_lifecycles(lifecycle_id)
        ON DELETE CASCADE,
    FOREIGN KEY (run_id) REFERENCES runtime_workflow_runs(run_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_runtime_protocol_events_lifecycle
ON runtime_protocol_events(lifecycle_id, run_id, event_sequence);

CREATE TABLE IF NOT EXISTS runtime_model_requests (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    lifecycle_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    model_run_id TEXT NOT NULL UNIQUE,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed')),
    error_code TEXT NOT NULL DEFAULT '',
    agent_type TEXT NOT NULL CHECK (
        agent_type IN ('main_agent', 'subagent')
    ),
    agent_id TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    parent_agent_id TEXT NOT NULL DEFAULT '',
    parent_agent_name TEXT NOT NULL DEFAULT '',
    workflow_node_id TEXT NOT NULL DEFAULT '',
    request_json TEXT NOT NULL,
    usage_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (lifecycle_id) REFERENCES runtime_lifecycles(lifecycle_id)
        ON DELETE CASCADE,
    FOREIGN KEY (run_id) REFERENCES runtime_workflow_runs(run_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_runtime_model_requests_lifecycle
ON runtime_model_requests(lifecycle_id, sequence);

CREATE INDEX IF NOT EXISTS idx_runtime_model_requests_run
ON runtime_model_requests(run_id, sequence);

CREATE TABLE IF NOT EXISTS runtime_command_observations (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    lifecycle_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    invocation_id TEXT NOT NULL,
    workflow_node_id TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    phase TEXT NOT NULL CHECK (phase IN ('started', 'completed', 'failed')),
    error_code TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE (run_id, invocation_id, phase),
    FOREIGN KEY (lifecycle_id) REFERENCES runtime_lifecycles(lifecycle_id)
        ON DELETE CASCADE,
    FOREIGN KEY (run_id) REFERENCES runtime_workflow_runs(run_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_runtime_command_observations_lifecycle
ON runtime_command_observations(lifecycle_id, run_id, sequence);

-- This narrow owner intentionally has no Lifecycle foreign key. Automatic
-- retention may release the runtime route while preserving the only verified
-- reference to a Shell-created directory for a later explicit user action.
CREATE TABLE IF NOT EXISTS runtime_managed_directories (
    lifecycle_id TEXT NOT NULL,
    filesystem_id TEXT NOT NULL,
    virtual_path TEXT NOT NULL,
    configured_root TEXT NOT NULL,
    resolved_target TEXT NOT NULL,
    created_at TEXT NOT NULL,
    released_at TEXT,
    PRIMARY KEY (lifecycle_id, filesystem_id, virtual_path)
);

"""

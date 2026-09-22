CREATE TABLE scenarios (
    id UUID PRIMARY KEY,
    body JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE training_sessions (
    id UUID PRIMARY KEY,
    scenario_id UUID NOT NULL REFERENCES scenarios(id),
    scenario_body JSONB NOT NULL,
    mode VARCHAR(16) NOT NULL,
    state VARCHAR(16) NOT NULL,
    card_body JSONB NOT NULL,
    card_revision INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    started_at TIMESTAMPTZ,
    ended_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL,
    failure_reason TEXT,
    time_limit_event_emitted BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX training_sessions_created_at_idx ON training_sessions(created_at);

CREATE TABLE session_events (
    event_id UUID PRIMARY KEY,
    session_id UUID NOT NULL REFERENCES training_sessions(id) ON DELETE CASCADE,
    type VARCHAR(64) NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    source VARCHAR(16) NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX session_events_session_idx ON session_events(session_id, occurred_at, event_id);

CREATE TABLE session_reports (
    session_id UUID PRIMARY KEY REFERENCES training_sessions(id) ON DELETE CASCADE,
    body JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE service_assignments (
    id UUID PRIMARY KEY,
    session_id UUID NOT NULL REFERENCES training_sessions(id) ON DELETE CASCADE,
    body JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX service_assignments_session_idx ON service_assignments(session_id);

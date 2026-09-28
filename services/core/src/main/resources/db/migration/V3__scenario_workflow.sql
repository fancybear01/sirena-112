CREATE TABLE scenario_workflow (
    id UUID PRIMARY KEY,
    family_id UUID NOT NULL,
    version INTEGER NOT NULL CHECK (version > 0),
    revision INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(16) NOT NULL CHECK (status IN ('DRAFT', 'APPROVED')),
    body JSONB NOT NULL,
    comment TEXT NOT NULL DEFAULT '',
    owner_id UUID,
    group_id UUID,
    source VARCHAR(16) NOT NULL,
    source_session_id UUID UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (family_id, version)
);
CREATE INDEX scenario_workflow_group_idx ON scenario_workflow(group_id, status);

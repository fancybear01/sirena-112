CREATE TABLE training_groups (
    id UUID PRIMARY KEY,
    name VARCHAR(120) NOT NULL UNIQUE
);

CREATE TABLE auth_accounts (
    id UUID PRIMARY KEY,
    username VARCHAR(80) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(16) NOT NULL,
    display_name VARCHAR(160) NOT NULL,
    group_id UUID REFERENCES training_groups(id),
    locked BOOLEAN NOT NULL DEFAULT FALSE,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX auth_accounts_group_idx ON auth_accounts(group_id);

ALTER TABLE training_sessions ADD COLUMN student_id UUID;
ALTER TABLE training_sessions ADD COLUMN teacher_id UUID;
ALTER TABLE training_sessions ADD COLUMN group_id UUID;
CREATE INDEX training_sessions_student_idx ON training_sessions(student_id);
CREATE INDEX training_sessions_teacher_idx ON training_sessions(teacher_id);

CREATE TABLE auth_audit (
    id UUID PRIMARY KEY,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor_id UUID,
    action VARCHAR(48) NOT NULL,
    subject_id UUID,
    outcome VARCHAR(16) NOT NULL,
    request_id VARCHAR(128)
);
CREATE INDEX auth_audit_occurred_idx ON auth_audit(occurred_at);

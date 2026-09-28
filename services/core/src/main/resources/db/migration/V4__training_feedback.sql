CREATE TABLE training_feedback (
    id UUID PRIMARY KEY,
    session_id UUID NOT NULL REFERENCES training_sessions(id) ON DELETE CASCADE,
    author_id UUID NOT NULL REFERENCES auth_accounts(id),
    kind VARCHAR(16) NOT NULL CHECK (kind IN ('COMMENT', 'CORRECTION')),
    text TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    old_score DOUBLE PRECISION,
    new_score DOUBLE PRECISION,
    CHECK ((kind = 'COMMENT' AND old_score IS NULL AND new_score IS NULL)
        OR (kind = 'CORRECTION' AND old_score IS NOT NULL AND new_score IS NOT NULL))
);
CREATE INDEX training_feedback_session_idx ON training_feedback(session_id, created_at, id);

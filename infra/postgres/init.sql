-- Postgres schema for the chatbot + inference logging system.
-- Loaded automatically by the postgres image on first start.

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ---------------------------------------------------------------------------
-- conversations: container for a multi-turn session.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS conversations (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title       TEXT,
    status      TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'cancelled', 'completed')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_conversations_updated
    ON conversations (updated_at DESC);

-- ---------------------------------------------------------------------------
-- messages: chat history. Drives both UI replay and the LLM context window.
-- Content is stored post-PII-redaction.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS messages (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL
                    CHECK (role IN ('user', 'assistant', 'system')),
    content         TEXT NOT NULL,
    sequence        INT  NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (conversation_id, sequence)
);

CREATE INDEX IF NOT EXISTS idx_messages_conv_seq
    ON messages (conversation_id, sequence);

-- ---------------------------------------------------------------------------
-- inference_logs: one row per LLM call. Parallel to messages but with its own
-- lifecycle (observability concern, not chat-replay concern).
-- request_id is the SDK-generated idempotency key.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS inference_logs (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id         UUID UNIQUE NOT NULL,
    conversation_id    UUID REFERENCES conversations(id) ON DELETE SET NULL,
    message_id         UUID REFERENCES messages(id)     ON DELETE SET NULL,
    provider           TEXT NOT NULL,
    model              TEXT NOT NULL,
    status             TEXT NOT NULL
                       CHECK (status IN ('success', 'error', 'cancelled')),
    error_code         TEXT,
    error_message      TEXT,
    started_at         TIMESTAMPTZ NOT NULL,
    ended_at           TIMESTAMPTZ NOT NULL,
    latency_ms         INT GENERATED ALWAYS AS
                         ((EXTRACT(EPOCH FROM (ended_at - started_at)) * 1000)::INT)
                         STORED,
    ttfb_ms            INT,
    prompt_tokens      INT,
    completion_tokens  INT,
    total_tokens       INT,
    input_preview      TEXT,
    output_preview     TEXT,
    metadata           JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_logs_created
    ON inference_logs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_logs_provider_model
    ON inference_logs (provider, model);
CREATE INDEX IF NOT EXISTS idx_logs_status
    ON inference_logs (status);
CREATE INDEX IF NOT EXISTS idx_logs_conv
    ON inference_logs (conversation_id);

-- ---------------------------------------------------------------------------
-- Trigger: bump conversations.updated_at whenever a message is added.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION touch_conversation()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE conversations
       SET updated_at = NOW()
     WHERE id = NEW.conversation_id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_touch_conversation ON messages;
CREATE TRIGGER trg_touch_conversation
    AFTER INSERT ON messages
    FOR EACH ROW
    EXECUTE FUNCTION touch_conversation();

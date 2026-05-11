-- =============================================================================
-- NISTULA UNIFIED MESSAGING PLATFORM - DATABASE SCHEMA
-- Author: Ravikumar
-- Database: PostgreSQL 15+
-- Description: Complete schema for guest messaging, conversations, AI processing,
--              and reservation tracking across all channels.
-- =============================================================================

-- =============================================================================
-- DESIGN DECISIONS (by Ravikumar)
-- =============================================================================
--
-- 1. GUEST PROFILES:
--    - Single table for guests across ALL channels (unified identity)
--    - phone/email are unique to prevent duplicate profiles
--    - created_at/updated_at for audit trail
--
-- 2. MESSAGES:
--    - All messages in ONE table (unified, regardless of channel)
--    - message_type: 'inbound' (from guest) or 'outbound' (to guest)
--    - ai_confidence_score and query_type stored per inbound message
--    - source_channel tracks where the message originated
--
-- 3. CONVERSATIONS:
--    - Groups related messages into threads
--    - Linked to guests and optionally to reservations
--    - status: 'active', 'resolved', 'escalated', 'archived'
--
-- 4. RESERVATIONS:
--    - Separate table for booking details
--    - Linked to guests (one guest can have multiple reservations)
--    - conversation links back to reservation for context
--
-- 5. AI PROCESSING TRACKING:
--    - ai_message_metadata: tracks how each AI response was handled
--    - ai_draft_status: 'drafted', 'edited', 'auto_sent', 'rejected'
--    - Full audit trail of human-AI collaboration
--
-- 6. PROPERTIES:
--    - Centralized property information
--    - Allows multi-property support in future
--
-- HARDEST DESIGN DECISION (by Ravikumar):
-- "Deciding how to handle the conversation-threading logic was the hardest choice.
-- I debated between: (a) auto-creating conversations based on time gaps
-- (24h silence = new conversation), (b) explicit conversation IDs from
-- external systems, or (c) a hybrid approach. I chose the hybrid:
-- conversations are explicitly created but linked to reservations for
-- natural grouping. This gives us clean thread boundaries while maintaining
-- flexibility for walk-in queries without reservations. The time-based
-- auto-splitting is handled at the application layer, not the database,
-- to keep the schema simpler and avoid complex triggers."
-- =============================================================================

-- Enable UUID extension for automatic UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Enable updated_at trigger function
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- =============================================================================
-- 1. PROPERTIES TABLE
-- =============================================================================
-- Stores property/villa information. Central reference for all messages.

CREATE TABLE properties (
    property_id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    property_code       VARCHAR(50) NOT NULL UNIQUE,     -- e.g., 'villa-b1'
    name                VARCHAR(200) NOT NULL,
    location            VARCHAR(300) NOT NULL,
    bedrooms            INTEGER NOT NULL DEFAULT 0,
    max_guests          INTEGER NOT NULL DEFAULT 0,
    has_private_pool    BOOLEAN NOT NULL DEFAULT FALSE,
    check_in_time       TIME NOT NULL DEFAULT '14:00:00',
    check_out_time      TIME NOT NULL DEFAULT '11:00:00',
    base_rate_per_night DECIMAL(12, 2) NOT NULL DEFAULT 0,
    extra_guest_rate    DECIMAL(12, 2) NOT NULL DEFAULT 0,
    wifi_password       VARCHAR(100),
    caretaker_hours     VARCHAR(100),
    chef_available      BOOLEAN NOT NULL DEFAULT FALSE,
    cancellation_policy TEXT,
    amenities           JSONB DEFAULT '{}',              -- Flexible amenities storage
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE properties IS 'Property/villa details - central reference table';
COMMENT ON COLUMN properties.property_code IS 'Human-readable property identifier (e.g., villa-b1)';

CREATE TRIGGER update_properties_updated_at
    BEFORE UPDATE ON properties
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Seed data for Villa B1
INSERT INTO properties (
    property_code, name, location, bedrooms, max_guests,
    has_private_pool, check_in_time, check_out_time,
    base_rate_per_night, extra_guest_rate, wifi_password,
    caretaker_hours, chef_available, cancellation_policy
) VALUES (
    'villa-b1',
    'Villa B1, Assagao, North Goa',
    'Assagao, North Goa, India',
    3,
    6,
    TRUE,
    '14:00:00',
    '11:00:00',
    18000.00,
    2000.00,
    'Nistula@2024',
    '8:00 AM - 10:00 PM',
    TRUE,
    'Free cancellation up to 7 days before check-in'
);

-- =============================================================================
-- 2. GUESTS TABLE (Unified Profile)
-- =============================================================================
-- One record per guest across ALL channels. Phone/email are unique to prevent
-- duplicate profiles when the same guest messages from different channels.

CREATE TABLE guests (
    guest_id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    full_name           VARCHAR(200) NOT NULL,
    phone               VARCHAR(20) UNIQUE,              -- WhatsApp number, primary identifier
    email               VARCHAR(200) UNIQUE,
    preferred_channel   VARCHAR(50) DEFAULT 'whatsapp',   -- whatsapp, booking_com, airbnb, instagram, direct
    notes               TEXT,                             -- Internal notes about guest
    tags                JSONB DEFAULT '[]',               -- e.g., ["vip", "repeat_guest", "allergic_to_nuts"]
    total_bookings      INTEGER NOT NULL DEFAULT 0,
    lifetime_value      DECIMAL(12, 2) NOT NULL DEFAULT 0,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE guests IS 'Unified guest profiles - one record per person across all channels';
COMMENT ON COLUMN guests.phone IS 'Primary identifier for deduplication (WhatsApp number)';
COMMENT ON COLUMN guests.tags IS 'JSON array of tags for guest segmentation';

CREATE TRIGGER update_guests_updated_at
    BEFORE UPDATE ON guests
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Index for fast guest lookup by phone/email
CREATE INDEX idx_guests_phone ON guests(phone) WHERE phone IS NOT NULL;
CREATE INDEX idx_guests_email ON guests(email) WHERE email IS NOT NULL;

-- =============================================================================
-- 3. GUEST_CHANNEL_IDENTITIES TABLE
-- =============================================================================
-- Maps external channel IDs to unified guest profiles.
-- e.g., WhatsApp number +91234567890 -> guest_id abc-123
--       Booking.com guest ID 9876543 -> guest_id abc-123 (same person)

CREATE TABLE guest_channel_identities (
    identity_id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    guest_id            UUID NOT NULL REFERENCES guests(guest_id) ON DELETE CASCADE,
    channel             VARCHAR(50) NOT NULL,             -- whatsapp, booking_com, airbnb, instagram, direct
    channel_guest_id    VARCHAR(200) NOT NULL,            -- ID from the external channel
    channel_guest_name  VARCHAR(200),                     -- Name as shown on that channel
    is_primary          BOOLEAN NOT NULL DEFAULT FALSE,    -- Primary channel for this guest
    created_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    
    -- One identity per channel per guest (prevents duplicates)
    UNIQUE(guest_id, channel),
    -- One channel_guest_id per channel (prevents mapping conflicts)
    UNIQUE(channel, channel_guest_id)
);

COMMENT ON TABLE guest_channel_identities IS 'Maps external channel IDs to unified guest profiles for cross-channel identity resolution';

CREATE INDEX idx_guest_channel_identities_guest ON guest_channel_identities(guest_id);
CREATE INDEX idx_guest_channel_identities_lookup ON guest_channel_identities(channel, channel_guest_id);

-- =============================================================================
-- 4. RESERVATIONS TABLE
-- =============================================================================
-- Booking records linked to guests. A guest can have multiple reservations.

CREATE TABLE reservations (
    reservation_id      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    booking_ref         VARCHAR(50) NOT NULL UNIQUE,      -- e.g., 'NIS-2024-0891'
    guest_id            UUID NOT NULL REFERENCES guests(guest_id),
    property_id         UUID NOT NULL REFERENCES properties(property_id),
    channel             VARCHAR(50) NOT NULL,             -- Where the booking came from
    check_in_date       DATE NOT NULL,
    check_out_date      DATE NOT NULL,
    num_guests          INTEGER NOT NULL DEFAULT 1,
    total_amount        DECIMAL(12, 2),
    status              VARCHAR(50) NOT NULL DEFAULT 'confirmed',  -- confirmed, checked_in, checked_out, cancelled, no_show
    special_requests    TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE reservations IS 'Booking records linked to guests and properties';
COMMENT ON COLUMN reservations.booking_ref IS 'Human-readable booking reference displayed to guests';

CREATE TRIGGER update_reservations_updated_at
    BEFORE UPDATE ON reservations
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE INDEX idx_reservations_guest ON reservations(guest_id);
CREATE INDEX idx_reservations_booking_ref ON reservations(booking_ref);
CREATE INDEX idx_reservations_dates ON reservations(check_in_date, check_out_date);
CREATE INDEX idx_reservations_property ON reservations(property_id);

-- =============================================================================
-- 5. CONVERSATIONS TABLE
-- =============================================================================
-- Groups related messages into conversation threads.
-- Linked to guests and optionally to reservations.

CREATE TABLE conversations (
    conversation_id     UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    guest_id            UUID NOT NULL REFERENCES guests(guest_id),
    reservation_id      UUID REFERENCES reservations(reservation_id),  -- NULL for pre-sales enquiries
    property_id         UUID NOT NULL REFERENCES properties(property_id),
    status              VARCHAR(50) NOT NULL DEFAULT 'active',  -- active, resolved, escalated, archived
    subject             VARCHAR(300),                         -- Optional subject/topic
    last_message_at     TIMESTAMPTZ,                          -- Timestamp of most recent message
    resolution_notes    TEXT,
    resolved_by         UUID,                                 -- Reference to agent who resolved (if applicable)
    created_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE conversations IS 'Conversation threads grouping related messages';
COMMENT ON COLUMN conversations.reservation_id IS 'NULL for pre-sales enquiries without a booking';
COMMENT ON COLUMN conversations.status IS 'active: ongoing, resolved: completed, escalated: needs human, archived: inactive';

CREATE TRIGGER update_conversations_updated_at
    BEFORE UPDATE ON conversations
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE INDEX idx_conversations_guest ON conversations(guest_id);
CREATE INDEX idx_conversations_reservation ON conversations(reservation_id) WHERE reservation_id IS NOT NULL;
CREATE INDEX idx_conversations_status ON conversations(status);
CREATE INDEX idx_conversations_last_message ON conversations(last_message_at);

-- =============================================================================
-- 6. MESSAGES TABLE (Unified - All Channels)
-- =============================================================================
-- ALL messages across ALL channels in ONE table. This is the core table.
-- Stores both inbound (from guest) and outbound (to guest) messages.
-- For inbound messages: stores AI confidence score and query type.

CREATE TABLE messages (
    message_id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    conversation_id     UUID NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    
    -- Message direction and source
    message_type        VARCHAR(20) NOT NULL,             -- 'inbound' (guest -> us) or 'outbound' (us -> guest)
    source_channel      VARCHAR(50) NOT NULL,             -- whatsapp, booking_com, airbnb, instagram, direct
    
    -- Content
    message_text        TEXT NOT NULL,
    
    -- For inbound messages: AI classification and processing
    query_type          VARCHAR(50),                      -- pre_sales_availability, pre_sales_pricing, etc.
    ai_confidence_score DECIMAL(5, 4),                    -- 0.0000 to 1.0000
    
    -- For outbound messages: how the message was created
    -- NOTE: This is PER MESSAGE - tracks how THIS specific outbound was created
    -- The detailed AI metadata is in ai_message_metadata table
    
    -- Metadata
    sent_at             TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    external_message_id VARCHAR(200),                     -- ID from external channel (if available)
    
    -- Raw payload storage for debugging/audit
    raw_payload         JSONB,                            -- Original webhook payload
    
    created_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE messages IS 'All messages across all channels - unified storage';
COMMENT ON COLUMN messages.message_type IS 'inbound: from guest, outbound: to guest';
COMMENT ON COLUMN messages.query_type IS 'AI-classified query category (only for inbound)';
COMMENT ON COLUMN messages.ai_confidence_score IS 'AI confidence score 0.0-1.0 (only for inbound)';
COMMENT ON COLUMN messages.raw_payload IS 'Original webhook payload for audit trail';

CREATE INDEX idx_messages_conversation ON messages(conversation_id);
CREATE INDEX idx_messages_type ON messages(message_type);
CREATE INDEX idx_messages_channel ON messages(source_channel);
CREATE INDEX idx_messages_query_type ON messages(query_type) WHERE query_type IS NOT NULL;
CREATE INDEX idx_messages_sent_at ON messages(sent_at);

-- =============================================================================
-- 7. AI MESSAGE METADATA TABLE
-- =============================================================================
-- Tracks AI-generated responses: how they were created, edited, and sent.
-- Links to outbound messages for full audit trail.

CREATE TABLE ai_message_metadata (
    metadata_id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    
    -- Link to the message tables
    -- The inbound message that triggered the AI response
    inbound_message_id  UUID NOT NULL REFERENCES messages(message_id),
    -- The outbound message that was created (may be NULL if not yet sent)
    outbound_message_id UUID REFERENCES messages(message_id),
    
    -- AI generation details
    ai_draft_status     VARCHAR(50) NOT NULL DEFAULT 'drafted',  -- drafted, edited, auto_sent, rejected, pending_review
    ai_model            VARCHAR(100) NOT NULL,                  -- claude-sonnet-4-20250514, etc.
    
    -- The actual AI-generated content
    ai_drafted_reply    TEXT NOT NULL,                          -- Raw AI output
    confidence_score    DECIMAL(5, 4) NOT NULL,                 -- Final composite score 0.0000-1.0000
    suggested_action    VARCHAR(50) NOT NULL,                   -- auto_send, agent_review, escalate
    actual_action       VARCHAR(50),                            -- What actually happened
    
    -- Human agent interaction (if applicable)
    agent_id            UUID,                                   -- Agent who reviewed/edited
    agent_edited_reply  TEXT,                                   -- Agent-modified version (if edited)
    review_started_at   TIMESTAMPTZ,                            -- When agent started review
    review_completed_at TIMESTAMPTZ,                            -- When agent finished
    
    -- Confidence factor breakdown (for analytics)
    confidence_factors  JSONB,                                  -- {ai_self: 0.9, context: 0.8, ...}
    
    -- Timestamps
    created_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE ai_message_metadata IS 'Tracks AI-generated responses: drafting, editing, and sending workflow';
COMMENT ON COLUMN ai_message_metadata.ai_draft_status IS 'drafted: AI generated, edited: agent modified, auto_sent: sent without review, rejected: discarded, pending_review: waiting for agent';
COMMENT ON COLUMN ai_message_metadata.confidence_factors IS 'JSON breakdown of individual confidence factors for analytics and debugging';

CREATE TRIGGER update_ai_metadata_updated_at
    BEFORE UPDATE ON ai_message_metadata
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE INDEX idx_ai_metadata_inbound ON ai_message_metadata(inbound_message_id);
CREATE INDEX idx_ai_metadata_outbound ON ai_message_metadata(outbound_message_id) WHERE outbound_message_id IS NOT NULL;
CREATE INDEX idx_ai_metadata_status ON ai_message_metadata(ai_draft_status);
CREATE INDEX idx_ai_metadata_action ON ai_message_metadata(suggested_action);

-- =============================================================================
-- 8. MESSAGE_ACTION_LOG TABLE
-- =============================================================================
-- Comprehensive audit trail of all actions taken on messages.
-- Who did what, when, and why.

CREATE TABLE message_action_log (
    log_id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    message_id          UUID NOT NULL REFERENCES messages(message_id),
    action_type         VARCHAR(50) NOT NULL,             -- ai_drafted, agent_edited, auto_sent, manually_sent, escalated, rejected, resolved
    performed_by        VARCHAR(100) NOT NULL,             -- 'system', 'agent_name', 'ai_model_name'
    details             JSONB DEFAULT '{}',               -- Additional context
    created_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE message_action_log IS 'Audit trail of all actions taken on messages';

CREATE INDEX idx_action_log_message ON message_action_log(message_id);
CREATE INDEX idx_action_log_created ON message_action_log(created_at);

-- =============================================================================
-- 9. ESCALATIONS TABLE
-- =============================================================================
-- Tracks escalated conversations and their resolution.

CREATE TABLE escalations (
    escalation_id       UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    conversation_id     UUID NOT NULL REFERENCES conversations(conversation_id),
    message_id          UUID NOT NULL REFERENCES messages(message_id),  -- The message that triggered escalation
    
    -- Escalation details
    reason              VARCHAR(200) NOT NULL,            -- Why it was escalated
    escalation_type     VARCHAR(50) NOT NULL DEFAULT 'ai_low_confidence',  -- complaint, low_confidence, complex_request, guest_request
    
    -- Assignment and resolution
    assigned_to         UUID,                                 -- Agent assigned
    assigned_at         TIMESTAMPTZ,
    resolved_at         TIMESTAMPTZ,
    resolution          TEXT,                                 -- How it was resolved
    
    -- SLA tracking
    sla_deadline        TIMESTAMPTZ,                          -- When response is due
    sla_met             BOOLEAN,                              -- Was SLA met?
    
    status              VARCHAR(50) NOT NULL DEFAULT 'open',  -- open, assigned, in_progress, resolved, closed
    
    created_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE escalations IS 'Tracks escalated conversations and their resolution with SLA monitoring';

CREATE TRIGGER update_escalations_updated_at
    BEFORE UPDATE ON escalations
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE INDEX idx_escalations_conversation ON escalations(conversation_id);
CREATE INDEX idx_escalations_status ON escalations(status);
CREATE INDEX idx_escalations_assigned ON escalations(assigned_to) WHERE assigned_to IS NOT NULL;
CREATE INDEX idx_escalations_sla ON escalations(sla_deadline) WHERE status NOT IN ('resolved', 'closed');

-- =============================================================================
-- 10. AGENTS TABLE (Staff/Operators)
-- =============================================================================
-- Internal staff who handle escalated conversations.

CREATE TABLE agents (
    agent_id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    full_name           VARCHAR(200) NOT NULL,
    email               VARCHAR(200) NOT NULL UNIQUE,
    role                VARCHAR(50) NOT NULL DEFAULT 'agent',  -- agent, supervisor, admin
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE agents IS 'Internal staff who review and handle escalated conversations';

CREATE TRIGGER update_agents_updated_at
    BEFORE UPDATE ON agents
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- =============================================================================
-- VIEWS FOR COMMON QUERIES
-- =============================================================================

-- View: Active conversations with latest message preview
CREATE VIEW active_conversations_preview AS
SELECT 
    c.conversation_id,
    c.guest_id,
    g.full_name AS guest_name,
    c.reservation_id,
    r.booking_ref,
    c.property_id,
    p.name AS property_name,
    c.status,
    c.last_message_at,
    c.created_at,
    (SELECT message_text FROM messages 
     WHERE conversation_id = c.conversation_id 
     ORDER BY sent_at DESC LIMIT 1) AS latest_message_preview
FROM conversations c
JOIN guests g ON c.guest_id = g.guest_id
LEFT JOIN reservations r ON c.reservation_id = r.reservation_id
JOIN properties p ON c.property_id = p.property_id
WHERE c.status IN ('active', 'escalated');

COMMENT ON VIEW active_conversations_preview IS 'Quick overview of all active conversations with latest message';

-- View: AI Performance Metrics
CREATE VIEW ai_performance_metrics AS
SELECT 
    ai.suggested_action,
    ai.ai_draft_status,
    m.query_type,
    COUNT(*) AS message_count,
    AVG(ai.confidence_score) AS avg_confidence,
    MIN(ai.confidence_score) AS min_confidence,
    MAX(ai.confidence_score) AS max_confidence
FROM ai_message_metadata ai
JOIN messages m ON ai.inbound_message_id = m.message_id
GROUP BY ai.suggested_action, ai.ai_draft_status, m.query_type;

COMMENT ON VIEW ai_performance_metrics IS 'AI performance analytics by action type and query category';

-- View: Escalation SLA Dashboard
CREATE VIEW escalation_sla_dashboard AS
SELECT 
    e.escalation_id,
    e.conversation_id,
    e.reason,
    e.escalation_type,
    e.status,
    e.sla_deadline,
    e.sla_met,
    CASE 
        WHEN e.sla_deadline < CURRENT_TIMESTAMP AND e.status NOT IN ('resolved', 'closed') 
        THEN TRUE 
        ELSE FALSE 
    END AS sla_breached,
    e.created_at,
    e.resolved_at
FROM escalations e;

COMMENT ON VIEW escalation_sla_dashboard IS 'SLA monitoring dashboard for escalations';

-- =============================================================================
-- STORED PROCEDURES / FUNCTIONS
-- =============================================================================

-- Function: Create a new conversation and return its ID
-- Usage: SELECT create_conversation('guest-uuid', 'reservation-uuid', 'property-uuid', 'subject');
CREATE OR REPLACE FUNCTION create_conversation(
    p_guest_id UUID,
    p_reservation_id UUID,
    p_property_id UUID,
    p_subject TEXT DEFAULT NULL
) RETURNS UUID AS $$
DECLARE
    v_conversation_id UUID;
BEGIN
    INSERT INTO conversations (guest_id, reservation_id, property_id, subject)
    VALUES (p_guest_id, p_reservation_id, p_property_id, p_subject)
    RETURNING conversation_id INTO v_conversation_id;
    
    RETURN v_conversation_id;
END;
$$ LANGUAGE plpgsql;

-- Function: Log a message action
-- Usage: SELECT log_message_action('message-uuid', 'auto_sent', 'system', '{"confidence": 0.92}'::jsonb);
CREATE OR REPLACE FUNCTION log_message_action(
    p_message_id UUID,
    p_action_type VARCHAR(50),
    p_performed_by VARCHAR(100),
    p_details JSONB DEFAULT '{}'
) RETURNS UUID AS $$
DECLARE
    v_log_id UUID;
BEGIN
    INSERT INTO message_action_log (message_id, action_type, performed_by, details)
    VALUES (p_message_id, p_action_type, p_performed_by, p_details)
    RETURNING log_id INTO v_log_id;
    
    RETURN v_log_id;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- END OF SCHEMA
-- =============================================================================
-- Total Tables: 10 (properties, guests, guest_channel_identities, reservations,
--                    conversations, messages, ai_message_metadata,
--                    message_action_log, escalations, agents)
-- Views: 3 (active_conversations_preview, ai_performance_metrics, escalation_sla_dashboard)
-- Functions: 3 (update_updated_at_column, create_conversation, log_message_action)
-- Author: Ravikumar
-- =============================================================================

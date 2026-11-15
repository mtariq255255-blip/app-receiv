
-- ============================================================
-- ReceivAI UAE — Audit Logs Database Migration
-- File: backend/migrations/20261115_audit_log_indexes.sql
--
-- Run once against the existing PostgreSQL database.
--
-- The AuditLog ORM model already exists in the backend.
-- This script creates the table only when missing,
-- and adds indexes for the audit dashboard.
--
-- Back up the database before executing.
-- ============================================================

BEGIN;

-- ============================================================
-- 1. CREATE AUDIT LOGS TABLE IF MISSING
-- ============================================================

CREATE TABLE IF NOT EXISTS audit_logs (
    id BIGSERIAL PRIMARY KEY,

    admin_id BIGINT NULL
        REFERENCES admin_users(id),

    action VARCHAR(150) NOT NULL,

    entity_type VARCHAR(100),

    entity_id BIGINT,

    details JSONB,

    created_at TIMESTAMPTZ NOT NULL
        DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- 2. INDEX: RECENT AUDIT EVENTS
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at_id
    ON audit_logs (
        created_at DESC,
        id DESC
    );

-- ============================================================
-- 3. INDEX: ACTION FILTERING
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_audit_logs_action_created_at
    ON audit_logs (
        action,
        created_at DESC
    );

-- ============================================================
-- 4. INDEX: ENTITY LOOKUPS
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_audit_logs_entity
    ON audit_logs (
        entity_type,
        entity_id
    );

-- ============================================================
-- 5. INDEX: ADMINISTRATOR ACTIVITY
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_audit_logs_admin_created
    ON audit_logs (
        admin_id,
        created_at DESC
    );

-- ============================================================
-- 6. COMMIT MIGRATION
-- ============================================================

COMMIT;

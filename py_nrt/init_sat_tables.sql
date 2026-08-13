-- ============================================
-- OTNSAT Database Schema Initialization
-- ============================================
-- This script creates all necessary tables for the SatQcResultsLoader
-- Run this once at the beginning to set up the database schema.
-- Replace {{sat_schema}} with your desired schema name if different.
-- ============================================

CREATE SCHEMA {{sat_schema}};

-- ============================================
-- Grant permissions on schema
-- ============================================
GRANT USAGE ON SCHEMA {{sat_schema}} TO {{user_name}};
GRANT CREATE ON SCHEMA {{sat_schema}} TO {{user_name}};
GRANT ALL PRIVILEGES ON SCHEMA {{sat_schema}} TO {{user_name}};


-- ============================================
-- 1. SAT_SSM_MASTER_TABLE
-- ============================================
CREATE TABLE IF NOT EXISTS {{sat_schema}}.sat_ssm_master (
    tag_id text NULL,
    "date" timestamp NULL,
    lon NUMERIC NULL,
    lat NUMERIC NULL,
    x NUMERIC NULL,
    y NUMERIC NULL,
    x_se NUMERIC NULL,
    y_se NUMERIC NULL,
    u NUMERIC NULL,
    v NUMERIC NULL,
    u_se NUMERIC NULL,
    v_se NUMERIC NULL,
    s NUMERIC NULL,
    s_se NUMERIC NULL,
    cid text null,
    common_name text null
);

-- ============================================
-- 2. SAT_SSM_UPLOAD_LOG_TABLE
-- ============================================
CREATE TABLE IF NOT EXISTS {{sat_schema}}.sat_ssm_upload_logs (
    id VARCHAR(100) PRIMARY KEY,
    start_datetime TIMESTAMPTZ NOT NULL,
    end_datetime TIMESTAMPTZ NULL,
    error_message TEXT NULL,
    ssmoutput_table TEXT NULL,
    source_file TEXT NULL,
    source_file_last_modified TIMESTAMPTZ NULL,
    raw_table_created BOOLEAN NULL,
    constraint_applied BOOLEAN NULL,
    loaded_rows INTEGER NULL
);

-- ============================================
-- 3. SAT_SSM_SUMMARY_TABLE
-- ============================================
CREATE TABLE IF NOT EXISTS {{sat_schema}}.sat_ssm_summary (
    sat_ssm_table_name VARCHAR(200) NOT NULL,
    tag_id TEXT NOT NULL,
    program TEXT NULL,
    cid TEXT NULL,
    collectioncode TEXT NULL,
    row_count INTEGER,
    min_date TIMESTAMPTZ,
    max_date TIMESTAMPTZ,
    last_updated TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    latest_lat NUMERIC NULL,
    latest_lon NUMERIC NULL,
    common_name TEXT NULL,
    UNIQUE (sat_ssm_table_name, tag_id)
);

ALTER TABLE {{sat_schema}}.sat_ssm_summary ADD PRIMARY KEY (sat_ssm_table_name, tag_id);

-- ============================================
-- 4. SAT_META_TABLE (sat_deployments)
-- ============================================
CREATE TABLE IF NOT EXISTS {{sat_schema}}.sat_deployments (
    campaign_id TEXT,
    tag_id TEXT,
    ptt BIGINT,
    deployment_start TIMESTAMPTZ,
    deployment_lon NUMERIC,
    deployment_lat NUMERIC,
    wmo_platform_code TEXT,
    instrument_model TEXT,
    common_name TEXT,
    scientific_name TEXT,
    time_coverage_start TIMESTAMPTZ,
    time_coverage_end TIMESTAMPTZ,
    qc_version TEXT,
    qc_run_date TIMESTAMPTZ,
    instrument_serial_number TEXT,
    min_depth NUMERIC,
    max_depth NUMERIC,
    date_updated timestamptz DEFAULT CURRENT_TIMESTAMP NOT NULL,
    PRIMARY KEY (campaign_id, tag_id, ptt)
);

-- ============================================
-- Optional: Create indexes for better performance
-- ============================================
CREATE INDEX IF NOT EXISTS idx_ssm_summary_last_updated
    ON {{sat_schema}}.sat_ssm_summary (last_updated);

CREATE INDEX IF NOT EXISTS idx_ssm_summary_program
    ON {{sat_schema}}.sat_ssm_summary (program);

CREATE INDEX IF NOT EXISTS idx_sat_deployments_tag_id
    ON {{sat_schema}}.sat_deployments (tag_id);

CREATE INDEX IF NOT EXISTS idx_sat_deployments_campaign_id
    ON {{sat_schema}}.sat_deployments (campaign_id);

-- ============================================
-- Verify tables were created
-- ============================================
SELECT
    schemaname,
    tablename,
    tableowner
FROM pg_tables
WHERE schemaname = 'satnrt'
ORDER BY tablename;
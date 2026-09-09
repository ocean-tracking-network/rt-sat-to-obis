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
-- Create functions to pull satellite tags and animals from otnunit
-- ============================================

CREATE TABLE IF NOT EXISTS obis.otn_satellite_tags_animals (
    basisofrecord varchar(256),
    institutioncode varchar(200),
    collectioncode varchar(200),
    catalognumber varchar(200),
    datelastmodified varchar(200),
    scientificname varchar(200),
    commonname varchar,
    collector varchar(200),
    datecollected timestamp,
    timezone varchar(100),
    yearcollected varchar(8),
    monthcollected varchar(4),
    daycollected varchar(4),
    julianday int4,
    timeofday float8,
    latitude float8,
    longitude float8,
    coordinateprecision float8,
    locality text,
    fieldnumber varchar(100),
    the_geom public.geometry,
    stock text,
    wild_ind text,
    sex text,
    observedindividualcount numeric,
    observedweight numeric,
    length numeric,
    lengthtype text,
    length2 numeric,
    length2type text,
    age numeric,
    ageunit text,
    lifestage text,
    lifestagedescription text,
    datereleaseanimal date,
    datedetectionsreleased date,
    notes text,
    organism_id text,
    -- All columns from otn_satellite_tags
    tag_datelastmodified varchar,
    tag_institutioncode varchar,
    tag_collectioncode varchar,
    tag_catalognumber varchar,
    ptt_code varchar,
    tag_startdatetime timestamp,
    tag_enddatetime timestamp,
    tag_timezone varchar,
    tag_locality varchar,
    tag_latitude numeric,
    tag_longitude numeric,
    instrumenttype varchar,
    instrumentmodel varchar,
    collectornumber varchar,
    fieldnumber_tag varchar,
    relationshiptype varchar,
    relatedcatalogitem varchar,
    tag_the_geom public.geometry,
    tag_notes text
);


CREATE OR REPLACE FUNCTION obis.repopulate_satellite_tags(
    p_username TEXT,
    p_password TEXT
)
RETURNS VOID AS
$$
DECLARE
    v_source_conn TEXT := 'host=db.load.oceantrack.org port=5432 dbname=otnunit user=' || p_username || ' password=' || p_password;
BEGIN
    -- Truncate existing tables
    TRUNCATE TABLE obis.otn_satellite_tags;
    TRUNCATE TABLE obis.otn_satellite_tags_animals;

    -- Populate otn_satellite_tags
    INSERT INTO obis.otn_satellite_tags (
        datelastmodified,
        institutioncode,
        collectioncode,
        catalognumber,
        ptt_code,
        startdatetime,
        enddatetime,
        timezone,
        locality,
        latitude,
        longitude,
        instrumenttype,
        instrumentmodel,
        collectornumber,
        fieldnumber,
        relationshiptype,
        relatedcatalogitem,
        the_geom,
        notes
    )
    SELECT
        datelastmodified,
        institutioncode,
        collectioncode,
        catalognumber,
        ptt_code,
        startdatetime::timestamp,
        enddatetime::timestamp,
        timezone,
        locality,
        latitude,
        longitude,
        instrumenttype,
        instrumentmodel,
        collectornumber,
        fieldnumber,
        relationshiptype,
        relatedcatalogitem,
        ST_SetSRID(ST_MakePoint(longitude, latitude), 4326) AS the_geom,
        notes
    FROM dblink(
        v_source_conn,
        'SELECT datelastmodified, institutioncode, collectioncode, catalognumber, ptt_code, startdatetime, enddatetime, timezone, locality, latitude, longitude, instrumenttype, instrumentmodel, collectornumber, fieldnumber, relationshiptype, relatedcatalogitem, notes FROM obis.otn_satellite_tags'
    ) AS t (
        datelastmodified varchar,
        institutioncode varchar,
        collectioncode varchar,
        catalognumber varchar,
        ptt_code varchar,
        startdatetime text,
        enddatetime text,
        timezone varchar,
        locality varchar,
        latitude numeric,
        longitude numeric,
        instrumenttype varchar,
        instrumentmodel varchar,
        collectornumber varchar,
        fieldnumber varchar,
        relationshiptype varchar,
        relatedcatalogitem varchar,
        notes text
    );

    -- Populate otn_satellite_tags_animals
    INSERT INTO obis.otn_satellite_tags_animals
    SELECT
        oa.*,
        ot.datelastmodified,
        ot.institutioncode,
        ot.collectioncode,
        ot.catalognumber,
        ot.ptt_code,
        ot.startdatetime,
        ot.enddatetime,
        ot.timezone,
        ot.locality,
        ot.latitude,
        ot.longitude,
        ot.instrumenttype,
        ot.instrumentmodel,
        ot.collectornumber,
        ot.fieldnumber,
        ot.relationshiptype,
        ot.relatedcatalogitem,
        ot.the_geom,
        ot.notes
    FROM dblink(
        v_source_conn,
        'SELECT basisofrecord, institutioncode, collectioncode, catalognumber, datelastmodified, scientificname, commonname, collector, datecollected, timezone, yearcollected, monthcollected, daycollected, julianday, timeofday, latitude, longitude, coordinateprecision, locality, fieldnumber, the_geom, stock, wild_ind, sex, observedindividualcount, observedweight, length, lengthtype, length2, length2type, age, ageunit, lifestage, lifestagedescription, datereleaseanimal, datedetectionsreleased, notes, organism_id FROM obis.otn_animals'
    ) AS oa (
        basisofrecord varchar(256),
        institutioncode varchar(200),
        collectioncode varchar(200),
        catalognumber varchar(200),
        datelastmodified varchar(200),
        scientificname varchar(200),
        commonname varchar,
        collector varchar(200),
        datecollected timestamp,
        timezone varchar(100),
        yearcollected varchar(8),
        monthcollected varchar(4),
        daycollected varchar(4),
        julianday int4,
        timeofday float8,
        latitude float8,
        longitude float8,
        coordinateprecision float8,
        locality text,
        fieldnumber varchar(100),
        the_geom public.geometry,
        stock text,
        wild_ind text,
        sex text,
        observedindividualcount numeric,
        observedweight numeric,
        length numeric,
        lengthtype text,
        length2 numeric,
        length2type text,
        age numeric,
        ageunit text,
        lifestage text,
        lifestagedescription text,
        datereleaseanimal date,
        datedetectionsreleased date,
        notes text,
        organism_id text
    )
    JOIN obis.otn_satellite_tags ot
    ON oa.catalognumber = ot.relatedcatalogitem;

EXCEPTION
    WHEN OTHERS THEN
        RAISE;
END;
$$
LANGUAGE plpgsql;

CREATE TABLE obis.vendor_ref_otn_catalognumber_match (
    tag_ref VARCHAR(255) UNIQUE,
    catalognumber VARCHAR(255) UNIQUE,
    UNIQUE (tag_ref, catalognumber)
);

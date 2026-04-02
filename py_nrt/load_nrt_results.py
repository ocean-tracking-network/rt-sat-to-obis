import glob
import io
import os
import socket
from pathlib import Path
from typing import List, Union, Dict, Any

from py_nrt.common import print_error, get_engine
from sqlalchemy.engine import Engine
from sqlalchemy import inspect

# OTN_NRT_SCHEMA = 'otn_realtime'
OTN_NRT_SCHEMA = 'test'
NRT_UPLOAD_LOG_TABLE = 'nrt_ssm_upload_logs'
OTN_NRT_SSM_SUMMARY_TABLE = 'otn_nrt_ssm_summary'


import pandas as pd
from datetime import datetime, timedelta
from sqlalchemy import create_engine, text
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
exclude_folders=['maps', 'diag', 'aodn']


def check_otn_nrt_backend(engine: Engine, verbose: bool=True) -> bool:
    """
    Get loaners in dataframe
    :param engine:
    :param verbose:
    :return:
    """
    inspector = inspect(engine)

    if OTN_NRT_SCHEMA in inspector.get_schema_names():
        print(f'Will upload QCed results into HOST: {engine.url.host} DB: {engine.url.database} schema: {OTN_NRT_SCHEMA}')
        return True

    if verbose:
        print(f'Schema {OTN_NRT_SCHEMA} does not exist')
    return False


def get_files_by_pattern(folder: str, file_pattern: str) -> List[Path]:
    """
    Find all files matching a pattern in a folder and its subfolders.

    Args:
    folder: relative folder to current folder.
    file_pattern: file name pattern
    Returns: List of Path objects for files matching the pattern.
    """
    folder_path = Path(folder)
    if not folder_path.exists():
        print_error(f'NRT folder is not found: {folder_path}')
        return []
    csv_files = list(folder_path.rglob(file_pattern))
    return csv_files


def get_qced_programs(qc_output_path: str) -> list[str]:
    """
    Get first-level folders(program) in qc_output_path, excluding specified folders.
    Args:
        qc_output_path: Path to the QC output directory

    Returns:
        list[str]: List of first-level folder names (excluding those in exclude_folders)
    """
    if (not os.path.exists(qc_output_path)) or (not os.path.isdir(qc_output_path)):
        print(f"Warning: Path {qc_output_path} does not exist or not a directory")
        return []

    programs = []
    for sub_folder in os.listdir(qc_output_path):
        if sub_folder not in exclude_folders and not sub_folder.startswith('.'):
            programs.append(sub_folder)

    return sorted(programs)


def get_project_qc_results_for_program(qc_output_path: str, program: str=None) -> dict[str, datetime]:
    """
    Get QCed projects for given program.
    Args:
        qc_output_path: Path to the QC output directory
        program: NRT program

    Returns:
        dict[str]: a map of the QCed results to last_modified
    """
    program_path = os.path.join(qc_output_path, program)
    ssmoutput_last_modified_map = {}
    for sub_folder in os.listdir(program_path):
        project_path = os.path.join(qc_output_path, program, sub_folder)
        if sub_folder not in exclude_folders and not sub_folder.startswith('.'):
            print(f'Found project folder for {program}: {project_path}')
            ssmoutputs_files = list(Path(project_path).glob('*ssmoutputs*_nrt.csv'))
            if ssmoutputs_files:
                project_ssmoutputs = str(ssmoutputs_files[0])
                last_modified = datetime.fromtimestamp(os.path.getmtime(ssmoutputs_files[0]))
                print(f"Found SSM results: "
                      f"{ssmoutputs_files[0]} - last updated on {last_modified}")
                ssmoutput_last_modified_map[project_ssmoutputs] = last_modified
            else:
                print(f"-- No SSM result found.")
    return ssmoutput_last_modified_map


def load_to_nrt_db(engine: Engine, ssmoutput_last_modified_map: dict[str, str]):
    for output_csv, last_modified in ssmoutput_last_modified_map.items():
        proj = output_csv.split(os.path.sep)[-2]
        prev_load_df = get_loaded_proj_table_info(engine, proj)
        if prev_load_df is not None and len(prev_load_df) > 0:
            prev_timestamp = pd.to_datetime(prev_load_df.iloc[0]['source_file_last_modified']).tz_localize(None)
            current_timestamp = pd.to_datetime(last_modified).tz_localize(None)
            if abs((current_timestamp - prev_timestamp).total_seconds()) < 2:
                print(f"SSM results have been loaded for table {proj} - last modified on {prev_timestamp.strftime('%Y_%m_%d_%H_%M_%S')}. Skipping...")
                continue

        summary_df = load_csv_to_db(engine, proj, output_csv, last_modified, OTN_NRT_SCHEMA)
        print(f'Uploaded SSM results to  HOST: {engine.url.host} DB: {engine.url.database} Schema: {OTN_NRT_SCHEMA}.{proj}')
        return summary_df


def get_loaded_proj_table_info(engine: Engine, table_name: str, schema: str=OTN_NRT_SCHEMA) -> dict[str, str]:
    inspector = inspect(engine)
    if not inspector.has_table(NRT_UPLOAD_LOG_TABLE, schema=OTN_NRT_SCHEMA) or (not inspector.has_table(table_name, schema=schema)):
        return {}

    log_sql = f"""
        SELECT ssmoutput_table, source_file_last_modified 
        FROM {schema}.{NRT_UPLOAD_LOG_TABLE}
        WHERE constraint_applied = true
        AND ssmoutput_table = '{table_name}'
        ORDER BY source_file_last_modified DESC
        LIMIT 1
    """
    with engine.begin() as conn:
        result = conn.execute(text(log_sql))
        rows = result.fetchall()

        if not rows:
            return pd.DataFrame()

    return pd.DataFrame(rows, columns=result.keys())


def init_nrt_upload_log_table(engine, schema, start_datetime, table_name):
    """
    Initialize a new upload log entry and return the log_id.
    """
    log_id = f"{get_ip_by_hostname()}_{table_name}_{start_datetime.replace(':', '_').replace(' ', '_')}"

    inspector = inspect(engine)
    if not inspector.has_table(NRT_UPLOAD_LOG_TABLE, schema=schema):
        create_table_sql = f'''
        CREATE TABLE IF NOT EXISTS {schema}.{NRT_UPLOAD_LOG_TABLE} (
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
        '''
        with engine.begin() as conn:
            conn.execute(text(create_table_sql))

    with engine.begin() as conn:
        conn.execute(
            text(f"""
                INSERT INTO {schema}.{NRT_UPLOAD_LOG_TABLE}
                (id, start_datetime)
                VALUES (:id, :start_datetime)
                RETURNING id
            """),
            {
                'id': log_id,
                'start_datetime': start_datetime
            }
        )

    return log_id


def load_csv_to_db(engine: Engine, table_name: str, csv_path: str, source_file_last_modified: datetime,  schema: str = OTN_NRT_SCHEMA) -> pd.DataFrame:
    """
    Args:
        engine: SQLAlchemy engine instance connected to the PostgreSQL database.
        table_name: Name of the target table to create/replace.
        csv_path: Path to the CSV file to be loaded.
        schema: Database schema. Defaults to OTN_NRT_SCHEMA

    Returns:
        bool: True if the CSV was successfully loaded.
    """
    full_table_name = f'{schema}.{table_name}'
    now_str = datetime.utcnow().strftime('%Y_%m_%d_%H_%M_%S')
    backup_table_name = f'{table_name}_{now_str}'
    start_time = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    log_id = init_nrt_upload_log_table(engine, schema, start_time, table_name)

    inspector = inspect(engine)
    table_exists = inspector.has_table(table_name, schema=schema)

    try:
        # Backup table if exists
        if table_exists:
            with engine.begin() as conn:
                conn.execute(text(f'ALTER TABLE {full_table_name} RENAME TO {backup_table_name}'))

        with engine.begin() as conn:
            # Read header to define columns (all as TEXT for simplicity)
            df_header = pd.read_csv(csv_path, nrows=0)
            col_defs = [f'"{col}" TEXT' for col in df_header.columns]
            create_sql = f'CREATE UNLOGGED TABLE {full_table_name} (\n  ' + ',\n  '.join(col_defs) + '\n)'
            conn.execute(text(create_sql))

        with engine.connect() as conn:
            with open(csv_path, 'r') as f:
                next(f)  # skip header
                raw_conn = conn.connection
                with raw_conn.cursor() as cursor:
                    cursor.copy_expert(f"COPY {full_table_name} FROM STDIN WITH CSV", f)
                raw_conn.commit()

            update_log_checkpoint(engine, schema, log_id, {'source_file': csv_path, 'source_file_last_modified': source_file_last_modified.strftime('%Y-%m-%d %H:%M:%S'), 'raw_table_created': True})

        with engine.connect() as conn:
            result = conn.execute(text(f'SELECT COUNT(*) FROM {full_table_name}'))
            rows_loaded = result.scalar()

        print(f"Successfully loaded {rows_loaded} rows into {full_table_name}")

        transform_nrt_table(engine, schema, table_name)
        update_log_checkpoint(engine, schema, log_id, {'ssmoutput_table': table_name, 'loaded_rows': rows_loaded, 'constraint_applied': True, 'end_datetime': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')})

        with engine.connect() as conn:
            conn.execute(text(f'DROP TABLE IF EXISTS {schema}.{backup_table_name}'))
    except Exception as e:
        update_log_checkpoint(engine, schema, log_id, {'error_message': str(e)})
        # If load failed: renamed an original table, try to restore it
        if table_exists and inspector.has_table(backup_table_name, schema=schema):
            with engine.begin() as conn_restore:
                # Drop the failed new table
                conn_restore.execute(text(f'DROP TABLE IF EXISTS {full_table_name}'))
                # Rename backup back to original name
                conn_restore.execute(text(f'ALTER TABLE {schema}.{backup_table_name} RENAME TO {table_name}'))
                print(f"Restored original table after load error: {table_name}")
        raise RuntimeError(f"CSV load failed: {e}") from e

    summary_df = update_otn_nrt_catalog(engine, schema, table_name)
    return summary_df


def transform_nrt_table(engine: Engine, schema: str, table_name: str):
    """
    Transform columns of a table from TEXT to desired data types.

    Args:
        engine: SQLAlchemy engine.
        schema: Database schema.
        table_name: Name of the table to transform.

    Returns:
        None
    """
    full_table_name = f'{schema}.{table_name}'
    float_columns = ['lon', 'lat', 'x', 'y', 'x_se', 'y_se', 'u', 'v', 'u_se', 'v_se', 's', 's_se']
    datetime_columns = ['date']
    inspector = inspect(engine)
    columns = [col['name'] for col in inspector.get_columns(table_name, schema=schema)]

    with engine.begin() as conn:
        # Convert to LOGGED
        conn.execute(text(f'ALTER TABLE {full_table_name} SET LOGGED'))

        # Convert each column
        for col in float_columns:
            alter_sql = f'''
                ALTER TABLE {full_table_name} 
                ALTER COLUMN "{col}" TYPE FLOAT 
                USING NULLIF("{col}", 'NA')::FLOAT
            '''
            conn.execute(text(alter_sql))

        for col in datetime_columns:
            alter_sql = f'''
                ALTER TABLE {full_table_name} 
                ALTER COLUMN "{col}" TYPE TIMESTAMP 
                USING "{col}"::TIMESTAMP
            '''
            conn.execute(text(alter_sql))

        # Rename to tag_id column
        if 'ref' in columns:
            conn.execute(text(f'ALTER TABLE {full_table_name} RENAME COLUMN "ref" TO "tag_id"'))
        elif 'DeploymentID' in columns:
            conn.execute(
                text(f'ALTER TABLE {full_table_name} RENAME COLUMN "DeploymentID" TO "tag_id"'))

    # Add index
    with engine.begin() as conn:
        conn.execute(text(f'CREATE INDEX IF NOT EXISTS idx_{table_name}_tag_id_date ON {full_table_name} ("tag_id", "date")'))


def update_log_checkpoint(engine: Engine, schema: str, log_id: int, updates: Dict[str, Any]) -> None:
    """
    Update specific fields in the log at checkpoints
    """
    if not log_id:
        print("Warning: No log_id provided for checkpoint update")
        return

    # Add the ID to the updates
    updates['id'] = log_id

    # Build dynamic UPDATE SQL
    update_columns = [col for col in updates.keys() if col != 'id']
    set_clause = ", ".join([f"{col} = :{col}" for col in update_columns])

    sql = f"""
        UPDATE {schema}.{NRT_UPLOAD_LOG_TABLE}
        SET {set_clause}
        WHERE id = :id
    """

    with engine.begin() as conn:
        conn.execute(text(sql), updates)
        print(f"Checkpoint updated for log {log_id}: {list(updates.keys())}")


def build_log_id(start_datetime: str, table_name:str):
    log_id = get_ip_by_hostname() + '_' + start_datetime.replace(':', '_').replace(':', '_') + ' ' + table_name
    return log_id


def get_ip_by_hostname():
    """
    Get IP address
    """
    ip_address = 'unknown_ip'
    try:
        ip_address = socket.gethostbyname(socket.gethostname())
    except Exception:
        print('Warning: can not get IP address.')
    return ip_address


def create_otn_nrt_ssm_summary(engine: Engine, schema: str):
    """
    Create the OTN NRT catalog table to track all data tables with tag and species info.
    """
    full_table_name = f'{schema}.{OTN_NRT_SSM_SUMMARY_TABLE}'
    create_sql = f'''
    CREATE TABLE IF NOT EXISTS {full_table_name} (
        id SERIAL PRIMARY KEY,
        nrt_ssm_table_name VARCHAR(200) NOT NULL,
        tag_id TEXT NOT NULL,
        program TEXT NULL,
        cid TEXT NULL,
        collectioncode TEXT NULL,
        row_count INTEGER,
        min_date TIMESTAMPTZ,
        max_date TIMESTAMPTZ,
        last_updated TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        latest_lat float8 NULL,
        latest_lon float8 NULL,
        common_name TEXT NULL,
        UNIQUE (nrt_ssm_table_name, tag_id)
    );
    ALTER TABLE test.otn_nrt_ssm_summary ADD PRIMARY KEY (nrt_ssm_table_name, tag_id);
    '''

    with engine.begin() as conn:
        conn.execute(text(create_sql))


def update_otn_nrt_catalog(engine: Engine, schema: str, ssm_result_table: str) -> pd.DataFrame:
    """
    Update OTN NRT catalog with dynamic CID detection.
    """
    summary_df = pd.DataFrame
    inspector = inspect(engine)
    if not inspector.has_table(OTN_NRT_SSM_SUMMARY_TABLE, schema=schema):
        create_otn_nrt_ssm_summary(engine, schema)

    # Check if CID column exists
    source_columns = [col['name'] for col in inspector.get_columns(ssm_result_table, schema=schema)]
    has_cid = 'cid' in source_columns

    # Build dynamic SQL
    if has_cid:
        query = f"""
            WITH 
            tag_aggregates AS (
                SELECT 
                    tag_id,
                    MIN(date) as min_date,
                    MAX(date) as max_date,
                    COUNT(*) as row_count
                FROM {schema}.{ssm_result_table}
                WHERE tag_id IS NOT NULL AND tag_id != ''
                GROUP BY tag_id
            ),
            tag_latest_info AS (
                SELECT DISTINCT ON (tag_id)
                    tag_id,
                    lon as latest_lon,
                    lat as latest_lat,
                    cid as latest_cid
                FROM {schema}.{ssm_result_table}
                WHERE tag_id IS NOT NULL AND tag_id != ''
                ORDER BY tag_id, date DESC
            )
            INSERT INTO {schema}.{OTN_NRT_SSM_SUMMARY_TABLE}
            (nrt_ssm_table_name, tag_id, min_date, max_date, row_count, cid, latest_lon, latest_lat)
            SELECT 
                '{ssm_result_table}' as nrt_ssm_table_name,
                a.tag_id,
                a.min_date,
                a.max_date,
                a.row_count,
                l.latest_cid,
                l.latest_lon,
                l.latest_lat
            FROM tag_aggregates a
            LEFT JOIN tag_latest_info l ON a.tag_id = l.tag_id
            ON CONFLICT (nrt_ssm_table_name, tag_id) DO UPDATE SET
                min_date = EXCLUDED.min_date,
                max_date = EXCLUDED.max_date,
                row_count = EXCLUDED.row_count,
                cid = EXCLUDED.cid,
                latest_lon = EXCLUDED.latest_lon,
                latest_lat = EXCLUDED.latest_lat,
                last_updated = CURRENT_TIMESTAMP
            RETURNING *
        """
    else:
        query = f"""
            WITH 
            tag_aggregates AS (
                SELECT 
                    tag_id,
                    MIN(date) as min_date,
                    MAX(date) as max_date,
                    COUNT(*) as row_count
                FROM {schema}.{ssm_result_table}
                WHERE tag_id IS NOT NULL AND tag_id != ''
                GROUP BY tag_id
            ),
            tag_latest_info AS (
                SELECT DISTINCT ON (tag_id)
                    tag_id,
                    lon as latest_lon,
                    lat as latest_lat
                FROM {schema}.{ssm_result_table}
                WHERE tag_id IS NOT NULL AND tag_id != ''
                ORDER BY tag_id, date DESC
            )
            INSERT INTO {schema}.{OTN_NRT_SSM_SUMMARY_TABLE}
            (nrt_ssm_table_name, tag_id, min_date, max_date, row_count, latest_lon, latest_lat)
            SELECT 
                '{ssm_result_table}' as nrt_ssm_table_name,
                a.tag_id,
                a.min_date,
                a.max_date,
                a.row_count,
                l.latest_lon,
                l.latest_lat
            FROM tag_aggregates a
            LEFT JOIN tag_latest_info l ON a.tag_id = l.tag_id
            ON CONFLICT (nrt_ssm_table_name, tag_id) DO UPDATE SET
                min_date = EXCLUDED.min_date,
                max_date = EXCLUDED.max_date,
                row_count = EXCLUDED.row_count,
                latest_lon = EXCLUDED.latest_lon,
                latest_lat = EXCLUDED.latest_lat,
                last_updated = CURRENT_TIMESTAMP
            RETURNING *
        """

    with engine.begin() as conn:
        result = conn.execute(text(query))
        rows = result.fetchall()

        if not rows:
            print(f"No tags found in {ssm_result_table}")
            return summary_df

        summary_df = pd.DataFrame(rows, columns=result.keys())
        print(f"Updated catalog with {len(summary_df)} tag records for {ssm_result_table}")

    return summary_df


def get_today_argosqc_run_details(argosqc_run_details_csv: str = '../argosqc_run_details.csv')-> pd.DataFrame:
    """Read argosqc_run_details.csv to parse today's results"""
    all_detail_df = pd.read_csv(argosqc_run_details_csv)
    all_detail_df['qc_start_datetime'] = pd.to_datetime(all_detail_df['qc_start_datetime'], errors='coerce')

    # Filter for rows >= today 0 AM
    today_detail_df = all_detail_df[all_detail_df['qc_start_datetime'] >= pd.Timestamp.now().normalize()].copy()
    # Remove qc_start_datetime and duplicates
    today_detail_df.drop(columns=['qc_start_datetime'], inplace=True)
    today_detail_df.drop_duplicates(subset=['program', 'output_dir', 'common_name'], inplace=True)
    print(f"Rows from {datetime.now().date()} 00:00:00 onwards: {len(today_detail_df)}")
    if today_detail_df.empty:
        latest_runs = all_detail_df.nlargest(5, 'qc_start_datetime')[['qc_start_datetime', 'program', 'common_name']]
        raise Exception(
            f'No ArgosQC results found for today.\n\nThe latest runs (top 5 by qc_start_datetime DESC):\n{latest_runs.to_string(index=False)}')
    return today_detail_df


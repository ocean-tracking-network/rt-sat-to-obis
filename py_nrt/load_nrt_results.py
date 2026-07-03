import glob
import io
import os
import re
import socket
from pathlib import Path
from typing import List, Union, Dict, Any

from py_nrt.common import print_error, get_engine
from sqlalchemy.engine import Engine
from sqlalchemy import inspect

# OTN_NRT_SCHEMA = 'satnrt'
OTN_NRT_SCHEMA = 'test'
OTN_NRT_SSM_MASTER_TABLE = 'nrt_ssm_master'
NRT_UPLOAD_LOG_TABLE = 'nrt_ssm_upload_logs'
OTN_NRT_SSM_SUMMARY_TABLE = 'nrt_ssm_summary'
TAG_META_FILE_PATTERN= r'.*metadata.*'
MIN_MAX_DEPTH_FILE_PATTERN = r'.*MinMaxDepth.*|.*_summary_.*'
QC_OUTPUT_PATH = 'qc'

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
    found_files = list(folder_path.rglob(file_pattern))
    if not found_files:
        found_files = [f for f in folder_path.glob('*') if re.search(file_pattern, f.name)]
    return found_files


def get_qced_programs(qc_output_path: str) -> list[str]:
    """
    Call get_qced_program_campaigns and get keys from the returned dict.
    Args:
        qc_output_path: Path to the QC output directory
            expecteded QC folder structure: {program}/{program}_{campaign}
    Returns:
        list[str]: list of programs
   """
    program_campaigns = get_qced_program_campaigns(qc_output_path)
    return program_campaigns.keys()


def get_qced_program_campaigns(qc_output_path: str) -> dict[str: list[str]]:
    """
    Get first-level folders (program) to campaign (second-level folders) in qc_output_path, excluding specified folders.
    Args:
        qc_output_path: Path to the QC output directory
            expecteded QC folder structure: {program}/{program}_{campaign}
    Returns:
        dict[str: list[str]]: dict of program: [campaigns...]
             e.g.,
             {'imos': ['imos_ct180', 'imos_ct182'],
             'irap': ['irap_damianlidgard_grey_seal']}
   """
    if (not os.path.exists(qc_output_path)) or (not os.path.isdir(qc_output_path)):
        print(f"Warning: Path {qc_output_path} does not exist or not a directory")
        return {}

    program_campaigns = {}
    for first_level_sub_folder in os.listdir(qc_output_path):
        campaigns = []
        if first_level_sub_folder not in exclude_folders and not first_level_sub_folder.startswith('.'):
            for second_level_sub_folder in os.listdir(os.path.join(qc_output_path, first_level_sub_folder)):
                if second_level_sub_folder not in exclude_folders and not second_level_sub_folder.startswith('.'):
                    campaigns.append(second_level_sub_folder)

            program_campaigns.update({first_level_sub_folder:sorted(campaigns)})

    return program_campaigns


def get_campaign_qc_results_for_program(qc_output_path: str, program: str=None) -> dict[str, datetime]:
    """
    Get QCed campaigns for given program.
    Args:
        qc_output_path: Path to the QC output directory
        program: NRT program

    Returns:
        dict[str]: a map of the QCed results to last_modified
    """
    program_path = os.path.join(qc_output_path, program)
    ssmoutput_last_modified_map = {}
    for sub_folder in os.listdir(program_path):
        campaign_path = os.path.join(qc_output_path, program, sub_folder)
        if sub_folder not in exclude_folders and not sub_folder.startswith('.'):
            print(f'Found campaign folder for {program}: {campaign_path}')
            ssmoutputs_files = list(Path(campaign_path).glob('*ssmoutputs*_nrt.csv'))
            if ssmoutputs_files:
                campaign_ssmoutputs = str(ssmoutputs_files[0])
                last_modified = datetime.fromtimestamp(os.path.getmtime(ssmoutputs_files[0]))
                print(f"Found SSM results: "
                      f"{ssmoutputs_files[0]} - last updated on {last_modified}")
                ssmoutput_last_modified_map[campaign_ssmoutputs] = last_modified
            else:
                print(f"-- No SSM result found.")
    return ssmoutput_last_modified_map


def load_single_ssmoutput_to_nrt_db(engine: Engine, proj_table_name: str, ssmoutput_csv: str, last_modified: datetime) -> pd.DataFrame:
    """
    Load a single ssmoutput into NRT DB as proj_table_name - if file last modified date is newer than previously loaded.

    """
    summary_df = pd.DataFrame()
    prev_load_df = get_loaded_proj_table_info(engine, proj_table_name)
    if (prev_load_df is None) or (len(prev_load_df) == 0):
        print(f'This is the first time loading {proj_table_name}. Will create {OTN_NRT_SCHEMA}.{proj_table_name}...')
    else:
        prev_timestamp = pd.to_datetime(prev_load_df.iloc[0]['source_file_last_modified']).tz_localize(None)
        current_timestamp = pd.to_datetime(last_modified).tz_localize(None)
        if abs((current_timestamp - prev_timestamp).total_seconds()) < 2:
            print(f"SSM results have been loaded for table {proj_table_name} - last modified on {prev_timestamp.strftime('%Y_%m_%d_%H_%M_%S')}. Skipping...")
            return summary_df

    summary_df = load_csv_to_db(engine, proj_table_name, ssmoutput_csv, last_modified, OTN_NRT_SCHEMA)
    return summary_df


def load_to_nrt_db(engine: Engine, ssmoutput_last_modified_map: dict[str, str]):
    summary_df_list = []
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


def init_otn_nrt_ssm_master_table(engine, schema):
    inspector = inspect(engine)
    if not inspector.has_table(OTN_NRT_SSM_MASTER_TABLE, schema=schema):
        create_table_sql = f'''
            CREATE TABLE IF NOT EXISTS {schema}.{OTN_NRT_SSM_MASTER_TABLE} (
                tag_id text NULL,
                "date" timestamp NULL,
                lon float8 NULL,
                lat float8 NULL,
                x float8 NULL,
                y float8 NULL,
                x_se float8 NULL,
                y_se float8 NULL,
                u float8 NULL,
                v float8 NULL,
                u_se float8 NULL,
                v_se float8 NULL,
                s float8 NULL,
                s_se float8 NULL,
                cid text null,
                common_name text null
            )'''
        with engine.begin() as conn:
            conn.execute(text(create_table_sql))


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


def transform_nrt_table(engine: Engine, schema: str, table_name: str) -> None:
    """
    Transform columns of a table from TEXT to desired data types.

    Args:
        engine: SQLAlchemy engine.
        schema: Database schema.
        table_name: Name of the table to transform.

    Returns:
        None
    """
    init_otn_nrt_ssm_master_table(engine, schema)
    full_table_name = f'{schema}.{table_name}'
    number_columns = ['lon', 'lat', 'x', 'y', 'x_se', 'y_se', 'u', 'v', 'u_se', 'v_se', 's', 's_se']
    datetime_columns = ['date']
    text_columns = ['ptt', 'cid', 'common_name']
    inspector = inspect(engine)
    columns = [col['name'] for col in inspector.get_columns(table_name, schema=schema)]

    with engine.begin() as conn:
        # Convert to LOGGED
        conn.execute(text(f'ALTER TABLE {full_table_name} SET LOGGED'))

        # Convert each column
        for col in number_columns:
            alter_sql = f'''
                ALTER TABLE {full_table_name} 
                ALTER COLUMN "{col}" TYPE NUMBER 
                USING NULLIF("{col}", 'NA')::NUMBER
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
            conn.execute(text(f'ALTER TABLE {full_table_name} RENAME COLUMN "DeploymentID" TO "tag_id"'))

        for column in text_columns:
            if column not in columns:
                conn.execute(text(f'ALTER TABLE {full_table_name} ADD COLUMN "{column}" TEXT'))

    # Add index and inheritance
    with engine.begin() as conn:
        conn.execute(text(f'CREATE INDEX IF NOT EXISTS idx_{table_name}_tag_id_date ON {full_table_name} ("tag_id", "date")'))
        conn.execute(text(f'ALTER TABLE {full_table_name} INHERIT {schema}.{OTN_NRT_SSM_MASTER_TABLE}'))


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
    ALTER TABLE {full_table_name} ADD PRIMARY KEY (nrt_ssm_table_name, tag_id);
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




def parse_min_max_depth(qc_output_path: str=QC_OUTPUT_PATH, program: str='', cid: str='', verbose: bool = True) -> pd.DataFrame:
    """
    Get min_depth (always be 0) and max_depth from QCed results
    Args:
        qc_output_path: Base directory path containing QC output files.
            Defaults to QC_OUTPUT_PATH.
        program: Program name (e.g., 'imos').
        cid: Collection/device ID (e.g., 'ct180').
        verbose: If True, prints detailed progress information.
            Defaults to True.

    Returns:
        pandas.DataFrame: DataFrame containing min_depth and max_depth values.
            Returns empty DataFrame if no matching file is found.
            example output:
            tag_ig,ptt,min_depth,max_depth
            ct180-156-BAT-15,196997,0,600.0
    """
    program_cid_path = os.path.join(qc_output_path, program, f'{program}_{cid}')
    depth_files = get_files_by_pattern(program_cid_path, MIN_MAX_DEPTH_FILE_PATTERN)
    if not depth_files:
        print_error(f'No min max depth file found in {program_cid_path} by pattern {MIN_MAX_DEPTH_FILE_PATTERN}')
        return pd.DataFrame()

    depth_df = pd.read_csv(depth_files[0])

    # Define column mapping
    column_mapping = {
        'tag_ig': ['ref', 'DeploymentID', 'deployment_id', 'tag_id', 'tag', 'Tag'],
        'ptt': ['ptt', 'Ptt', 'ptt_id', 'PTT'],
        'max_depth': ['MaxDepth', 'max_depth', 'depth_max', 'max_depth_m', 'DepthMax']
    }

    selected_columns = {}
    for target_col, possible_cols in column_mapping.items():
        found_col = None
        for col in possible_cols:
            if col in depth_df.columns:
                found_col = col
                break
        if found_col is None:
            print_error(
                f"None of the expected columns for '{target_col}' found in {depth_df.columns.tolist()}"
            )
            return pd.DataFrame()
        selected_columns[target_col] = found_col
        if verbose:
            print(f"   Mapped: '{found_col}' ➔ '{target_col}'")

    # Select and rename columns
    try:
        depth_df = depth_df[
            [selected_columns['tag_ig'], selected_columns['ptt'], selected_columns['max_depth']]
        ].copy()
        depth_df.columns = ['tag_ig', 'ptt', 'max_depth']
    except KeyError as e:
        print_error(f"Column selection error: {e}")
        return pd.DataFrame()

    # Group by tag_ig and ptt to get the max of max_depth
    group_depth_df = (
        depth_df.groupby(['tag_ig', 'ptt'], as_index=False)
            .agg({
            'max_depth': 'max'
        })
    )

    # Add min_depth column with default value 0
    group_depth_df['min_depth'] = 0

    # Reorder columns
    group_depth_df = group_depth_df[['tag_ig', 'ptt', 'min_depth', 'max_depth']]

    if verbose:
        print(f"\n📈 Results: {len(group_depth_df)} unique (tag_ig, ptt) pairs")
        print(
            f"   Max depth range: {group_depth_df['max_depth'].min():.2f} - {group_depth_df['max_depth'].max():.2f}")
        print(f"\n📋 First 5 rows:")
        print(group_depth_df.head())

    return group_depth_df


def parse_tag_metadata(qc_output_path: str = QC_OUTPUT_PATH, program: str = '', cid: str = '',
                       verbose: bool = True) -> pd.DataFrame:
    """
    Parse tag metadata from QC summary files.

    This function searches for tag metadata files matching the pattern
    in the specified path, reads the first matching CSV file, and maps
    columns to standardized names.

    Args:
        qc_output_path: Base directory path containing QC output files.
            Defaults to QC_OUTPUT_PATH.
        program: Program name (e.g., 'imos').
        cid: Collection/device ID (e.g., 'ct180').
        verbose: If True, prints detailed progress information.
            Defaults to True.

    Returns:
        pandas.DataFrame: DataFrame with standardized column names.
            Missing columns are added with null values.

    Examples:
        >>> df = parse_tag_metadata('qc', 'imos', 'ct180')
        Looking in: qc/imos/imos_ct180
        ✓ Found: IMOS_ATF-SATTAG_Location-QC_summary_ct180_nrt.csv
        Mapped: 'device_id' ➔ 'tag_ig'
        Mapped: 'ptt' ➔ 'ptt'
        Mapped: 'max_depth' ➔ 'max_depth'
    """
    program_cid_path = os.path.join(qc_output_path, program, f'{program}_{cid}')

    if verbose:
        print(f"Looking in: {program_cid_path}")

    meta_files = get_files_by_pattern(program_cid_path, TAG_META_FILE_PATTERN)

    if not meta_files:
        print_error(
            f'No tag metadata file found in {program_cid_path} by pattern {TAG_META_FILE_PATTERN}')
        return pd.DataFrame()

    meta_df = pd.read_csv(meta_files[0])

    if verbose:
        print(f"\nLoaded {len(meta_df)} rows from {meta_files[0].name}")
        print(f"Available columns: {meta_df.columns.tolist()}")

    # Define column mapping
    column_mapping = {
        'program': ['sattag_program'],
        'tag_ig': ['device_id', 'deployment_id'],
        'ptt': ['ptt', 'Ptt', 'ptt_id', 'tag_ptt'],
        'deployment_start': ['deploy_date', 'release_date'],
        'deployment_lon': ['release_longitude', 'deploy_longitude', 'embark_longitude'],
        'deployment_lat': ['release_latitude', 'deploy_latitude', 'embark_latitude'],
        'wmo_platform_code': ['device_wmo_ref'],
        'instrument_model': ['tag_type', 'tag_model'],
        'common_name': ['common_name'],
        'scientific_name': ['species'],
        'time_coverage_start': ['qc_start_date'],
        'time_coverage_end': ['qc_end_date'],
        'qc_version': ['qc_version', 'qc_method_version'],
        'qc_method': ['qc_method'],
        'qc_version': ['qc_version'],
        'qc_run_date': ['qc_run_date'],
        'instrument_serial_number': ['tag_serial_number', 'body'],
    }

    selected_columns = {}
    missing_columns = []

    for target_col, possible_cols in column_mapping.items():
        found_col = None
        for col in possible_cols:
            if col in meta_df.columns:
                found_col = col
                break

        if found_col is None:
            missing_columns.append(target_col)
            if verbose:
                print(f"   ⚠ Column not found for '{target_col}', will set to null")
        else:
            selected_columns[target_col] = found_col
            if verbose:
                print(f"   Mapped: '{found_col}' ➔ '{target_col}'")

    # Check if we have at least the essential columns
    essential_columns = ['tag_ig', 'ptt']  # Define which columns are essential
    missing_essential = [col for col in essential_columns if col not in selected_columns]

    if missing_essential:
        print_error(f"Essential columns missing: {missing_essential}")
        print_error("Cannot proceed without essential columns")
        return pd.DataFrame()

    # Select existing columns
    existing_cols_to_select = list(selected_columns.values())

    try:
        # Select only columns that exist
        meta_df_selected = meta_df[existing_cols_to_select].copy()

        # Rename selected columns
        rename_dict = {v: k for k, v in selected_columns.items()}
        meta_df_selected = meta_df_selected.rename(columns=rename_dict)

        # Add missing columns with null values
        for missing_col in missing_columns:
            meta_df_selected[missing_col] = None

        if verbose and missing_columns:
            print(
                f"\n   Added {len(missing_columns)} column(s) with null values: {missing_columns}")

    except KeyError as e:
        print_error(f"Column selection error: {e}")
        return pd.DataFrame()

    return meta_df_selected
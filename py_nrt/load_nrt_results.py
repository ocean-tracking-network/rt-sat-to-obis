import glob
import io
import os
import socket
from pathlib import Path
from typing import List, Union, Dict, Any
from contextlib import closing

import pandas as pd
from dbtools.common import has_schema

from py_nrt.common import print_error, get_engine
from sqlalchemy.engine import Engine
from sqlalchemy import inspect

# OTN_NRT_SCHEMA = 'otn_realtime'
OTN_NRT_SCHEMA = 'test'
NRT_UPLOAD_LOG_TABLE = 'nrt_ssm_upload_logs'


def check_otn_nrt_backend(engine: Engine, verbose: bool=True) -> bool:
    """
    Get loaners in dataframe
    :param engine:
    :param verbose:
    :return:
    """
    get_engine()
    if has_schema(engine, OTN_NRT_SCHEMA):
        print(f'Will upload QCed results into HOST: {engine.url.host} DB: {engine.url.database} schema: {OTN_NRT_SCHEMA}')
        return True
    else:
        print(f'Schema: {OTN_NRT_SCHEMA} is not found in HOST: {engine.url.host} DB: {engine.url.database}')
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


def load_nrt_to_datastore(engine: Engine, nrt_file_pattern = 'ssmoutputs_*.csv'):
    """

    """
    nrt_qc_folder = 'output'
    for qced_nrt_file in get_files_by_pattern(nrt_qc_folder, nrt_file_pattern):
        nrt_df = pd.read_csv(qced_nrt_file)
        print(nrt_df)


import pandas as pd
import psycopg2
from io import StringIO
from datetime import datetime, timedelta
from sqlalchemy import create_engine, text
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
exclude_folders=['maps', 'diag']


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


def get_project_qc_results_for_program(qc_output_path: str, program: str=None) -> dict[str, str]:
    """
    Get QCed projects for given program.
    Args:
        qc_output_path: Path to the QC output directory
        program: NRT program

    Returns:
        dict[str]: a map of program_project to the QCed results
    """
    program_path = os.path.join(qc_output_path, program)
    project_path_map = {}
    for sub_folder in os.listdir(program_path):
        project_path = os.path.join(qc_output_path, program, sub_folder)
        if sub_folder not in exclude_folders and not sub_folder.startswith('.'):
            print(f'Found project folder for {program}: {project_path}')
            ssmoutputs_files = list(Path(project_path).glob('*ssmoutputs*_nrt.csv'))
            if ssmoutputs_files:
                project_ssmoutputs = str(ssmoutputs_files[0])
                project_path_map[sub_folder] = project_ssmoutputs
                last_modified = datetime.fromtimestamp(os.path.getmtime(ssmoutputs_files[0]))
                print(f"-- Found SSM results: {ssmoutputs_files[0]} - last updated on {last_modified.strftime('%Y-%m-%d %H:%M:%S')}")
            else:
                print(f"-- No SSM result found.")
    return project_path_map

def load_to_nrt_db(engine: Engine, proj_ssmourput_map: dict[str, str]):
    for proj, csv in proj_ssmourput_map.items():
        load_csv_to_unlogged_table(engine, proj, csv, OTN_NRT_SCHEMA)
    print(f'Uploaded SSM results to  HOST: {engine.url.host} DB: {engine.url.database} Schema: {OTN_NRT_SCHEMA}.{proj}')


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


def load_csv_to_unlogged_table(engine: Engine, table_name: str, csv_path: str, schema: str = OTN_NRT_SCHEMA) -> bool:
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

            update_log_checkpoint(engine, schema, log_id, {'source_file': csv_path,'raw_table_created': True})

        with engine.connect() as conn:
            result = conn.execute(text(f'SELECT COUNT(*) FROM {full_table_name}'))
            rows_loaded = result.scalar()

        print(f"Successfully loaded {rows_loaded} rows into {full_table_name}")

        transform_nrt_table(engine, schema,table_name)
        update_log_checkpoint(engine, schema, log_id, {'constraint_applied': True})

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

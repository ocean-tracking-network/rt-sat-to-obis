import glob
import io
import os
from pathlib import Path
from typing import List, Union
from contextlib import closing

import pandas as pd
from dbtools.common import has_schema

from py_nrt.common import print_error, get_engine
from sqlalchemy.engine import Engine
from sqlalchemy import inspect

# OTN_NRT_SCHEMA = 'otn_realtime'
OTN_NRT_SCHEMA = 'test'
NRT_UPLOAD_LOG = 'nrt_ssm_upload_logs'


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


def update_nrt_log_table(engine: Engine, schema: str, log_entry: dict[str, any]):
    """
    Create the upload_log table in the specified schema if it does not already exist.

    The table records metadata about CSV uploads, including timing, source file,
    target table name, whether constraints were applied, and number of rows loaded.

    Args:
        engine: SQLAlchemy Engine instance.
        schema: Database schema name.
        log_entry: dict of column and value to be updated

    Returns:
        None
    """
    inspector = inspect(engine)
    if not inspector.has_table(NRT_UPLOAD_LOG, schema=schema):
        create_table_sql = f'''
        CREATE TABLE IF NOT EXISTS {schema}.{NRT_UPLOAD_LOG} (
            id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
            start_datetime TIMESTAMPTZ NOT NULL,
            end_datetime TIMESTAMPTZ NULL,
            source_file TEXT NOT NULL,
            raw_table_created TEXT NULL,
            constraint_applied BOOLEAN NULL,
            loaded_rows INTEGER NULL
        );
        '''
        with engine.begin() as conn:
            conn.execute(text(create_table_sql))

    with engine.begin() as conn:
        conn.execute(
            text(f"""
                INSERT INTO {schema}.upload_log
                (start_datetime, end_datetime, source_file, raw_table_created, constraint_applied, loaded_rows)
                VALUES (:start, :end, :file, :table, :constraint, :rows)
            """),
            {
                'start_datetime': log_entry['start_datetime'],
                'end_datetime': log_entry['end_datetime'],
                'source_file': log_entry['source_file'],
                'table': log_entry['raw_table_created'],
                'constraint': log_entry['constraint_applied'],
                'rows': log_entry['loaded_rows']
            }
        )


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
    today_str = datetime.utcnow().strftime('%Y_%m_')
    backup_table_name = f'{table_name}_{today_str}'
    start_time = datetime.utcnow()

    inspector = inspect(engine)
    table_exists = inspector.has_table(table_name, schema=schema)

    if table_exists:
        with engine.begin() as conn:
            conn.execute(text(f'ALTER TABLE {full_table_name} RENAME TO {backup_table_name}'))

    rows_loaded = 0
    load_successful = False
    try:
        with engine.begin() as conn:
            # Read header to define columns (all as TEXT for simplicity)
            df_header = pd.read_csv(csv_path, nrows=0)
            col_defs = [f'"{col}" TEXT' for col in df_header.columns]
            create_sql = f'CREATE UNLOGGED TABLE {full_table_name} (\n  ' + ',\n  '.join(col_defs) + '\n)'
            conn.execute(text(create_sql))

        with open(csv_path, 'r') as f:
            next(f)  # skip header
            with engine.raw_connection() as raw_conn:
                with raw_conn.cursor() as cursor:
                    cursor.copy_expert(f"COPY {full_table_name} FROM STDIN WITH CSV", f)
                raw_conn.commit()

        with engine.connect() as conn:
            result = conn.execute(text(f'SELECT COUNT(*) FROM {full_table_name}'))
            rows_loaded = result.scalar()

        load_successful = True

    except Exception as e:
        # If load failed and we had renamed an original table, try to restore it
        if table_exists:
            try:
                with engine.begin() as conn_restore:
                    # Drop the failed new table
                    conn_restore.execute(text(f'DROP TABLE IF EXISTS {full_table_name}'))
                    # Rename backup back to original name
                    conn_restore.execute(text(f'ALTER TABLE {schema}.{backup_table_name} RENAME TO {table_name}'))
            except Exception as restore_error:
                print(f"Critical: Failed to restore original table after load error: {restore_error}")
        raise RuntimeError(f"CSV load failed: {e}") from e

    end_time = datetime.now(datetime.UTC)
    log_entry = {
        'start_datetime': start_time,
        'end_datetime': end_time,
        'source_file': csv_path,
        'raw_table_created': full_table_name,
        'constraint_applied': False,   # adjust if you later add constraints
        'loaded_rows': rows_loaded
    }
    update_nrt_log_table(engine, schema, log_entry)


def transform_nrt_table(engine: Engine, schema: str, table_name: str,
                        column_types: dict, add_indexes: list = None):
    """
    Transform columns of a table from TEXT to desired data types.

    Args:
        engine: SQLAlchemy engine.
        schema: Database schema.
        table_name: Name of the table to transform.
        column_types: Dictionary mapping column names to target PostgreSQL types.
                      Supported types: 'float', 'int', 'varchar', 'timestamp', 'date', 'boolean'.
                      For varchar, you can specify length like 'varchar(50)'.
        add_indexes: List of column names (or expressions) to create indexes on.
                     Each entry can be a string (column name) or a dict with 'columns' and 'index_name'.

    Returns:
        None

    Raises:
        SQLAlchemyError: If any ALTER or CREATE INDEX statement fails.
    """
    full_table_name = f'{schema}.{table_name}'

    # Mapping from our shorthand to PostgreSQL type with USING clause
    type_mapping = {
        'float': 'DOUBLE PRECISION USING {col}::DOUBLE PRECISION',
        'int': 'INTEGER USING {col}::INTEGER',
        'varchar': 'VARCHAR USING {col}::VARCHAR',  # base, can include length
        'timestamp': 'TIMESTAMP USING {col}::TIMESTAMP',
        'date': 'DATE USING {col}::DATE',
        'boolean': 'BOOLEAN USING {col}::BOOLEAN'
    }

    with engine.begin() as conn:
        conn.execute(text(f'ALTER TABLE {full_table_name} SET LOGGED'))
        # Apply column type changes
        for col, target_type in column_types.items():
            # Check if target_type includes a length spec (e.g., 'varchar(255)')
            if target_type.startswith('varchar'):
                base_type = 'varchar'
                # Use the exact type as given (e.g., VARCHAR(255))
                using_sql = f"{target_type} USING {col}::{target_type}"
            else:
                base_type = target_type.lower()
                if base_type not in type_mapping:
                    raise ValueError(f"Unsupported type: {target_type}. Supported: {list(type_mapping.keys())}")
                using_sql = type_mapping[base_type].format(col=col)

            alter_sql = f'ALTER TABLE {full_table_name} ALTER COLUMN "{col}" TYPE {using_sql}'
            conn.execute(text(alter_sql))

        # Add indexes
        if add_indexes:
            for idx_def in add_indexes:
                if isinstance(idx_def, str):
                    # Simple index on one column
                    idx_name = f"idx_{table_name}_{idx_def}"
                    idx_sql = f'CREATE INDEX {idx_name} ON {full_table_name} ("{idx_def}")'
                elif isinstance(idx_def, dict):
                    idx_name = idx_def.get('index_name', f"idx_{table_name}_custom")
                    columns = idx_def['columns']
                    if isinstance(columns, list):
                        col_list = ', '.join([f'"{c}"' for c in columns])
                    else:
                        col_list = f'"{columns}"'
                    idx_sql = f'CREATE INDEX {idx_name} ON {full_table_name} ({col_list})'
                else:
                    continue  # skip invalid definitions
                conn.execute(text(idx_sql))

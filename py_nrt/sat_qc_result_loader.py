import glob
import io
import os
import re
import socket
import itables
from pathlib import Path
from typing import List, Union, Dict, Any, Optional
from IPython.display import display, HTML

from py_nrt.common import print_error, get_engine, show_df, get_program_project_from_ssm_file, get_files_by_pattern, get_ip_by_hostname
from sqlalchemy.engine import Engine
from sqlalchemy import inspect
import pandas as pd
from datetime import datetime, timedelta
from sqlalchemy import create_engine, text
import logging


class SatQcResultsLoader:
    """
    A class to manage loading and processing of Satellite QC results into a database.

    - Reads QC output files from the filesystem
    - Loads SSM results into NRT database
    - Parses tag metadata and min/max depth information
    - Manages database schema and table operations
    - Tracks upload history and status
    """

    # Default DB settings
    SATNRT_SCHEMA = 'satnrt'
    SATDELAY_SCHEMA = 'satdelay'
    SAT_SSM_MASTER_TABLE = 'sat_ssm_master'
    SAT_SSM_UPLOAD_LOG_TABLE = 'sat_ssm_upload_logs'
    SAT_SSM_SUMMARY_TABLE = 'sat_ssm_summary'
    SAT_META_TABLE = 'sat_deployments'
    SAT_DB_INIT_FILE = 'init_sat_tables.sql'

    # Default file system settings
    TAG_META_FILE_PATTERN = r'.*metadata.*'
    QCED_OUTPUT_FILE_PATTERN = '*ssmoutputs*_nrt.csv'
    MIN_MAX_DEPTH_FILE_PATTERN = r'.*MinMaxDepth.*|.*summary_.*'
    QC_OUTPUT_PATH = 'qc'
    EXCLUDE_FOLDERS = ['maps', 'diag', 'aodn', 'mdb']

    def __init__(self, engine: Engine, schema: str = SATNRT_SCHEMA, qc_output_path: str = QC_OUTPUT_PATH, verbose: bool = True):
        """
        Initialize the SatQcResultsLoader.

        Args:
            engine: SQLAlchemy Engine object. If None, must be set later.
            qc_output_path: Path to the QC output directory
            schema: Database schema to use (default: SATNRT_SCHEMA)
            verbose: Whether to print verbose output
        """
        self.engine = engine
        self.qc_output_path = qc_output_path
        self.schema = schema
        self.verbose = verbose

        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)

    def check_sat_db(self) -> bool:
        """
        Verify Satellite DB tables and permissions.

        Returns:
            bool: True if all tables exist and user has permission, False otherwise
        """
        inspector = inspect(self.engine)
        if self.schema not in inspector.get_schema_names():
            raise RuntimeError(f'{self.schema} is not found in the list of schemas: {inspector.get_schema_names()}. \n'
                               f'Please sat_loader.init_database_tables() to create the schema.')

        # Check required tables
        required_tables = [
            self.SAT_SSM_MASTER_TABLE,
            self.SAT_SSM_UPLOAD_LOG_TABLE,
            self.SAT_SSM_SUMMARY_TABLE,
            self.SAT_META_TABLE
        ]

        missing_tables = []
        for table in required_tables:
            if not self.engine.has_table(table, schema=self.schema):
                missing_tables.append(table)

        if missing_tables:
            raise RuntimeError(f"Missing tables in schema '{self.schema}': {missing_tables} \nPlease contact OTN Data Team for assistance.")

        # Check permissions on tables
        permission_issues = []
        try:
            with self.engine.connect() as conn:
                # Check SELECT permission on each table
                for table in required_tables:
                    try:
                        result = conn.execute(
                            text(f"SELECT COUNT(*) FROM {self.schema}.{table} LIMIT 1"))
                        result.fetchone()
                    except Exception as e:
                        if "permission denied" in str(e).lower():
                            permission_issues.append(f"SELECT permission denied on {table}")

                    # Check INSERT permission (by attempting a dummy insert that will fail)
                    try:
                        # This will fail but checks if INSERT is allowed
                        conn.execute(
                            text(f"INSERT INTO {self.schema}.{table} DEFAULT VALUES RETURNING 1"))
                    except Exception as e:
                        if "permission denied" in str(e).lower():
                            permission_issues.append(f"INSERT permission denied on {table}")

        except Exception as e:
            if "permission denied" in str(e).lower():
                raise RuntimeError(f"Permission denied accessing schema '{self.schema}'"
                                   f"\nPlease contact OTN Data Team to grant appropriate permissions.")
            else:
                print(f"Warning: Could not verify permissions: {e}")
                raise e

        if permission_issues:
            print(f"Permission issues detected:")
            for issue in permission_issues:
                raise RuntimeError(f"Permission issue(s) found: \n{issue}"
                                   f"\nPlease contact OTN Data Team to grant appropriate permissions.")

        # All checks passed
        print(f"All checks passed.")
        return True

    def init_database_tables(self) -> bool:
        """
        Initialize database tables by running the SQL script.

        Returns:
            bool: True if initialization was successful, False otherwise
        """
        inspector = inspect(self.engine)
        if self.schema in inspector.get_schema_names():
            raise RuntimeError(f'{self.schema} is already exist.')

        # Find SQL file
        sql_file_path = os.path.join(os.getcwd(), SatQcResultsLoader.SAT_DB_INIT_FILE)
        if not os.path.exists(sql_file_path):
            sql_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), SatQcResultsLoader.SAT_DB_INIT_FILE)

        if not os.path.exists(sql_file_path):
            raise RuntimeError(f"SQL file not found: {sql_file_path}")

        # Read and modify SQL
        with open(sql_file_path, 'r') as f:
            sql_content = f.read()

        sql_content = sql_content.replace('{{sat_schema}}', f'{self.schema}')
        sql_content = sql_content.replace('{{user_name}}', f'{self.engine.url.username}')

        # Execute
        try:
            with self.engine.begin() as conn:
                conn.execute(text(sql_content))
            print(f"Schema '{self.schema}' initialized successfully!")
            return True
        except Exception as e:
            raise RuntimeError(f"Database initialization failed: {e}")

    def get_qced_programs(self) -> List[str]:
        """
        Get list of programs that have QC results.

        Returns:
            list[str]: list of programs
        """
        if (not os.path.exists(self.qc_output_path)) or (not os.path.isdir(self.qc_output_path)):
            print(f"Warning: Path {self.qc_output_path} does not exist or not a directory")
            return []

        qced_programs = []
        for sub_folder in os.listdir(self.qc_output_path):
            if (sub_folder not in self.EXCLUDE_FOLDERS and not sub_folder.startswith('.')):
                qced_programs.append(sub_folder)
        return qced_programs

    def get_qced_projects_for_programs(self, qced_programs: List[str]) -> Dict[str, List[str]]:
        """
        Get projects (second-level folders) in qc_output_path/program.

        Returns:
            dict[str: list[str]]: dict of program: [projects...]
                e.g.,
                {'imos': ['imos_ct180', 'imos_ct182'],
                 'irap': ['irap_damianlidgard_grey_seal']}
        """
        program_projects = {}
        for qced_program in qced_programs:
            program_folder = os.path.join(self.qc_output_path, qced_program)
            if not os.path.exists(program_folder):
                print_error(f'QCed program folder {program_folder} not found. Skipping...')
                continue
            projects = []
            for sub_folder in os.listdir(program_folder):
                if (sub_folder not in self.EXCLUDE_FOLDERS and not sub_folder.startswith('.')):
                    projects.append(sub_folder)

            program_projects.update({qced_program: sorted(projects)})
        return program_projects

    def get_qc_results_for_program(self, program: str) -> Dict[str, datetime]:
        """
        Get QCed projects for a given program.

        Args:
            program: program name

        Returns:
            dict[str, datetime]: A map of the QCed results file path to last_modified datetime
        """
        if program not in self.get_qced_programs():
            raise RuntimeError(f"Program not found in QC output folder: {self.qc_output_path}")

        projects = self.get_qced_projects_for_programs([program]).get(program, [])
        ssmoutput_last_modified_map = {}
        for project in projects:
            project_path = os.path.join(self.qc_output_path, program, project)
            ssmoutputs_files = list(Path(project_path).glob(SatQcResultsLoader.QCED_OUTPUT_FILE_PATTERN))
            if ssmoutputs_files:
                project_ssmoutputs = str(ssmoutputs_files[0])
                last_modified = datetime.fromtimestamp(os.path.getmtime(ssmoutputs_files[0]))
                if self.verbose:
                    print(f"Found SSM results: {ssmoutputs_files[0]} - last updated on {last_modified}")
                ssmoutput_last_modified_map[project_ssmoutputs] = last_modified
            else:
                if self.verbose:
                    print(f"-- No SSM result found for project: {project_path}. Skipping...")
                continue

        return ssmoutput_last_modified_map

    def load_qced_results_to_db(self, programs: List[str], projects: List[str]=None) -> tuple[pd.DataFrame, List[pd.DataFrame]]:
        """
        Load all QC results for specified programs (or all available) to the database.

        Args:
            programs: List of program names to load. If None, loads all available programs.
            projects: List of project names to load. If None, loads all available projects.

        Returns:
            tuple: (summary_df, all_meta_df_list)
        """
        if programs is None:
            programs = self.get_qced_programs()

        summary_df_list = []
        all_meta_df_list = []

        for program in programs:
            ssmoutput_map = self.get_qc_results_for_program(program)
            print(ssmoutput_map)
            if not ssmoutput_map:
                if self.verbose:
                    print(f"No SSM results found for program: {program}")
                continue

            for output_csv, last_modified in ssmoutput_map.items():
                program_name, project = get_program_project_from_ssm_file(output_csv)
                table_name = '_'.join([program_name, project])
                if self.verbose:
                    print(f'Uploading SSM results for program:{program_name} project:{project}...')

                # Check previously loaded table
                if self._is_already_loaded(table_name, last_modified):
                    continue

                summary_df = self.load_single_ssmoutput_to_db(output_csv, last_modified, table_name)
                if not summary_df.empty:
                    summary_df_list.append(summary_df)

                if self.verbose:
                    print(f'Uploaded SSM results to HOST: {self.engine.url.host} DB: {self.engine.url.database} {self.schema}.{table_name} table.')

                # Load metadata
                meta_df = self.parse_tag_metadata(program_name, project)
                if not meta_df.empty:
                    metadata_rows = self.load_meta_df_to_db(meta_df, table_name=self.SAT_META_TABLE)
                    if self.verbose:
                        print(f'Uploaded {metadata_rows} SSM tag metadata to {self.SAT_META_TABLE} table')
                    all_meta_df_list.append(meta_df)

        # Combine results
        summary_df = pd.concat(summary_df_list, ignore_index=True) if summary_df_list else pd.DataFrame()
        return summary_df, all_meta_df_list

    def _is_already_loaded(self, table_name: str, last_modified: datetime) -> bool:
        """
        Check if a table has already been loaded with the given last_modified timestamp.

        Args:
            table_name: Name of the table to check
            last_modified: Last modified datetime of the source file

        Returns:
            bool: True if already loaded, False otherwise
        """
        prev_load_df = self._get_loaded_table_info(table_name)
        if prev_load_df is None or len(prev_load_df) == 0:
            if self.verbose:
                print(f'This is the first time loading {table_name}. Will create {self.schema}.{table_name}...')
            return False

        prev_timestamp = pd.to_datetime(prev_load_df.iloc[0]['source_file_last_modified']).tz_localize(None)
        current_timestamp = pd.to_datetime(last_modified).tz_localize(None)

        if abs((current_timestamp - prev_timestamp).total_seconds()) < 2:
            if self.verbose:
                print(f"SSM results have been loaded for table {table_name} - last modified on {prev_timestamp.strftime('%Y_%m_%d_%H_%M_%S')}. Skipping...")
            return True

        return False

    def _get_loaded_table_info(self, table_name: str) -> pd.DataFrame:
        """
        Get information about previously loaded tables.

        Args:
            table_name: Name of the table to check

        Returns:
            DataFrame with table info or empty DataFrame
        """
        inspector = inspect(self.engine)
        if (not inspector.has_table(self.SAT_SSM_UPLOAD_LOG_TABLE, schema=self.schema) or
                not inspector.has_table(table_name, schema=self.schema)):
            return pd.DataFrame()

        log_sql = f"""
            SELECT ssmoutput_table, source_file_last_modified 
            FROM {self.schema}.{self.SAT_SSM_UPLOAD_LOG_TABLE}
            WHERE constraint_applied = true
            AND ssmoutput_table = '{table_name}'
            ORDER BY source_file_last_modified DESC
            LIMIT 1
        """
        with self.engine.begin() as conn:
            result = conn.execute(text(log_sql))
            rows = result.fetchall()

            if not rows:
                return pd.DataFrame()

        return pd.DataFrame(rows, columns=result.keys())

    def load_single_ssmoutput_to_db(self, ssmoutput_csv: str, last_modified: datetime, table_name: str) -> pd.DataFrame:
        """
        Load a single ssmoutput into the database.

        Args:
            ssmoutput_csv: Path to the SSM output CSV file
            last_modified: Last modified datetime of the file
            table_name: Name of the table to load into

        Returns:
            DataFrame with summary information
        """
        return self.load_csv_to_db(table_name, ssmoutput_csv, last_modified)

    def load_csv_to_db(self, table_name: str, csv_path: str, source_file_last_modified: datetime) -> pd.DataFrame:
        """
        Load a CSV file into the database.

        Args:
            table_name: Name of the target table
            csv_path: Path to the CSV file
            source_file_last_modified: Last modified datetime of the source file

        Returns:
            DataFrame with summary information
        """
        if self.engine is None:
            raise ValueError("Database engine not initialized. Call set_engine() first.")

        full_table_name = f'{self.schema}.{table_name}'
        now_str = datetime.utcnow().strftime('%Y_%m_%d_%H_%M_%S')
        backup_table_name = f'{table_name}_{now_str}'
        start_time = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        log_id = self._init_upload_log(start_time, table_name)

        inspector = inspect(self.engine)
        table_exists = inspector.has_table(table_name, schema=self.schema)

        try:
            # Backup table if exists
            if table_exists:
                with self.engine.begin() as conn:
                    conn.execute(
                        text(f'ALTER TABLE {full_table_name} RENAME TO {backup_table_name}'))

            with self.engine.begin() as conn:
                # Read header to define columns (all as TEXT for simplicity)
                df_header = pd.read_csv(csv_path, nrows=0)
                col_defs = [f'"{col}" TEXT' for col in df_header.columns]
                create_sql = f'CREATE UNLOGGED TABLE {full_table_name} (\n  ' + ',\n  '.join(
                    col_defs) + '\n)'
                conn.execute(text(create_sql))

            with self.engine.connect() as conn:
                with open(csv_path, 'r') as f:
                    next(f)  # skip header
                    raw_conn = conn.connection
                    with raw_conn.cursor() as cursor:
                        cursor.copy_expert(f"COPY {full_table_name} FROM STDIN WITH CSV", f)
                    raw_conn.commit()

                self._update_log_checkpoint(log_id, {
                    'source_file': csv_path,
                    'source_file_last_modified': source_file_last_modified.strftime(
                        '%Y-%m-%d %H:%M:%S'),
                    'raw_table_created': True
                })

            with self.engine.connect() as conn:
                result = conn.execute(text(f'SELECT COUNT(*) FROM {full_table_name}'))
                rows_loaded = result.scalar()

            if self.verbose:
                print(f"Successfully loaded {rows_loaded} rows into {full_table_name}")

            self._transform_nrt_table(table_name)
            self._update_log_checkpoint(log_id, {
                'ssmoutput_table': table_name,
                'loaded_rows': rows_loaded,
                'constraint_applied': True,
                'end_datetime': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
            })

            with self.engine.connect() as conn:
                conn.execute(text(f'DROP TABLE IF EXISTS {self.schema}.{backup_table_name}'))

        except Exception as e:
            self._update_log_checkpoint(log_id, {'error_message': str(e)})
            # If load failed: rename an original table, try to restore it
            if table_exists and inspector.has_table(backup_table_name, schema=self.schema):
                with self.engine.begin() as conn_restore:
                    conn_restore.execute(text(f'DROP TABLE IF EXISTS {full_table_name}'))
                    conn_restore.execute(text(
                        f'ALTER TABLE {self.schema}.{backup_table_name} RENAME TO {table_name}'))
                    if self.verbose:
                        print(f"Restored original table after load error: {table_name}")
            raise RuntimeError(f"CSV load failed: {e}") from e

        summary_df = self._update_nrt_catalog(table_name)
        return summary_df

    def _init_upload_log(self, start_datetime: str, table_name: str) -> str:
        """
        Initialize a new upload log entry and return the log_id.
        Note: The upload log table should already exist (created by SQL script).
        """
        if self.engine is None:
            raise ValueError("Database engine not initialized. Call set_engine() first.")

        log_id = f"{get_ip_by_hostname()}_{table_name}_{start_datetime.replace(':', '_').replace(' ', '_')}"

        with self.engine.begin() as conn:
            conn.execute(
                text(f"""
                    INSERT INTO {self.schema}.{self.SAT_SSM_UPLOAD_LOG_TABLE}
                    (id, start_datetime)
                    VALUES (:id, :start_datetime)
                    RETURNING id
                """), {'id': log_id, 'start_datetime': start_datetime}
            )

        return log_id

    def _update_log_checkpoint(self, log_id: int, updates: Dict[str, Any]) -> None:
        """
        Update specific fields in the log at checkpoints.

        Args:
            log_id: The log entry ID
            updates: Dictionary of field-value pairs to update
        """
        # Add the ID to the updates
        updates['id'] = log_id

        # Build dynamic UPDATE SQL
        update_columns = [col for col in updates.keys() if col != 'id']
        set_clause = ", ".join([f"{col} = :{col}" for col in update_columns])

        sql = f"""
            UPDATE {self.schema}.{self.SAT_SSM_UPLOAD_LOG_TABLE}
            SET {set_clause}
            WHERE id = :id
        """

        with self.engine.begin() as conn:
            conn.execute(text(sql), updates)
            if self.verbose:
                print(f"Checkpoint updated for log {log_id}: {list(updates.keys())}")

    def _transform_nrt_table(self, table_name: str) -> None:
        """
        Transform columns of a table from TEXT to desired data types.

        Args:
            table_name: Name of the table to transform
        """
        full_table_name = f'{self.schema}.{table_name}'
        number_columns = ['lon', 'lat', 'x', 'y', 'x_se', 'y_se', 'u', 'v', 'u_se', 'v_se', 's', 's_se']
        datetime_columns = ['date']
        text_columns = ['ptt', 'cid', 'common_name']

        inspector = inspect(self.engine)
        columns = [col['name'] for col in inspector.get_columns(table_name, schema=self.schema)]

        with self.engine.begin() as conn:
            # Convert to LOGGED
            conn.execute(text(f'ALTER TABLE {full_table_name} SET LOGGED'))

            # Convert each column
            for col in number_columns:
                alter_sql = f'''
                    ALTER TABLE {full_table_name} 
                    ALTER COLUMN "{col}" TYPE NUMERIC 
                    USING NULLIF("{col}", 'NA')::NUMERIC
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

            for column in text_columns:
                if column not in columns:
                    conn.execute(text(f'ALTER TABLE {full_table_name} ADD COLUMN "{column}" TEXT'))

        # Add index and inheritance
        with self.engine.begin() as conn:
            conn.execute(text(
                f'CREATE INDEX IF NOT EXISTS idx_{table_name}_tag_id_date ON {full_table_name} ("tag_id", "date")'))
            conn.execute(text(
                f'ALTER TABLE {full_table_name} INHERIT {self.schema}.{self.SAT_SSM_MASTER_TABLE}'))

    def _update_nrt_catalog(self, ssm_result_table: str) -> pd.DataFrame:
        """
        Update the NRT catalog with dynamic CID detection.

        Args:
            ssm_result_table: Name of the SSM result table

        Returns:
            DataFrame with updated catalog information
        """
        summary_df = pd.DataFrame()
        inspector = inspect(self.engine)

        # Check if CID column exists
        source_columns = [col['name'] for col in inspector.get_columns(ssm_result_table, schema=self.schema)]
        has_cid = 'cid' in source_columns

        # Build dynamic SQL using self.schema
        if has_cid:
            query = f"""
                WITH 
                tag_aggregates AS (
                    SELECT 
                        tag_id,
                        MIN(date) as min_date,
                        MAX(date) as max_date,
                        COUNT(*) as row_count
                    FROM {self.schema}.{ssm_result_table}
                    WHERE tag_id IS NOT NULL AND tag_id != ''
                    GROUP BY tag_id
                ),
                tag_latest_info AS (
                    SELECT DISTINCT ON (tag_id)
                        tag_id,
                        lon as latest_lon,
                        lat as latest_lat,
                        cid as latest_cid
                    FROM {self.schema}.{ssm_result_table}
                    WHERE tag_id IS NOT NULL AND tag_id != ''
                    ORDER BY tag_id, date DESC
                )
                INSERT INTO {self.schema}.{self.SAT_SSM_SUMMARY_TABLE}
                (sat_ssm_table_name, tag_id, min_date, max_date, row_count, cid, latest_lon, latest_lat)
                SELECT 
                    '{ssm_result_table}' as sat_ssm_table_name,
                    a.tag_id,
                    a.min_date,
                    a.max_date,
                    a.row_count,
                    l.latest_cid,
                    l.latest_lon,
                    l.latest_lat
                FROM tag_aggregates a
                LEFT JOIN tag_latest_info l ON a.tag_id = l.tag_id
                ON CONFLICT (sat_ssm_table_name, tag_id) DO UPDATE SET
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
                    FROM {self.schema}.{ssm_result_table}
                    WHERE tag_id IS NOT NULL AND tag_id != ''
                    GROUP BY tag_id
                ),
                tag_latest_info AS (
                    SELECT DISTINCT ON (tag_id)
                        tag_id,
                        lon as latest_lon,
                        lat as latest_lat
                    FROM {self.schema}.{ssm_result_table}
                    WHERE tag_id IS NOT NULL AND tag_id != ''
                    ORDER BY tag_id, date DESC
                )
                INSERT INTO {self.schema}.{self.SAT_SSM_SUMMARY_TABLE}
                (sat_ssm_table_name, tag_id, min_date, max_date, row_count, latest_lon, latest_lat)
                SELECT 
                    '{ssm_result_table}' as sat_ssm_table_name,
                    a.tag_id,
                    a.min_date,
                    a.max_date,
                    a.row_count,
                    l.latest_lon,
                    l.latest_lat
                FROM tag_aggregates a
                LEFT JOIN tag_latest_info l ON a.tag_id = l.tag_id
                ON CONFLICT (sat_ssm_table_name, tag_id) DO UPDATE SET
                    min_date = EXCLUDED.min_date,
                    max_date = EXCLUDED.max_date,
                    row_count = EXCLUDED.row_count,
                    latest_lon = EXCLUDED.latest_lon,
                    latest_lat = EXCLUDED.latest_lat,
                    last_updated = CURRENT_TIMESTAMP
                RETURNING *
            """

        with self.engine.begin() as conn:
            result = conn.execute(text(query))
            rows = result.fetchall()

            if not rows:
                if self.verbose:
                    print(f"No tags found in {ssm_result_table}")
                return summary_df

            summary_df = pd.DataFrame(rows, columns=result.keys())
            if self.verbose:
                print(f"Updated catalog with {len(summary_df)} tag records for {ssm_result_table}")

        return summary_df

    def load_meta_df_to_db(self, meta_df: pd.DataFrame, table_name: str = None) -> int:
        """
        Load metadata DataFrame to the database.

        Args:
            meta_df: metadata dataframe
            table_name: Name of the target table. Defaults to SAT_META_TABLE

        Returns:
            int: Number of rows affected
        """
        table_name = table_name or self.SAT_META_TABLE
        full_table_name = f"{self.schema}.{table_name}"
        temp_table = f"temp_{table_name}"

        with self.engine.begin() as conn:
            # Create temporary table
            conn.execute(text(f"""
                CREATE TEMP TABLE {temp_table} (
                    LIKE {full_table_name} INCLUDING DEFAULTS
                ) ON COMMIT DROP
            """))

            # Insert data into temporary table
            for _, row in meta_df.iterrows():
                # Handle NaN values
                row_dict = row.to_dict()
                for key, value in row_dict.items():
                    if pd.isna(value):
                        row_dict[key] = None

                # Build insert statement
                columns = ', '.join([f'"{col}"' for col in meta_df.columns])
                placeholders = ', '.join([f':{col}' for col in meta_df.columns])

                insert_sql = text(f"""
                    INSERT INTO {temp_table} ({columns})
                    VALUES ({placeholders})
                """)

                conn.execute(insert_sql, row_dict)

            # UPSERT from temp table
            columns = [f'"{col}"' for col in meta_df.columns]
            columns_str = ', '.join(columns)

            # Exclude conflict columns from update set
            conflict_columns = ['program', 'tag_id', 'ptt']
            update_columns = [col for col in meta_df.columns if col not in conflict_columns]
            update_set = ', '.join([f'{col} = EXCLUDED.{col}' for col in update_columns])

            upsert_sql = text(f"""
                INSERT INTO {full_table_name} ({columns_str})
                SELECT {columns_str}
                FROM {temp_table}
                ON CONFLICT (campaign_id, tag_id, ptt) 
                DO UPDATE SET
                    {update_set}
            """)

            result = conn.execute(upsert_sql)
            return result.rowcount

    def parse_tag_metadata(self, program: str, cid: str) -> pd.DataFrame:
        """
        Parse tag metadata from QC summary files.

        Args:
            program: Program name (e.g., 'imos')
            cid: Collection/device ID (e.g., 'ct180')

        Returns:
            DataFrame with standardized column names
        """
        program_cid_path = os.path.join(self.qc_output_path, program, f'{program}_{cid}')

        if self.verbose:
            print(f"Looking in: {program_cid_path}")

        # Get tag metadata file
        meta_files = get_files_by_pattern(program_cid_path, self.TAG_META_FILE_PATTERN)

        if not meta_files:
            print_error(
                f'No tag metadata file found in {program_cid_path} by pattern {self.TAG_META_FILE_PATTERN}')
            return pd.DataFrame()

        # Load the original data
        meta_df = pd.read_csv(meta_files[0])

        if self.verbose:
            print(f"\nLoaded {len(meta_df)} rows from {meta_files[0].name}")
            print(f"Original columns: {meta_df.columns.tolist()}")

        # Define column mapping
        column_mapping = {
            'campaign_id': ['sattag_program'],
            'tag_id': ['device_id', 'deployment_id'],
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
            'qc_run_date': ['qc_run_date'],
            'instrument_serial_number': ['tag_serial_number', 'body'],
        }

        # Curated metadata: add missing columns and set values as None
        curated_meta_df = pd.DataFrame(
            {col: [None] * len(meta_df) for col in column_mapping.keys()})

        # Map and fill existing columns from meta_df
        selected_columns = {}
        for target_col, possible_cols in column_mapping.items():
            for col in possible_cols:
                if col in meta_df.columns:
                    curated_meta_df[target_col] = meta_df[col]
                    selected_columns[target_col] = col
                    if self.verbose:
                        print(f"   Mapped: '{col}' ➔ '{target_col}'")
                    break
            else:
                if self.verbose:
                    print(f"      Column not found for '{target_col}', set to null")

        # Check essential columns
        essential_columns = ['tag_id', 'ptt']
        missing_essential = [col for col in essential_columns if col not in selected_columns]

        if missing_essential:
            print_error(f"Essential columns missing: {missing_essential}")
            return pd.DataFrame()

        # Get min/max depth dataframe
        min_max_depth_df = self._parse_min_max_depth(program, cid)
        if self.verbose:
            show_df(min_max_depth_df, 'min_max_depth_df', True)

        # Left join min_max_depth_df with min_max_depth_df
        curated_meta_df = curated_meta_df.merge(
            min_max_depth_df,
            on=['tag_id', 'ptt'],
            how='left',
            suffixes=('', '_depth')
        )

        return curated_meta_df

    def _parse_min_max_depth(self, program: str, cid: str) -> pd.DataFrame:
        """
        Get min_depth (always be 0) and max_depth from QCed results

        Args:
            program: Program name (e.g., 'imos')
            cid: Collection/device ID (e.g., 'ct180')

        Returns:
            pandas.DataFrame: DataFrame containing min_depth and max_depth values.
                Returns empty DataFrame if no matching file is found.
        """
        program_cid_path = os.path.join(self.qc_output_path, program, f'{program}_{cid}')
        depth_files = get_files_by_pattern(program_cid_path, self.MIN_MAX_DEPTH_FILE_PATTERN)

        if not depth_files:
            print_error(f'No min max depth file found in {program_cid_path} by pattern {self.MIN_MAX_DEPTH_FILE_PATTERN}')
            return pd.DataFrame()

        depth_df = pd.read_csv(depth_files[0])

        # Define column mapping
        column_mapping = {
            'tag_id': ['ref', 'DeploymentID', 'deployment_id'],
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
                print_error(f"None of the expected columns for '{target_col}' found in {depth_df.columns.tolist()}")
                return pd.DataFrame()
            selected_columns[target_col] = found_col
            if self.verbose:
                print(f"   Mapped: '{found_col}' to '{target_col}'")

        # Select and rename columns
        try:
            depth_df = depth_df[[selected_columns['tag_id'], selected_columns['ptt'], selected_columns['max_depth']]].copy()
            depth_df.columns = ['tag_id', 'ptt', 'max_depth']
        except KeyError as e:
            print_error(f"Column selection error: {e}")
            return pd.DataFrame()

        # Group by tag_id and ptt to get the max of max_depth
        group_depth_df = (depth_df.groupby(['tag_id', 'ptt'], as_index=False).agg({'max_depth': 'max'}))
        # Add min_depth column with default value 0
        group_depth_df['min_depth'] = 0
        # Reorder columns
        group_depth_df = group_depth_df[['tag_id', 'ptt', 'min_depth', 'max_depth']]
        return group_depth_df

    def show_db_deployments(self, program: List[str] = [], project: List[str] = []) -> pd.DataFrame:
        """
        Query NRT DB to get deployments

        Args:
            program: List of program names to filter
            project: List of project names to filter

        Returns:
            DataFrame with deployment information
        """
        inspector = inspect(self.engine)
        if not inspector.has_table(self.SAT_META_TABLE, schema=self.schema):
            print(f'Table does not exist {self.schema}.{self.SAT_META_TABLE}.')
            return pd.DataFrame()

        # Build the query with optional filters
        base_query = f"SELECT * FROM {self.schema}.{self.SAT_META_TABLE}"

        where_clauses = []
        params = {}

        if program:
            placeholders = ','.join([f':p{i}' for i in range(len(program))])
            where_clauses.append(f"program IN ({placeholders})")
            for i, p in enumerate(program):
                params[f'p{i}'] = p

        if project:
            placeholders = ','.join([f':c{i}' for i in range(len(project))])
            where_clauses.append(f"project IN ({placeholders})")
            for i, c in enumerate(project):
                params[f'c{i}'] = c

        if where_clauses:
            full_query = base_query + " WHERE " + " AND ".join(where_clauses)
        else:
            full_query = base_query

        with self.engine.begin() as conn:
            result = conn.execute(text(full_query), params)
            rows = result.fetchall()
            if not rows:
                print(f"No tags found in {self.schema}.{self.SAT_META_TABLE}")
                return pd.DataFrame()

        db_nrt_metadata_df = pd.DataFrame(rows, columns=result.keys())
        show_df(db_nrt_metadata_df, 'db_nrt_metadata_df', True)
        return db_nrt_metadata_df

    def show_db_nrt_status(self, programs: List[str] = [], projects: List[str] = []) -> None:
        """
        Display NRT status with colored lights

        Args:
            programs: List of program names to filter
            projects: List of project names to filter
        """
        status_df = self.get_project_status(programs, projects)
        self._show_status_lights(status_df)

    def get_project_status(self, programs: List[str] = [], projects: List[str] = []) -> pd.DataFrame:
        """
        Get the latest last_updated timestamp for each project/collectioncode

        Args:
            programs: List of program names to filter
            projects: List of project names to filter

        Returns:
            DataFrame with project status information
        """
        if not self.engine.has_table(self.SAT_SSM_SUMMARY_TABLE, schema=self.schema):
            print(f'Table does not exist {self.schema}.{self.SAT_SSM_SUMMARY_TABLE}.')
            return pd.DataFrame()

        # Build WHERE clause for filters
        where_clauses = []
        params = {}

        if programs:
            placeholders = ','.join([f':p{i}' for i in range(len(programs))])
            where_clauses.append(f"program IN ({placeholders})")
            for i, p in enumerate(programs):
                params[f'p{i}'] = p

        if projects:
            placeholders = ','.join([f':c{i}' for i in range(len(projects))])
            where_clauses.append(f"cid IN ({placeholders})")
            for i, c in enumerate(projects):
                params[f'c{i}'] = c

        where_clause = " WHERE " + " AND ".join(where_clauses) if where_clauses else ""

        full_query = f"""
            WITH latest_updates AS (
                SELECT
                    program, 
                    cid as campaign_id,
                    collectioncode,
                    MAX(last_updated) as latest_update,
                    COUNT(DISTINCT tag_id) as tag_count,
                    COUNT(*) as total_records,
                    MIN(min_date) as earliest_date,
                    MAX(max_date) as latest_date
                FROM {self.schema}.{self.SAT_SSM_SUMMARY_TABLE}
                {where_clause}
                GROUP BY program, cid, collectioncode
            )
            SELECT 
                program, 
                campaign_id,
                collectioncode,
                latest_update,
                tag_count,
                total_records,
                earliest_date,
                latest_date
            FROM latest_updates
        """

        with self.engine.connect() as conn:
            result = conn.execute(text(full_query), params)
            data = result.fetchall()
            df = pd.DataFrame(data, columns=result.keys())

        if df.empty:
            print("No status data found")
            return df

        now = pd.Timestamp.now()
        df['latest_update'] = pd.to_datetime(df['latest_update']).dt.tz_localize(None)
        df['hours_since_update'] = (now - df['latest_update']).dt.total_seconds() / 3600

        def get_status(hours):
            if hours <= 24:
                return '🟢'
            elif hours <= 48:
                return '🟡'
            else:
                return '🔴'

        df['status'] = df['hours_since_update'].apply(get_status)

        status_order = {'🟢': 0, '🟡': 1, '🔴': 2}
        df['status_order'] = df['status'].map(status_order)
        df = df.sort_values(['status_order', 'campaign_id']).drop('status_order', axis=1)

        return df

    def _show_status_lights(self, status_df: pd.DataFrame) -> None:
        """
        Display project status with colored lights

        Args:
            status_df: DataFrame with status information
        """
        if status_df.empty:
            print("No status data to display")
            return

        html = """
        <div style="display: flex; flex-wrap: wrap; gap: 15px; padding: 10px; font-family: Arial, sans-serif;">
        """

        for _, row in status_df.iterrows():
            status = row['status']
            campaign = row['campaign_id']
            hours = round(row['hours_since_update'], 1)
            tag_count = row['tag_count']
            latest_update = row['latest_update'].strftime('%Y-%m-%d %H:%M')

            if status == '🟢':
                bg_color = '#4CAF50'
                text_color = 'white'
                status_text = '✅ Active'
            elif status == '🟡':
                bg_color = '#FFC107'
                text_color = 'black'
                status_text = '⚠️ Warning'
            else:
                bg_color = '#f44336'
                text_color = 'white'
                status_text = '❌ Stale'

            html += f"""
            <div style="
                flex: 1 1 200px;
                min-width: 180px;
                padding: 15px;
                background-color: {bg_color};
                color: {text_color};
                border-radius: 10px;
                box-shadow: 0 2px 5px rgba(0,0,0,0.2);
                text-align: center;
            ">
                <div style="font-size: 48px; margin-bottom: 5px;">{status}</div>
                <div style="font-size: 18px; font-weight: bold;">{campaign}</div>
                <div style="font-size: 14px; margin-top: 5px;">{status_text}</div>
                <div style="font-size: 12px; margin-top: 5px; opacity: 0.9;">
                    Last update: {latest_update}
                </div>
                <div style="font-size: 12px; opacity: 0.9;">
                    {hours} hours ago • {tag_count} tags
                </div>
            </div>
            """

        html += "</div>"
        display(HTML(html))
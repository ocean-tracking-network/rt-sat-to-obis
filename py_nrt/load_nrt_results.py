from pathlib import Path
from typing import List, Union

import pandas as pd

from py_nrt.common import print_error

OTN_NRT_SCHEMA = 'otn_realtime'
from sqlalchemy.engine import Engine


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


class OTNRealtimeLoader:
    def __init__(self, db_url, csv_path, table_name="otn_realtime.near_realtime_qc"):
        self.db_url = db_url
        self.csv_path = csv_path
        self.table_name = table_name
        self.engine = create_engine(db_url, pool_pre_ping=True)

    def get_latest_datetime(self):
        """Get the most recent datetime_utc from the table"""
        query = f"""
        SELECT MAX(datetime_utc) as latest_date 
        FROM {self.table_name}
        """
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text(query)).fetchone()
                latest_date = result[0] if result[0] else None
                logger.info(f"Latest datetime_utc in table: {latest_date}")
                return latest_date
        except Exception as e:
            logger.warning(f"Could not fetch latest datetime: {e}")
            return None

    def filter_recent_data(self, df, latest_date=None, weeks_back=2):
        """
        Filter DataFrame to include only data from the last 2 weeks
        before the latest date in the table
        """
        if latest_date:
            # Calculate cutoff date (2 weeks before latest date)
            cutoff_date = latest_date - timedelta(weeks=weeks_back)
            logger.info(f"Filtering data after: {cutoff_date}")

            # Filter DataFrame
            df_filtered = df[df['datetime_utc'] > cutoff_date].copy()
            logger.info(f"Filtered from {len(df)} to {len(df_filtered)} rows")
            return df_filtered
        else:
            # If table is empty, return all data
            logger.info("Table is empty, loading all data")
            return df

    def read_and_filter_csv(self):
        """Read CSV and filter based on existing data"""
        # Read CSV with optimized dtypes
        logger.info(f"Reading CSV: {self.csv_path}")

        # Define column dtypes for memory efficiency
        dtype_spec = {
            'deploymentid': 'str',
            'longitude': 'float32',
            'latitude': 'float32',
            'x': 'float32',
            'y': 'float32',
            'x_se': 'float32',
            'y_se': 'float32',
            'u': 'float32',
            'v': 'float32',
            'u_se': 'float32',
            'v_se': 'float32',
            's': 'float32',
            's_se': 'float32'
        }

        # Read CSV with chunks for large files
        try:
            # First, get the latest date from table
            latest_date = self.get_latest_datetime()

            # Read entire CSV or filter during read for large files
            df = pd.read_csv(
                self.csv_path,
                dtype=dtype_spec,
                parse_dates=['datetime_utc'],
                infer_datetime_format=True
            )

            # Filter to only recent data
            df_filtered = self.filter_recent_data(df, latest_date)

            return df_filtered

        except Exception as e:
            logger.error(f"Error reading CSV: {e}")
            raise

    def prepare_dataframe(self, df):
        """Prepare DataFrame for upsert"""
        # Ensure datetime_utc is timezone aware UTC
        if df['datetime_utc'].dt.tz is None:
            df['datetime_utc'] = df['datetime_utc'].dt.tz_localize('UTC')
        else:
            df['datetime_utc'] = df['datetime_utc'].dt.tz_convert('UTC')

        # Replace NaNs with None for proper NULL handling
        df = df.where(pd.notnull(df), None)

        # Ensure columns are in correct order
        expected_cols = [
            'deploymentid', 'datetime_utc', 'longitude', 'latitude',
            'x', 'y', 'x_se', 'y_se', 'u', 'v', 'u_se', 'v_se',
            's', 's_se'
        ]

        return df[expected_cols]

    def upsert_with_copy_then_merge(self, df):
        """
        Most efficient upsert: COPY to temp table then MERGE
        """
        if df.empty:
            logger.info("No new data to upsert")
            return 0

        temp_table = f"temp_{self.table_name.replace('.', '_')}"

        with self.engine.begin() as conn:
            # Step 1: Create temporary table
            logger.info(f"Creating temporary table: {temp_table}")
            conn.execute(text(f"""
                CREATE TEMP TABLE {temp_table} 
                (LIKE {self.table_name} INCLUDING DEFAULTS)
                ON COMMIT DROP;
            """))

            # Step 2: Bulk COPY to temp table
            logger.info(f"Copying {len(df)} rows to temp table")
            self._bulk_copy_to_temp(df, temp_table, conn)

            # Step 3: Perform upsert
            logger.info("Performing upsert")
            result = conn.execute(text(f"""
                INSERT INTO {self.table_name}
                SELECT * FROM {temp_table}
                ON CONFLICT (deploymentid, datetime_utc) 
                DO UPDATE SET
                    longitude = EXCLUDED.longitude,
                    latitude = EXCLUDED.latitude,
                    x = EXCLUDED.x,
                    y = EXCLUDED.y,
                    x_se = EXCLUDED.x_se,
                    y_se = EXCLUDED.y_se,
                    u = EXCLUDED.u,
                    v = EXCLUDED.v,
                    u_se = EXCLUDED.u_se,
                    v_se = EXCLUDED.v_se,
                    s = EXCLUDED.s,
                    s_se = EXCLUDED.s_se,
                    created_at = CASE 
                        WHEN {self.table_name}.created_at IS NULL 
                        THEN EXCLUDED.created_at 
                        ELSE {self.table_name}.created_at 
                    END
                WHERE 
                    {self.table_name}.longitude IS DISTINCT FROM EXCLUDED.longitude OR
                    {self.table_name}.latitude IS DISTINCT FROM EXCLUDED.latitude OR
                    {self.table_name}.x IS DISTINCT FROM EXCLUDED.x OR
                    {self.table_name}.y IS DISTINCT FROM EXCLUDED.y OR
                    {self.table_name}.x_se IS DISTINCT FROM EXCLUDED.x_se OR
                    {self.table_name}.y_se IS DISTINCT FROM EXCLUDED.y_se OR
                    {self.table_name}.u IS DISTINCT FROM EXCLUDED.u OR
                    {self.table_name}.v IS DISTINCT FROM EXCLUDED.v OR
                    {self.table_name}.u_se IS DISTINCT FROM EXCLUDED.u_se OR
                    {self.table_name}.v_se IS DISTINCT FROM EXCLUDED.v_se OR
                    {self.table_name}.s IS DISTINCT FROM EXCLUDED.s OR
                    {self.table_name}.s_se IS DISTINCT FROM EXCLUDED.s_se;
            """))

            logger.info(f"Upserted/Updated {result.rowcount} rows")
            return result.rowcount

    def _bulk_copy_to_temp(self, df, temp_table, conn):
        """Use COPY for maximum speed"""
        # Get raw psycopg2 connection
        raw_conn = conn.connection

        # Convert DataFrame to CSV string
        output = StringIO()
        df.to_csv(output, header=False, index=False, na_rep='\\N')
        output.seek(0)

        # Execute COPY
        cursor = raw_conn.cursor()
        cursor.copy_expert(
            f"COPY {temp_table} FROM STDIN WITH CSV NULL '\\N'",
            output
        )
        cursor.close()

    def optimized_upsert(self, df):
        """
        Alternative: Direct ON CONFLICT DO UPDATE with execute_values
        Good for smaller datasets
        """
        from psycopg2.extras import execute_values
        import psycopg2

        if df.empty:
            return 0

        # Prepare data
        data_tuples = [tuple(x) for x in df.to_numpy()]
        columns = ', '.join(df.columns)

        # Build upsert query
        update_set = ', '.join([
            f"{col} = EXCLUDED.{col}"
            for col in df.columns
            if col not in ['deploymentid', 'datetime_utc', 'created_at']
        ])

        query = f"""
            INSERT INTO {self.table_name} ({columns})
            VALUES %s
            ON CONFLICT (deploymentid, datetime_utc)
            DO UPDATE SET {update_set}
        """

        # Execute with psycopg2 for better performance
        with psycopg2.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                execute_values(cur, query, data_tuples, page_size=10000)
                conn.commit()
                return cur.rowcount

    def run(self, use_fast_method=True):
        """Main execution method"""
        logger.info("Starting OTN Realtime Loader")

        try:
            # Step 1: Read and filter CSV
            df = self.read_and_filter_csv()

            if df.empty:
                logger.info("No data to process after filtering")
                return 0

            # Step 2: Prepare DataFrame
            df_prepared = self.prepare_dataframe(df)
            logger.info(f"Processing {len(df_prepared)} rows")

            # Step 3: Upsert data
            if use_fast_method and len(df_prepared) > 1000:
                # Use COPY + MERGE for large datasets
                upserted = self.upsert_with_copy_then_merge(df_prepared)
            else:
                # Use optimized execute_values for smaller datasets
                upserted = self.optimized_upsert(df_prepared)

            logger.info(f"Successfully processed {upserted} rows")
            return upserted

        except Exception as e:
            logger.error(f"Error in run: {e}")
            raise


# Configuration and Usage
CONFIG = {
    'db_url': 'postgresql://user:password@host:port/database',
    'csv_path': '/path/to/your/data.csv'
}


def main():
    # Initialize loader
    loader = OTNRealtimeLoader(
        db_url=CONFIG['db_url'],
        csv_path=CONFIG['csv_path']
    )

    # Run the loader
    loader.run(use_fast_method=True)


if __name__ == "__main__":
    main()
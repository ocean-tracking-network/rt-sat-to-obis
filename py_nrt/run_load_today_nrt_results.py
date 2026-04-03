#!/usr/bin/env python3
"""
Run load SSM results to NRT backend DB with multiple config files in parallel threads.
"""

import argparse
import fnmatch
import logging
import os

import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List
from pathlib import Path
import json
import pandas as pd
from .load_nrt_results import *

DEFAULT_LOG_DIR = "/var/log/argosqc"
DEFAULT_MAX_THREADS = 4

# Setup log format
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(threadName)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)



def get_today_argosqc_run_details(argosqc_run_details_csv: str = '../argosqc_run_details.csv')-> pd.DataFrame:
    """Read argosqc_run_details.csv to parse today's results"""
    all_detail_df = pd.read_csv(argosqc_run_details_csv)
    all_detail_df['qc_start_datetime'] = pd.to_datetime(all_detail_df['qc_start_datetime'], errors='coerce')

    # Filter for rows >= today 0 AM
    today_detail_df = all_detail_df.copy()
    # today_detail_df = all_detail_df[all_detail_df['qc_start_datetime'] >= pd.Timestamp.now().normalize()].copy()
    # Remove qc_start_datetime and duplicates
    today_detail_df.drop(columns=['qc_start_datetime'], inplace=True)
    today_detail_df.drop_duplicates(subset=['program', 'output_dir', 'common_name'], inplace=True)
    print(f"ArgosQC results from {datetime.now().date()} 00:00:00 onwards: {len(today_detail_df)}")
    if today_detail_df.empty:
        latest_runs = all_detail_df.nlargest(5, 'qc_start_datetime')[['qc_start_datetime', 'program', 'common_name']]
        print(f'No ArgosQC results found for today.\n\nThe latest runs (top 5 by qc_start_datetime DESC):\n{latest_runs.to_string(index=False)}')
    return today_detail_df


def load_today_ssmoutput(auth_file: str = 'database_conn_string.auth', argosqc_run_details: str='argosqc_run_details.csv'):
    engine = get_engine(auth_file)
    check_otn_nrt_backend(engine)
    today_argosqc_df = get_today_argosqc_run_details(argosqc_run_details)

    if today_argosqc_df.empty:
        print("WARNING: No ArgosQC runs found for today")
        return

    for index, argosqc_row in today_argosqc_df.iterrows():
        ssmoutput_folder = os.path.normpath(argosqc_row['output_dir'])
        ssmoutput_csvs = list(Path(ssmoutput_folder).rglob('*ssmoutputs*.csv'))
        project_id = argosqc_row['proj_id']

        if not ssmoutput_csvs:
            print(f"WARNING: *ssmoutputs*_nrt.csv not found in {ssmoutput_folder}")
            continue
        try:
            last_modified = datetime.fromtimestamp(os.path.getmtime(ssmoutput_csvs[0]))
            print(f"Found: {ssmoutput_csvs[0]} (modified: {last_modified})")
            load_single_ssmoutput_to_nrt_db(engine, project_id, str(ssmoutput_csvs[0]), last_modified)
        except Exception as e:
            print(f'Exception occurred loading {str(ssmoutput_csvs[0])}')


def main():
    """
    Main function to load today's ssmoutput files in parallel.
    """
    logger.info("=" * 60)
    logger.info("STARTING SSMOUTPUT LOADER")
    logger.info("=" * 60)
    logger.info(f"Using {DEFAULT_MAX_THREADS} parallel threads")

    # Load today's ssmoutput files in parallel
    load_today_ssmoutput()


if __name__ == "__main__":
    main()
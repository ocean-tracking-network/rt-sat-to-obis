#!/usr/bin/env python3
"""
Run R script with multiple config files in parallel threads.
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
from py_nrt.load_nrt_results import *
DEFAULT_LOG_DIR = "/var/log/argosqc"
DEFAULT_MAX_THREADS = 4

# Setup log format
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(threadName)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def load_today_ssmoutput(
        auth_file: str = r"G:\Niu_2020\2020_OTN\db_auth\000_local_timescale_conn_string.auth"):
    engine = get_engine(auth_file)
    today_argosqc_df = get_today_argosqc_run_details('argosqc_run_details.csv')

    if today_argosqc_df.empty:
        print("WARNING: No ArgosQC runs found for today")
        return

    ssmoutput_last_modified_map = {}

    for index, argosqc_row in today_argosqc_df.iterrows():
        ssmoutput_folder = argosqc_row['output_dir']
        ssmoutput_csvs = list(Path(ssmoutput_folder).rglob('*ssmoutputs*_nrt.csv'))

        if not ssmoutput_csvs:
            print(f"WARNING: ssmoutputs*_nrt.csv not found in {ssmoutput_folder}")
            continue

        last_modified = datetime.fromtimestamp(os.path.getmtime(ssmoutput_csvs[0]))
        ssmoutput_last_modified_map[str(ssmoutput_csvs[0])] = last_modified
        print(f"Found: {ssmoutput_csvs[0]} (modified: {last_modified})")

    if ssmoutput_last_modified_map:
        load_to_nrt_db(engine, ssmoutput_last_modified_map)
    else:
        print("WARNING: No ssmoutput files found to load")


def main():

    load_to_nrt_db(engine, ssmoutput_last_modified_map)



    # Find all config files
    logger.info(f"Searching for '{args.pattern}' in '{args.search_root}'")
    config_files = find_config_files(args.search_root, args.pattern)

    if not config_files:
        logger.error("No config files found matching the pattern.")
        sys.exit(1)

    logger.info(f"Found {len(config_files)} config files: \n {config_files}")

    # Use ThreadPoolExecutor
    results = []
    with ThreadPoolExecutor(max_workers=args.threads) as executor:
        # Submit tasks
        future_to_config = {}
        for config in config_files:
            future = executor.submit(
                run_r_script,

                config,
                args.log_dir,
                not args.no_sudo
            )
            future_to_config[future] = config

        # Process completed tasks as they finish
        for future in as_completed(future_to_config):
            config = future_to_config[future]
            try:
                result = future.result()
                results.append(result)
            except Exception as exc:
                logger.error(f"Task for {config} generated an exception: {exc}")
                results.append({
                    'config': config,
                    'log': None,
                    'returncode': -1,
                    'timestamp': datetime.now().strftime("%Y%m%d_%H%M%S"),
                    'vendor': 'Unknown',
                    'error': str(exc)
                })

    # Print summary
    logger.info("=" * 60)
    logger.info("SUMMARY")
    logger.info("=" * 60)

    successful = [r for r in results if r.get('returncode') == 0]
    failed = [r for r in results if r.get('returncode') != 0]

    logger.info(f"Total: {len(results)}")
    logger.info(f"Successful: {len(successful)}")
    logger.info(f"Failed: {len(failed)}")

    if failed:
        logger.info("\nFailed configurations:")
        for f in failed:
            logger.info(f"  - {f['config']} (vendor: {f.get('vendor', 'N/A')}, exit code: {f.get('returncode', 'N/A')})")
            if f.get('log'):
                logger.info(f"    Log: {f['log']}")
            if f.get('error'):
                logger.info(f"    Error: {f['error']}")

    logger.info(f"\nLogs saved to: {args.log_dir}")

if __name__ == "__main__":
    main()
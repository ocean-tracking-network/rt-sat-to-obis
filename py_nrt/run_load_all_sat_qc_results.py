"""
Run load SSM results to NRT backend DB with multiple config files.
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
sys.path.insert(0, os.getcwd())
from load_nrt_results import load_single_ssmoutput_to_nrt_db
from common import get_engine
from sat_qc_result_loader import SatQcResultsLoader
DEFAULT_LOG_DIR = "./logs"
# Setup log format
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(threadName)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def load_all_ssmoutput(auth_file: str = './py_nrt/database_conn_string.auth'):
    engine = get_engine(auth_file)
    error_occurred = False
    sat_loader = SatQcResultsLoader(engine, SatQcResultsLoader.SATNRT_SCHEMA)
    programs = sat_loader.get_qced_programs()
    all_ssmoutput_last_modified_map = {}
    for program in programs:
        ssmoutput_last_modified_map = sat_loader.get_qc_results_for_program_and_project(program)
        all_ssmoutput_last_modified_map.update(ssmoutput_last_modified_map)
    summary_df, _ = sat_loader.load_qced_results_to_db(programs)

    if error_occurred:
        sys.exit(1)


def main():
    """
    Main function to load today's ssmoutput files in parallel.
    """
    logger.info("=" * 60)
    logger.info("STARTING SSMOUTPUT LOADER")
    logger.info("=" * 60)

    # Load today's ssmoutput files in parallel
    load_all_ssmoutput()


if __name__ == "__main__":
    main()
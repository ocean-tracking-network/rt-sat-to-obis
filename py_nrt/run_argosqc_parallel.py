#!/usr/bin/env python3
"""
Run R script with multiple config files in parallel threads.
"""

import argparse
import fnmatch
import logging00
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Dict, Any, List
from pathlib import Path
import json
import pandas as pd
import getpass

# Default configuration file to search
DEFAULT_SEARCH_PATTERN = "*config*.json"
DEFAULT_SEARCH_ROOT = './input'
DEFAULT_R_SCRIPT_DIR = "r_nrt"
DEFAULT_LOG_DIR = "./logs"
DEFAULT_MAX_THREADS = 4

# Setup log format
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(threadName)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Run R script with config files in parallel",
        epilog="Example: %(prog)s /path/to/configs --threads 6 --log-dir /tmp/logs"
    )
    parser.add_argument(
        'search_root', nargs='?', default=DEFAULT_SEARCH_ROOT,
        help='Root directory to search for config files (default: ./input)'
    )
    parser.add_argument(
        '-t', '--threads', type=int, default=DEFAULT_MAX_THREADS,
        help=f'Number of parallel threads (default: {DEFAULT_MAX_THREADS})'
    )
    parser.add_argument(
        '-l', '--log-dir', default=DEFAULT_LOG_DIR,
        help=f'Directory to store per-run log files (default: {DEFAULT_LOG_DIR})'
    )
    parser.add_argument(
        '-p', '--pattern', default=DEFAULT_SEARCH_PATTERN,
        help=f'Glob pattern for config files (default: "{DEFAULT_SEARCH_PATTERN}")'
    )
    parser.add_argument(
        '--sudo', action='store_true',
        help='Use sudo when running the R script (default: run as current user)'
    )
    parser.add_argument(
        '--r-executable',
        default='/opt/R/4.5.2/bin/Rscript',
        help='Path to the Rscript executable (default: /opt/R/4.5.2/bin/Rscript)'
    )
    return parser.parse_args()


def find_config_files(search_root: str, pattern: str) -> List[str]:
    """
    Find all configuration files matching the given pattern under the search root directory.

    This function recursively traverses the directory tree starting from `search_root`
    and collects all file paths whose names match the specified pattern.

    Args:
        search_root (str): The root directory path from which to start the search.
        pattern (str): A glob-style pattern to match file names (e.g., "*.conf", "config.*").

    Returns:
        List[str]: A list of absolute file paths that match the pattern.
                   If no matching files are found, an empty list is returned.
    """
    config_files = []
    for root, dirs, files in os.walk(search_root):
        for file in files:
            if fnmatch.fnmatch(file, pattern):
                config_files.append(os.path.join(root, file))
    return config_files


def run_r_script(config_file: str, log_dir: str, use_sudo: bool, r_executable: str = '/opt/R/4.5.2/bin/Rscript') -> Dict[str, Any]:
    """
    Run the R script with a given config file and capture output to a log file.
    """
    config_path = Path(config_file)

    # Parse vendor from config to determine which R script to use
    try:
        config_df = parse_vendor_config(config_path)

        # Determine which R script to use based on vendor
        vendor = config_df['vendor'].iloc[0] if not config_df.empty else None

        if vendor == 'SMRU':
            r_script_name = 'run_ArgosQC_smru_qc.R'
        elif vendor == 'WC':
            r_script_name = 'run_ArgosQC_wc_qc.R'
        else:
            raise Exception(f"Unknown vendor: {vendor}")

        # Write to run details
        config_df['qc_start_datetime'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        csv_path = Path.cwd() / "argosqc_run_details.csv"
        _csv_write_lock = threading.Lock()
        with _csv_write_lock:
            # Write header only if the file does not exist
            file_exists = csv_path.exists()
            config_df.to_csv(csv_path, mode='a', header=not file_exists, index=False)

        # Construct full path to R script in /opt/otn_nrt/rt-sat-to-obis/py_nrt/
        script_dir = Path(__file__).parent.parent
        argosqc_r_script_path = script_dir / DEFAULT_R_SCRIPT_DIR / r_script_name

        if not argosqc_r_script_path.exists():
            raise Exception(f"R script not found: {argosqc_r_script_path}")

    except Exception as e:
        logger.error(f"Error processing config {config_path}: {e}")
        return {
            'config': str(config_path),
            'log': None,
            'returncode': -1,
            'timestamp': datetime.now().strftime("%Y%m%d_%H%M%S"),
            'vendor': 'Unknown',
            'error': str(e)
        }

    config_name = config_path.stem
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = Path(log_dir) / f"{config_name}_{timestamp}.log"

    # Ensure log directory exists
    os.makedirs(log_dir, exist_ok=True)

    # Build the command
    cmd = []
    if use_sudo:
        cmd.append("sudo")
    cmd.extend([r_executable, str(argosqc_r_script_path), str(config_path)])

    logger.info(f"Starting: {config_path} with {r_script_name}")

    try:
        # Open log file and run the process
        with open(log_file, 'w') as log_f:
            log_f.write(f"Command: {' '.join(cmd)}\n")
            log_f.write(f"Config file: {config_path}\n")
            log_f.write(f"R script: {argosqc_r_script_path}\n")
            log_f.write("=" * 60 + "\n\n")
            log_f.flush()

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )

            # Stream output to log file in real-time
            for line in process.stdout:
                log_f.write(line)
                log_f.flush()

            process.wait()

        returncode = process.returncode
        if returncode == 0:
            logger.info(f"Completed: {config_path} (exit code: {returncode})")
        else:
            logger.error(f"Failed: {config_path} (exit code: {returncode})")

        return {
            'config': str(config_path),
            'log': str(log_file),
            'returncode': returncode,
            'timestamp': timestamp,
            'vendor': vendor,
            'error': None
        }

    except Exception as e:
        logger.exception(f"Exception running {config_path}: {e}")
        return {
            'config': str(config_path),
            'log': str(log_file),
            'returncode': -1,
            'timestamp': timestamp,
            'vendor': vendor,
            'error': str(e)
        }


def detect_vendor(row):
    wc_akey = str(row.get("harvest.wc.akey", "") or "").strip()
    smru_user = str(
        row.get("harvest.smru.user", row.get("harvest.smru.usr", "")) or ""
    ).strip()

    if wc_akey:
        return "WC"
    elif smru_user:
        return "SMRU"
    return None


def parse_vendor_config(config_path: str) -> pd.DataFrame:
    with open(config_path, "r", encoding="utf-8") as f:
        config_json = json.load(f)

    config_df = pd.json_normalize(config_json)

    # Apply vendor detection to the config_df
    config_df["vendor"] = config_df.apply(detect_vendor, axis=1)

    # Check if ANY value in the vendor column is valid, and handle properly
    vendor_values = config_df["vendor"].dropna()
    if len(vendor_values) == 0 or not vendor_values.isin(['SMRU', 'WC']).any():
        raise Exception(f'Can not determine vendor in configuration file: {config_path}')

    # Call appropriate parser based on vendor
    vendor = vendor_values.iloc[0]  # Get the first valid vendor

    if vendor == 'SMRU':
        return parse_smru_config(config_df)
    elif vendor == 'WC':
        return parse_wc_config(config_df)


def parse_smru_config(config_df: pd.DataFrame) -> pd.DataFrame:
    cols_map = {
        "setup.program": "program",
        "setup.output.dir": "output_dir",
        "meta.common_name": "common_name",
        "meta.species": "species",
        "meta.release_site": "release_site",
        "meta.state_country": "state_country"
    }

    # Ensure output_dir exists and split for proj_id
    if 'setup.output.dir' in config_df.columns:
        config_df['proj_id'] = config_df['setup.output.dir'].str.split('/').str[-1]
    else:
        config_df['proj_id'] = None

    # Select, rename, and add vendor
    result_df = (config_df[list(cols_map.keys())]
                 .rename(columns=cols_map)
                 .assign(vendor='SMRU'))

    # Add proj_id to result
    result_df['proj_id'] = config_df['proj_id'].values if 'proj_id' in config_df.columns else None

    return result_df


def parse_wc_config(config_df: pd.DataFrame) -> pd.DataFrame:
    cols_map = {
        "setup.program": "program",
        "setup.output.dir": "output_dir",
        "meta.common_name": "common_name",
        "meta.species": "species",
        "meta.release_site": "release_site",
        "meta.state_country": "state_country"
    }
    config_df['cid'] = ''
    # Ensure output_dir exists and split for proj_id
    if 'setup.output.dir' in config_df.columns:
        config_df['proj_id'] = config_df['setup.output.dir'].str.split('/').str[-1]
    else:
        config_df['proj_id'] = None

    # Select, rename, and add vendor
    result_df = (config_df[list(cols_map.keys())]
                 .rename(columns=cols_map)
                 .assign(vendor='WC'))

    # Add proj_id to result
    result_df['proj_id'] = config_df['proj_id'].values if 'proj_id' in config_df.columns else None

    return result_df


def main():
    args = parse_args()

    if os.geteuid() == 0:
        logger.warning("Running as root.")
    else:
        logger.warning(f"Running as {getpass.getuser()}.")

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
                args.sudo,
                args.r_executable
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

    # Exit code 1 when any thread failed
    if failed:
        logger.error(f"{len(failed)} thread(s) failed. Exiting with code 1.")
        sys.exit(1)
    else:
        logger.info(f"All {len(successful)} thread(s) succeeded. Exiting with code 0.")
        sys.exit(0)


if __name__ == "__main__":
    main()

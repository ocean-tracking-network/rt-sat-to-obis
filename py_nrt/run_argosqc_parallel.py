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
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List

# Default configuration file to search
DEFAULT_SEARCH_PATTERN = "*config*.json"
DEFAULT_SEARCH_ROOT = '../input'
DEFAULT_R_SCRIPT = "run_ArgosQC.R"
DEFAULT_LOG_DIR = "/var/log/argosqc"
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
        help='Root directory to search for config files (default: ../input)'
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
        '-s', '--script', default=DEFAULT_R_SCRIPT,
        help=f'R script to execute (default: {DEFAULT_R_SCRIPT})'
    )
    parser.add_argument(
        '--no-sudo', action='store_true',
        help='Do not use sudo when running the R script (run as current user)'
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


def run_r_script(config_file: str, r_script: str, log_dir: str, use_sudo: bool) -> Dict[str, Any]:
    """
    Run the R script with a given config file and capture output to a log file.

    This function executes an R script, passing the configuration file as an argument.
    All output (stdout and stderr) is captured and written to a timestamped log file
    inside the specified log directory. The function returns a dictionary containing
    the execution status, log file path, and any error details.

    Args:
        config_file (str): Path to the configuration file that the R script expects.
        r_script (str): Path to the R script to be executed.
        log_dir (str): Directory where log files will be stored. Created if it does not exist.
        use_sudo (bool): Whether to run the R script with elevated privileges (via sudo).

    Returns:
        Dict[str, Any]: A dictionary with the following keys:
            - 'success' (bool): True if the script executed without errors, False otherwise.
            - 'log_file' (str): Path to the generated log file.
            - 'return_code' (int): The exit code of the R process.
            - 'error_message' (str or None): Description of any error that occurred, if any.
    """
    config_path = Path(config_file)
    config_name = config_path.stem
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = Path(log_dir) / f"{config_name}_{timestamp}.log"

    # Ensure log directory exists
    os.makedirs(log_dir, exist_ok=True)

    # Build the command
    cmd = []
    if use_sudo:
        cmd.append("sudo")
    cmd.extend(["Rscript", r_script, str(config_path)])

    logger.info(f"Starting: {config_path}")

    try:
        # Open log file and run the process
        with open(log_file, 'w') as log_f:
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
            'error': None
        }

    except Exception as e:
        logger.exception(f"Exception running {config_path}: {e}")
        return {
            'config': str(config_path),
            'log': str(log_file),
            'returncode': -1,
            'timestamp': timestamp,
            'error': str(e)
        }


def main():
    args = parse_args()

    # Check if running as root or with sudo access (only for warning)
    if not args.no_sudo and os.geteuid() != 0:
        logger.warning("Not running as root. Commands will use sudo.")

    # Find all config files
    logger.info(f"Searching for '{args.pattern}' in '{args.search_root}'")
    config_files = find_config_files(args.search_root, args.pattern)

    if not config_files:
        logger.error("No config files found matching the pattern.")
        sys.exit(1)

    logger.info(f"Found {len(config_files)} config files")

    # Use ThreadPoolExecutor
    results = []
    with ThreadPoolExecutor(max_workers=args.threads) as executor:
        # Submit tasks
        future_to_config = {}
        for config in config_files:
            future = executor.submit(
                run_r_script,
                config,
                args.script,
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
            logger.info(f"  - {f['config']} (exit code: {f.get('returncode', 'N/A')})")
            if f.get('log'):
                logger.info(f"    Log: {f['log']}")
            if f.get('error'):
                logger.info(f"    Error: {f['error']}")

    logger.info(f"\nLogs saved to: {args.log_dir}")


if __name__ == "__main__":
    main()
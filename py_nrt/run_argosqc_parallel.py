#!/usr/bin/env python3
"""
Run R script with multiple config files in parallel threads
"""

import os
import subprocess
import threading
import queue
import logging
from pathlib import Path
from datetime import datetime
import sys

# Configuration
SEARCH_PATTERN = "*config*.json"
R_SCRIPT = "run_ArgosQC.R"
LOG_DIR = "/var/log/argosqc"
MAX_THREADS = 4  # Adjust based on your system

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(threadName)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class CommandRunner(threading.Thread):
    def __init__(self, task_queue, results_queue):
        super().__init__()
        self.task_queue = task_queue
        self.results_queue = results_queue
        self.daemon = True

    def run(self):
        while True:
            try:
                config_file = self.task_queue.get(timeout=1)
                self.run_command(config_file)
                self.task_queue.task_done()
            except queue.Empty:
                break
            except Exception as e:
                logger.error(f"Error processing {config_file}: {e}")
                self.task_queue.task_done()

    def run_command(self, config_file):
        """Run R script with config file and collect logs"""
        config_path = Path(config_file)
        config_name = config_path.stem
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Create log file path
        log_file = Path(LOG_DIR) / f"{config_name}_{timestamp}.log"

        # Ensure log directory exists with proper permissions
        os.makedirs(LOG_DIR, exist_ok=True)

        # Build the command
        cmd = [
            "sudo", "Rscript", R_SCRIPT,
            str(config_path)
        ]

        logger.info(f"Starting: {config_path}")

        try:
            # Run command and capture output
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

                if process.returncode == 0:
                    logger.info(f"Completed: {config_path} (exit code: {process.returncode})")
                else:
                    logger.error(f"Failed: {config_path} (exit code: {process.returncode})")

            # Store result in results queue
            self.results_queue.put({
                'config': str(config_path),
                'log': str(log_file),
                'returncode': process.returncode,
                'timestamp': timestamp
            })

        except Exception as e:
            logger.error(f"Exception running {config_path}: {e}")
            self.results_queue.put({
                'config': str(config_path),
                'log': str(log_file),
                'error': str(e),
                'returncode': -1
            })


def find_config_files(search_root=".", pattern=SEARCH_PATTERN):
    """Find all config files matching pattern"""
    config_files = []
    for root, dirs, files in os.walk(search_root):
        for file in files:
            if PatternMatcher(pattern).match(file):
                config_files.append(os.path.join(root, file))
    return config_files


class PatternMatcher:
    """Simple pattern matcher for wildcard patterns"""

    def __init__(self, pattern):
        self.pattern = pattern

    def match(self, filename):
        """Check if filename matches pattern"""
        import fnmatch
        return fnmatch.fnmatch(filename, self.pattern)


def main():
    """Main function to run parallel processing"""

    # Parse command line arguments
    if len(sys.argv) > 1:
        search_root = sys.argv[1]
    else:
        search_root = "."

    if len(sys.argv) > 2:
        max_threads = int(sys.argv[2])
    else:
        max_threads = MAX_THREADS

    # Find all config files
    logger.info(f"Searching for {SEARCH_PATTERN} in {search_root}")
    config_files = find_config_files(search_root)

    if not config_files:
        logger.error(f"No config files found matching {SEARCH_PATTERN}")
        return

    logger.info(f"Found {len(config_files)} config files")

    # Create queues
    task_queue = queue.Queue()
    results_queue = queue.Queue()

    # Add all config files to queue
    for config_file in config_files:
        task_queue.put(config_file)

    # Create and start threads
    threads = []
    for i in range(min(max_threads, len(config_files))):
        thread = CommandRunner(task_queue, results_queue)
        thread.start()
        threads.append(thread)
        logger.info(f"Started thread {thread.name}")

    # Wait for all tasks to complete
    task_queue.join()

    # Wait for threads to finish
    for thread in threads:
        thread.join(timeout=5)

    # Collect and display results
    logger.info("=" * 60)
    logger.info("SUMMARY")
    logger.info("=" * 60)

    results = []
    while not results_queue.empty():
        results.append(results_queue.get())

    successful = [r for r in results if r.get('returncode') == 0]
    failed = [r for r in results if r.get('returncode') != 0]

    logger.info(f"Total: {len(results)}")
    logger.info(f"Successful: {len(successful)}")
    logger.info(f"Failed: {len(failed)}")

    if failed:
        logger.info("\nFailed configurations:")
        for f in failed:
            logger.info(f"  - {f['config']} (exit code: {f.get('returncode', 'N/A')})")
            logger.info(f"    Log: {f.get('log', 'N/A')}")

    logger.info(f"\nLogs saved to: {LOG_DIR}")


if __name__ == "__main__":
    # Check if running as root or with sudo access
    if os.geteuid() != 0:
        logger.warning("Not running as root. Commands will use sudo.")

    main()
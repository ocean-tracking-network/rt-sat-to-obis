"""
Pull otn_satellite_tag and related animals from OTNUNIT DB to OTNSAT DB
"""
import logging
import os
import sys

sys.path.insert(0, os.getcwd())
from common import pull_sat_tags_from_otnunit_to_otnsat
DEFAULT_LOG_DIR = "./logs"
# Setup log format
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(threadName)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def main():
    """
    Main function to load today's ssmoutput files in parallel.
    """
    logger.info("=" * 60)
    logger.info("STARTING to pull otn_satellite_tag and related animals from OTNUNIT DB to OTNSAT DB")
    logger.info("=" * 60)

    pull_sat_tags_from_otnunit_to_otnsat()


if __name__ == "__main__":
    main()
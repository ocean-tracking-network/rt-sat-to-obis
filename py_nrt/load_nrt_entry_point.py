#!/usr/bin/env python
"""
Script to load NRT results to database with logging.
"""

import os
import sys
import logging
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from py_nrt.common import get_engine
from py_nrt import load_nrt_results as lnr
import itables


def setup_logging(log_file=None):
    """Setup logging configuration."""
    if log_file is None:
        log_dir = 'logs'
        os.makedirs(log_dir, exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        log_file = os.path.join(log_dir, f'nrt_load_{timestamp}.log')

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )

    return logging.getLogger('load_nrt_to_db')


def main():
    """Main function to load NRT results to database."""

    logger = setup_logging()
    logger.info("=" * 60)
    logger.info("Starting NRT load process")
    logger.info("=" * 60)

    try:
        logger.info("Initializing database engine...")
        # TODO: change to read DB auth
        engine = get_engine(r"database_conn_string.auth")
        logger.info(f"Engine created for host: {engine.url.host}")

        # Check backend
        qc_output_path = '../qc'
        logger.info("Checking OTN NRT backend...")
        if lnr.check_otn_nrt_backend(engine):
            logger.info("OTN NRT backend is available")
        else:
            logger.warning("OTN NRT backend is not available")

        # Get QCed programs
        logger.info(f"Getting QCed programs from {qc_output_path}...")
        programs = lnr.get_qced_programs(qc_output_path)
        logger.info(f"Found {len(programs)} programs: {programs}")

        if not programs:
            logger.warning("No QCed programs found. Exiting.")
            return

        # Process each program
        for program in programs:
            logger.info(f"\n{'=' * 40}")
            logger.info(f"Processing program: {program}")
            logger.info(f"{'=' * 40}")

            try:
                # Get QC results for program
                logger.info(f"Getting QC results for program: {program}")
                ssmoutput_last_modified_map = lnr.get_project_qc_results_for_program(
                    qc_output_path, program
                )

                if not ssmoutput_last_modified_map:
                    logger.warning(f"No QC results found for program: {program}")
                    continue

                logger.info(f"Found {len(ssmoutput_last_modified_map)} QC results to process")
                for output_csv, last_modified in list(ssmoutput_last_modified_map.items())[:3]:
                    logger.info(f"  - {output_csv}: {last_modified}")
                if len(ssmoutput_last_modified_map) > 3:
                    logger.info(f"  ... and {len(ssmoutput_last_modified_map) - 3} more")

                # Load to database
                logger.info("Loading results to database...")
                summary_df = lnr.load_to_nrt_db(engine, ssmoutput_last_modified_map)

                # Display summary
                if summary_df is not None and not summary_df.empty:
                    logger.info("Load summary:")
                    logger.info(f"\n{summary_df.to_string()}")

                    # Show interactive table
                    try:
                        itables.show(summary_df)
                    except Exception as e:
                        logger.warning(f"Could not display interactive table: {e}")
                else:
                    logger.info("No new data loaded")

            except Exception as e:
                logger.error(f"Error processing program {program}: {e}", exc_info=True)
                continue

        logger.info("\n" + "=" * 60)
        logger.info("NRT load process completed successfully")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"Fatal error in main process: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
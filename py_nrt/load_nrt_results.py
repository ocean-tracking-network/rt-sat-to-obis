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
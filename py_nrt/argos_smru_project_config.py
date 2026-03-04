import binascii
import hashlib
import json
import os
import zipfile

import typing
from collections import defaultdict
from datetime import datetime, date
from functools import partial
from itertools import product
import requests
import hashlib
import hmac
import pandas as pd
import xml.etree.ElementTree as ET
from pathlib import Path
import zipfile
import shutil
from datetime import datetime
from typing import List, Tuple
import subprocess
import pandas as pd
import os
import tempfile
from typing import Tuple

import numpy as np
import pandas as pd
import plotly
import requests
from IPython import get_ipython
from ipywidgets import Layout, Checkbox, VBox, Label, Box, Button, widgets, HTML, RadioButtons
from IPython.display import display
from shapely import wkb
import xmltodict
from pandas import json_normalize

from sqlalchemy.engine import Engine
import itables
import re
import hmac
import hashlib
import requests
import pandas as pd
from xml.etree import ElementTree as ET
import warnings

from py_nrt.common import run_from_ipython

itables.init_notebook_mode()
# SMRU API endpoint
SMRU_API_ENDPOINT = 'www.smru.st-andrews.ac.uk'
import os
import requests
import zipfile
from pathlib import Path
from typing import List, Optional
from tqdm import tqdm
import shutil
import time


def smru_get_mdb(cid: str, dest: str,user: str, pwd: str, timeout: int = 120, verbose: bool = False) -> None:
    """
    Download and extract SMRU database files.

    Args:
    cid : str
        collection IDs to download
    dest : str
        Destination directory for downloaded files
    user : str
        Username for authentication
    pwd : str
        Password for authentication
    timeout(int): Timeout in seconds for download operations (default: 120)
    verbose(bool): Whether to show progress bars (default: False)
    """

    if dest is None:
        raise ValueError("dest must be specified")
    if not os.path.exists(dest):
        raise ValueError(f"Destination directory {dest} does not exist")
    if user is None:
        raise ValueError("user must be specified")
    if pwd is None:
        raise ValueError("pwd must be specified")

    dest_path = Path(dest)

    # Download each CID
    for cid in tqdm([cid], desc=f"Downloading .mdb for {cid}", disable=not verbose):
        # Construct request URL for mdb.zip
        url = f"http://{user}:{pwd}@{SMRU_API_ENDPOINT}/protected/{cid}/db/{cid}.zip"
        download_and_extract(url, cid, dest_path)


def download_and_extract(mdb_url: str, cid: str, dest_path:Path, timeout: int=180, verbose: bool=False) -> None:
    """Download and extract a single CID file."""
    # Destination paths
    zip_path = dest_path / f"{cid}.zip"
    extract_path = dest_path

    try:

        response = requests.get(
            mdb_url,
            timeout=timeout,
            stream=True
        )

        if verbose:
            print(f"response: {response}")

        response.raise_for_status()

        # Save zip file
        with open(zip_path, 'wb') as f:
            if verbose:
                # Show progress bar for download
                total_size = int(response.headers.get('content-length', 0))
                with tqdm(total=total_size, unit='B', unit_scale=True,
                          desc=f"Downloading {cid}", disable=not verbose) as pbar:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                        pbar.update(len(chunk))
            else:
                f.write(response.content)

        # Extract zip file
        if verbose:
            print(f"Extracting {cid}...")

        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_path)

        # Remove zip file
        # os.remove(zip_path)

    except requests.exceptions.RequestException as e:
        print(f"Error downloading {cid}: {e}")
        # Clean up partial download if it exists
        if zip_path.exists():
            os.remove(zip_path)
        raise
    except zipfile.BadZipFile as e:
        print(f"Error extracting {cid}: Invalid zip file")
        if zip_path.exists():
            os.remove(zip_path)
        raise
    except Exception as e:
        print(f"Unexpected error processing {cid}: {e}")
        if zip_path.exists():
            os.remove(zip_path)
        raise


def extract_deployments(cid: str, input_path: str, verbose: bool=False) -> dict[str, pd.DataFrame]:
    """
    Extract deployments table from <cid>.mdb (Access DB)

    Args:
        cid: Collection ID for the Access database file
        input_path: Path to the directory containing the <cid>.mdb file
        verbose: If True, print additional information during execution

    Returns:
        Dictionary containing DataFrames with deployment data, typically including
        tables like 'deployments', 'sensors', or other related tables from the Access DB
    """
    mdb_file = cid + '.mdb'
    table = 'deployments'
    return extract_table_from_mdb(input_path, mdb_file, table, verbose)


def extract_tacks(cid: str, input_path: str, exclude_tag_ref: list[str], verbose: bool=False) -> tuple[str, pd.DataFrame]:
    """
    Extract tracks data (ctd table) from <cid>.mdb (Access DB) and filter out excluded tags

    Args:
        cid: Collection ID for the Access database file
        input_path: Path to the directory containing the <cid>.mdb file
        exclude_tag_ref: List of tag references to exclude from the extracted tracks
        verbose: If True, print additional information during execution

    Returns:
        Tuple of .mdb file and dataFrame of all tracks excluding specified tags
    """
    mdb_file = cid + '.mdb'
    table = 'ctd'
    mdb_file, tracks_df = extract_table_from_mdb(input_path, mdb_file, table, verbose)
    tracks_df = tracks_df[~tracks_df['REF'].isin(exclude_tag_ref)]
    return mdb_file, tracks_df


def extract_table_from_mdb(input_path: str, mdb_file: str, table: str, verbose=False) -> Tuple[str, pd.DataFrame]:
    """
    Extract a table from an .mdb file using mdbtools on Windows.
    """
    mdb_full_path = os.path.join(input_path, mdb_file)

    if not os.path.exists(mdb_full_path):
        raise FileNotFoundError(f"{mdb_file} is not found in: {input_path}")

    if verbose:
        print(f"Exporting table '{table}' from {mdb_file}...")

    # Create temp file
    with tempfile.NamedTemporaryFile(mode='w+', suffix='.csv', delete=False) as temp_csv:
        temp_csv_path = temp_csv.name

    # Export table to CSV
    with open(temp_csv_path, 'w', newline='', encoding='utf-8') as csv_file:
        subprocess.run(
            ['mdb-export', mdb_full_path, table],
            stdout=csv_file,
            check=True,
            shell=True
        )

    # Read CSV into DataFrame
    df = pd.read_csv(temp_csv_path)

    # Clean up
    os.unlink(temp_csv_path)

    return (mdb_file, df)

def create_smru_qc_config(
        data_dir: Path = None,
        dest_path: Path = None,
        a_key: str = None,
        s_key: str = None,
        collaborator: str = None,
        time_step: int = 3,
        program: str=None,
        project_id: str =None,
        common_name: str = None,
        species: str = None,
        release_site: str = None,
        state_country: str = None,
        tag_uuid_list: list[str] = []
) -> list:
    """
    Create a configuration file for smru_qc with customizable parameters.

    Args:
        owner_id: Owner ID for harvest section
        time_step: Time step for model section
        common_name: Common name for meta section
        species: Species name for meta section
        release_site: Release site for meta section
        state_country: State/Country for meta section

    Returns:
        List containing the configuration template
    """
    wc_qc_config = [
        {
            "setup": {
                "program": program,
                "data.dir": data_dir,
                "meta.file": None,
                "maps.dir": f"output/maps/{project_id}",
                "diag.dir": f"output/diag/{project_id}",
                "output.dir": f"output/{program}/{project_id}",
                "return.R": True
            },
            "harvest": {
                "download": False,
                "owner.id": collaborator.split(' - ')[-1],
                "wc.akey": a_key,
                "wc.skey": s_key,
                "tag.list": f"{program}_{project_id}_tags.csv",
                "dropIDs": None
            },
            "model": {
                "model": "rw",
                "vmax": 3,
                "time.step": time_step,
                "proj": None,
                "reroute": True,
                "dist": 20,
                "barrier": None,
                "buffer": 0.25,
                "centroids": True,
                "cut": False,
                "min.gap": 72,
                "QCmode": "nrt",
                "pred.int": 12
            },
            "meta": {
                "common_name": common_name,
                "species": species,
                "release_site": release_site,
                "state_country": state_country
            }
        }
    ]
    output_path = os.path.join(dest_path, f'{program}_{project_id}_wc.json')
    with open(output_path, 'w') as f:
        json.dump(wc_qc_config, f, indent=2, ensure_ascii=False)
    tag_list_file = os.path.join(dest_path, f'{program}_{project_id}_tags.csv')
    with open(tag_list_file, 'w') as f:
        f.write('\n'.join(['uuid'] + tag_uuid_list))
    print(f'wc_qc config file is written to {output_path}')
    print(f'tag list config file is written to {tag_list_file}')

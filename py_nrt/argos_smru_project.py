from IPython.display import display, HTML
import binascii
import hashlib
import json
import os
import sys
import zipfile
import subprocess

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
from typing import Dict, Optional, List, Union, Any, Tuple

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

from py_nrt.common import run_from_ipython, show_df, show_program_dropdown, show_collectioncode_textbox, evaluate_input, get_notebook_base_url, check_file_exists
from py_nrt.load_nrt_results import get_files_by_pattern
from ipywidgets.widgets import widget, VBox, Text, HTML, RadioButtons

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


def show_data_upload_mode_radio() -> RadioButtons:
    from IPython.display import display
    date_upload_mode_dict = {
        'nrt': 'Ongoing: near real-time mode',
        'delay': 'Completed: delay mode'
    }
    choices = list(date_upload_mode_dict.values())

    radio = RadioButtons(options=choices, value=None)
    display(HTML('<h3 style="margin: 0; color: blue;">Please choose project status:</h3>'))
    display(radio)
    return radio


def show_cid_textbox() -> Text:
    cid_textbox = Text(
        value='',
        placeholder='SMRU Campaign ID',
        description='Campaign ID:',
        disabled=False,
        layout=Layout(width='400px')
    )
    display(HTML('<h3 style="margin: 0; color: blue;">SMRU campaign ID:</h3>'))
    display(cid_textbox)
    return cid_textbox


def show_user_passwd_textboxes() -> Tuple[Text, Text]:
    user_textbox = Text(
        value='',
        placeholder='SMRU login user',
        disabled=False,
        layout=Layout(width='400px')
    )
    passwd_textbox = Text(
        value='',
        placeholder='SMRU login password',
        disabled=False,
        layout=Layout(width='400px')
    )
    display(user_textbox)
    display(passwd_textbox)
    return user_textbox, passwd_textbox


def show_controls_for_upload_mode(radio: RadioButtons):
    if not radio.value:
        display(HTML('<h4 style="margin: 0; color: red;">Please select an option to continue...</h4>'))


def get_user_input(user_input_dict: Dict) -> Optional[Tuple]:
    """
    Parse user input
    """
    # Validate all widgets
    for key, widget in user_input_dict.items():
        if not evaluate_input(key, widget):  # or evaluate_input(widget)
            return None, None, None, None
    upload_mode = 'delay' if 'delay' in user_input_dict['upload_mode'].value else 'nrt'
    return (user_input_dict['program'].value, upload_mode, user_input_dict['cid'].value, user_input_dict['collectioncode'].value)


def show_smru_login_or_local_mdb(qc_input_path: str, program: str, upload_mode: str, cid: str, collectioncode, base_url) -> Optional[Tuple]:
    """
    Show SMRU login text boxes or local .mdb file.

    Args:
        qc_input_path (str): Path to the QC input file/directory
        program (str): The program name for the QC configuration
        upload_mode (str): The upload mode being used
        cid (str): Collection/collaboration identifier
        collectioncode: OTN collection code identifier (type unspecified)
        base_url (str): Base URL for the SMRU service

    Returns: Tuple of Text for SMRU user and password
    """
    if upload_mode == 'nrt':
        display(HTML('<h3 style="margin: 0; color: blue;">Near real-time mode require SMRU login credentials:</h3>'))
        return show_user_passwd_textboxes()
    elif upload_mode == 'delay':
        current_dir = os.path.dirname(__file__)
        relative_path = os.path.join(qc_input_path, program, f'{program}_{cid}', 'mdb')
        folder_path = os.path.join(os.path.dirname(current_dir), relative_path)
        upload_url = os.path.join(base_url, qc_input_path, program, f'{program}_{cid}', 'mdb')

        html_messages = {
            'found': [
                HTML(f'<h3 style="margin: 0; color: blue;">Found {cid}.mdb file in folder: {relative_path}</h3>'),
                HTML(f'<a href="{upload_url}" target="_blank">Click here to view existing {cid}.mdb in new tab.</a>')
            ],
            'missing': [
                HTML(f'<h3 style="margin: 0; color: blue;">Delay mode requires user to upload {cid}.mdb file to below folder: {relative_path}</h3>'),
                HTML(f'<a href="{upload_url}" target="_blank">Click here to upload {cid}.mdb in new tab.</a>')
            ]
        }
        check_file_exists(relative_path, f'{cid}.mdb', html_messages, upload_url, True, False)

        return None, None


def create_folder_instruct_upload_mdb(program, upload_mode, cid, collectioncode) -> Optional[Tuple]:
    pass


def get_path_from_strings(path_string_parts: []) ->Path:
    """
    Construct a Path object from a list of string parts.

    Args:
        path_string_parts (List[str]): List of path components to join

    Returns:
        Path: Combined Path object
    """
    if not path_string_parts:
        return Path()
    parent_path = Path(os.path.sep.join(path_string_parts[0:-1]))
    if not os.path.exists(parent_path):
        parent_path.mkdir(parents=True, exist_ok=True)

    path = Path(path_string_parts[0])
    for part in path_string_parts[1:]:
        path = path / part
    return path


def smru_get_mdb(program: str, cid: str,  user: str, pwd: str, qc_input_path: str, otn_collection_code: str='', timeout: int = 120, verbose: bool = False) -> None:
    """
    Download and extract SMRU database files.

        program (str): Program name identifier for the database request
        cid (str): Collection IDs to download
        user (str): Username for authentication
        pwd (str): Password for authentication
        qc_input_path (str): Destination directory path for downloaded files
        otn_collection_code (str, optional): OTN collection code identifier. Defaults to ''.
        timeout (int, optional): Timeout in seconds for download operations. Defaults to 120.
        verbose (bool, optional): Whether to show progress bars during download. Defaults to False.
    """

    if qc_input_path is None:
        raise ValueError("dest must be specified")
    if not os.path.exists(qc_input_path):
        Path(qc_input_path).mkdir(parents=True, exist_ok=True)

    download_path = get_path_from_strings([qc_input_path, program, f"{program}_{cid}", 'mdb'])
    download_path.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {cid}.mdb to '{download_path}'")

    if user is None:
        raise ValueError("user must be specified")
    if pwd is None:
        raise ValueError("pwd must be specified")

    print(f'Optional arguments: otn_collection_code: {otn_collection_code}; timeout: {timeout}')

    # Download the CID
    for cid in tqdm([cid], desc=f"Downloading .mdb for {cid}", disable=not verbose):
        # Construct request URL for mdb.zip
        url = f"http://{user}:{pwd}@{SMRU_API_ENDPOINT}/protected/{cid}/db/{cid}.zip"
        download_and_extract(url, cid, download_path)


def download_and_extract(mdb_url: str, cid: str, dest_path: Path, timeout: int=180, verbose: bool=False) -> None:
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


def extract_deployments(program: str, cid: str, input_path: str, mdb_path: str='', verbose: bool=False) -> dict[str, pd.DataFrame]:
    """
    Extract deployments table from <cid>.mdb (Access DB)

    Args:
        program: program ID
        cid: Collection ID
        input_path: Path to the directory containing the <cid>.mdb file
        verbose: If True, print additional information during execution

    Returns:
        Dictionary containing DataFrames with deployment data, typically including
        tables like 'deployments', 'sensors', or other related tables from the Access DB
    """
    mdb_file = cid + '.mdb'
    table = 'deployments'
    cid_mdb, deployment_df = extract_table_from_mdb(get_path_from_strings([input_path, program, f'{program}_{cid}', 'mdb']), mdb_file, table, mdb_path, verbose)
    show_df(deployment_df, f'{cid}_deployment_df', True)
    return cid_mdb, deployment_df

def extract_tacks(program: str, cid: str, input_path: str, exclude_tag_ref: list[str], mdb_path:str='', verbose: bool=False) -> tuple[str, pd.DataFrame]:
    """
    Extract tracks data (diag table) from <cid>.mdb (Access DB) and filter out excluded tags

    Args:
        program: program ID
        cid: Collection ID for the Access database file
        input_path: Path to the directory containing the <cid>.mdb file
        exclude_tag_ref: List of tag references to exclude from the extracted tracks
        verbose: If True, print additional information during execution

    Returns:
        Tuple of .mdb file and dataFrame of all tracks excluding specified tags
    """
    mdb_file = cid + '.mdb'
    table = 'diag'
    mdb_file, tracks_df = extract_table_from_mdb(get_path_from_strings([input_path, program, f'{program}_{cid}', 'mdb']), mdb_file, table, mdb_path, verbose)
    tracks_df = tracks_df[~tracks_df['REF'].isin(exclude_tag_ref)]
    tracks_min_max_date_df = tracks_df.groupby('REF', group_keys=False).apply(partial(keep_min_max, column='D_DATE'))
    print(f'Showing min and max dates rows in the "diag" table for each REF ({tracks_min_max_date_df.shape[0]} out of {tracks_df.shape[0]}) rows,')
    show_df(tracks_min_max_date_df, f'{cid}_tracks_min_max_date_df', True)
    return mdb_file, tracks_df

def keep_min_max(dataframe: pd.DataFrame, column: str) -> pd.DataFrame:
    """
    Keep rows where a column equals its minimum or maximum value within the DataFrame.

    Args:
        dataframe: Input DataFrame
        column: Name of the column to evaluate min/max on

    Returns:
        DataFrame containing only rows where the specified column
    """
    min_date = dataframe[column].min()
    max_date = dataframe[column].max()
    return dataframe[dataframe[column].isin([min_date, max_date])]

def export_for_kepler(cid: str, tracks_df: pd.DataFrame, subset_tags: list[str] = []) -> pd.DataFrame:
    """
    Export animal tracking data to a format compatible with Kepler.gl visualization.

    This function processes and exports telemetry/tracking data for use in Kepler.gl,
    an open-source geospatial data visualization tool. The exported file can be
    directly loaded into Kepler.gl for interactive mapping and temporal analysis.

    Args:
        cid (str): Collection ID.
        tracks_df (pd.DataFrame): DataFrame containing tag location data
    Returns: tracks_subset
    """
    filename = f"{cid}_tracks_{datetime.now().strftime('%Y%m%d')}.csv"
    tracks_subset = tracks_df[['REF', 'D_DATE', 'LAT', 'LON']].copy().rename(columns={
        'REF': 'tag_ref',
        'D_DATE': 'date_time'
    })
    tracks_subset['date_time'] = pd.to_datetime(
        tracks_subset['date_time'],
        format='%d/%m/%y %H:%M:%S',  # Explicit format
        dayfirst=True,
        errors='coerce'
    )
    if subset_tags:
        tracks_subset = tracks_subset[tracks_subset['tag_ref'].isin(subset_tags)]
    show_df(tracks_subset, filename, True)
    return tracks_subset


def extract_table_from_mdb(input_path: str, mdb_file: str, table: str, mdb_path: str='', verbose=False) -> Tuple[str, pd.DataFrame]:
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
        # Construct the command
        mdb_export_cmd = os.path.join([mdb_path, 'mdb-export']) if mdb_path else 'mdb-export'
        cmd = [mdb_export_cmd, mdb_full_path, table]

        # Print the full command
        print(f"Running command: {' '.join(cmd)}")

        # Run the command
        subprocess.run(cmd, stdout=csv_file, check=True)

    # Read CSV into DataFrame
    df = pd.read_csv(temp_csv_path)

    # Clean up
    os.unlink(temp_csv_path)

    return (mdb_file, df)


def create_smru_qc_config(
        upload_mode:str,
        program: str,
        cid: str,
        deployment_df: pd.DataFrame,
        drop_ids: list[str],
        otn_collection_code: str,
        qc_input_path: Path,
        qc_output_path: Path,
        mdb_tables_path: str,
        user: str,
        password: str,
        timeout: int=180,
        download: bool=True,
        time_step: int = 3,
        common_name: str = None,
        species: str = None,
        release_site: str = None,
        state_country: str = None,
        notebook_base_url: str = '',
        verbose=False
) -> list:
    """
    Create a configuration file for smru_qc with customizable parameters.

    Args:
        program (str): The program name for the QC configuration
        deployment_meta_file_for_argosqc (str): deployment meta file for ArgosQC
        cid (str): Collection/collaboration identifier
        deployment_df (pd.DataFrame): vendor deployment dataframe.
        drop_ids (list[str]): List of drop/tag IDs to process
        otn_collection_code (str): OTN collection code identifier
        qc_input_path (Path): Directory path containing input data files
        qc_output_path (Path): Directory path for QC output files
        mdb_tables_path (Path): .mdb file path
        user (str): Username for database authentication
        password (str): Password for database authentication
        timeout (int, optional): Time step interval in hours. Defaults to 180 (seconds).
        download (bool, optional): download or not.
        time_step (int, optional): Time step interval in hours. Defaults to 3.
        common_name (Optional[str], optional): Common name of the species. Defaults to None.
        species (Optional[str], optional): Scientific species name. Defaults to None.
        release_site (Optional[str], optional): Release location. Defaults to None.
        state_country (Optional[str], optional): State or country of release. Defaults to None.
        notebook_base_url (Optional[str], optional): Notebook base URL.

    Returns:
        List containing the configuration template
    """
    drop_ids_file = f'exclude_tags.csv'
    meta_file = None
    first_loc_type = deployment_df['LOC_TYPE'].iloc[0]
    if first_loc_type.upper() == 'G':
        proj = '+proj=merc +ellps=WGS84 +units=km +no_defs'
    elif first_loc_type.upper() == 'K':
        proj = '+proj=stere +lat_0=-90 +lat_ts=-71 +lon_0=100 +k=1 +ellps=WGS84 +units=km +no_defs'
    else:
        proj = None  # or a default projection

    if not proj:
        proj = '+proj=stere +lat_0=-90 +lat_ts=-71 +lon_0=100 +k=1 +ellps=WGS84 +units=km +no_defs'
        display(HTML(f'<h3 style="margin: 0; color: red;">Can not determine projection type from SMRU deployment table:\n Setting to default {proj}</h3>'))
        show_df(deployment_df, 'vendor_deployment_df.csv')

    project_id = build_project_id_smru(program, cid)
    if upload_mode == 'nrt':
        if (not user) or (not password):
            display(HTML(f'<h3 style="margin: 0; color: red;">Near real-time configuration requires SUMR user and password.</h3>'))
    elif upload_mode == 'delay':
        deployment_meta_file_for_argosqc, deployments_for_argosqc_df = export_deployment_for_argosqc(program, cid,
                                                                              deployment_df,
                                                                              qc_input_path,
                                                                              notebook_base_url)
        deployments_for_argosqc_df['state_city'] = state_country
        deployments_for_argosqc_df['common_name'] = common_name
        deployments_for_argosqc_df['species'] = species
        deployments_for_argosqc_df['release_site'] = release_site
        meta_file = deployment_meta_file_for_argosqc
    smru_qc_config = [
        {
            "setup": {
                "program": program,
                "data.dir": f'{qc_input_path}/{program}/{project_id}/mdb',
                "meta.file": meta_file,
                "maps.dir": f"{qc_output_path}/{program}/{project_id}/maps",
                "diag.dir": f"{qc_output_path}/{program}/{project_id}/diag",
                "output.dir": f"{qc_output_path}/{program}/{project_id}",
                "return.R": verbose
            },
            "harvest": {
                "download": download,
                "cid": cid,
                "smru.usr": user,
                "smru.pwd": password,
                "timeout": timeout,
                "dropIDs": f'{qc_input_path}/{program}/{project_id}/{drop_ids_file}',
                "p2mdbtools": mdb_tables_path
            },
            "model": {
                "model": "crw",
                "vmax": 3,
                "time.step": time_step,
                "proj": proj,
                "reroute": True,
                "dist": 500,
                "barrier": None,
                "buffer": 0.5,
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
    qc_config_file = get_path_from_strings([qc_input_path, program, f'{program}_{cid}', f'config_{cid}.json'])
    with open(qc_config_file, 'w') as f:
        json.dump(smru_qc_config, f, indent=2, ensure_ascii=False)
    exclude_tags_file = get_path_from_strings([qc_input_path, program, f'{program}_{cid}', drop_ids_file])
    with open(exclude_tags_file, 'w') as f:
        f.write('\n'.join(drop_ids))
    upload_url = os.path.join(notebook_base_url, qc_input_path, program, f'{program}_{cid}')
    relative_path = f'{qc_input_path}/{program}/{project_id}'
    html_messages = {
        'found':  [
            HTML(f'<h3 style="margin: 0; color: blue;">Generated ArgosQC config files: config_{cid}.json and {drop_ids_file}</h3>'),
            HTML(f'<a href="{upload_url}" target="_blank">Click here to review or modify config files in a new tab.</a>')
        ],
        'missing': [
            HTML(f'<h3 style="margin: 0; color: red;">No Argos config files found in {qc_input_path}. Please contact OTN data team for assistant.</h3>')
        ]
    }
    check_file_exists(relative_path, f'config_{cid}.json', html_messages, upload_url, False, False)

    display(HTML(f'''<p>
        <span style="font-size:25px;"><i class="fa fa-flip-horizontal">🐟</i></span>
        <span style="font-size:20px;">~ Paste this into issue: </span>
        <span style="font-size:20px; color:#392696">smru_qc config file is written to: {Path(qc_config_file).as_posix()}</span>
    </p>'''))
    return [qc_config_file, exclude_tags_file]


def build_project_id_smru(program: str, cid: str) -> str:
    """
    Build a project ID from program, collaborator email, and common name.
    Args:
        program: The program name
        cid: CID of the project
    Returns:
        Formatted project ID string: {program}_{cid}
    """
    project_id = f'{program}_{cid}'
    return project_id


def extract_ssmoutput_tracks(program: str, cid: str, qc_output_path: str, subset_tags: list[str]=[], verbose=False) -> pd.DataFrame:
    ssmoutput_folder = get_path_from_strings([qc_output_path, program, f'{program}_{cid}'])
    ssmoutput_files = get_files_by_pattern(ssmoutput_folder, '*ssmoutputs*.csv')
    if not ssmoutput_files:
        print(f'No SSM output file found in {ssmoutput_folder}')
        return pd.DataFrame()

    ssmoutputs_df = pd.read_csv(ssmoutput_files[0])
    itables.show(ssmoutputs_df)
    ssmoutputs_df = ssmoutputs_df[['ref', 'date', 'lat', 'lon']].copy().rename(columns={
        'ref': 'tag_ref',
        'date': 'date_time'
    })
    ssmoutputs_df['date_time'] = pd.to_datetime(
        ssmoutputs_df['date_time'],
        format='mixed',
        dayfirst=True
    )
    if subset_tags:
        ssmoutputs_df = ssmoutputs_df[ssmoutputs_df['tag_ref'].isin(subset_tags)]
    filename = f"{cid}_ssmoutput_{datetime.now().strftime('%Y%m%d')}.csv"
    show_df(ssmoutputs_df, filename, True)
    return ssmoutputs_df


def run_smru_qc(r_executable: str, config_file: str, argosqc_r_script = 'r_nrt/run_ArgosQC_smru_qc.R'):
    is_rscript = 'rscript' in r_executable.lower() or r_executable.lower() == 'rscript'

    if is_rscript:
        # Rscript: script and args directly
        cmd = [r_executable, argosqc_r_script, config_file]
    else:
        # R: use --vanilla -f script.R --args
        cmd = [
            r_executable,
            '--vanilla',
            '-f', argosqc_r_script,
            '--args', config_file
        ]

    print(f"Running ArgosQC: {' '.join(cmd)}")

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1
    )

    # Read stdout and stderr in real-time
    while True:
        stdout_line = process.stdout.readline()
        if stdout_line:
            print(f"{stdout_line}", end='')
            sys.stdout.flush()

        stderr_line = process.stderr.readline()
        if stderr_line:
            print(f"{stderr_line}", end='')
            sys.stderr.flush()

        if process.poll() is not None:
            # Read any remaining output
            remaining_stdout = process.stdout.read()
            if remaining_stdout:
                print(f"{remaining_stdout}", end='')

            remaining_stderr = process.stderr.read()
            if remaining_stderr:
                print(f"{remaining_stderr}", end='')
            break

    if process.returncode == 0:
        print(f"ArgosQC completed successfully!")
    else:
        print(f"ArgosQC failed with return code: {process.returncode}")


def export_deployment_for_argosqc(program: str, cid: str, deployment_df: pd.DataFrame, qc_input_path: str, notebook_base_url: str) -> Tuple[str, pd.DataFrame]:
    """
    Transform vendor metadata into ArgosQC required format.

    Args:
        program: The program name
        cid: CID of the project
        deployment_df: DataFrame containing deployment metadata from vendor
        qc_input_path: File path where QC input data should be written
        notebook_base_url: Base URL for notebook server links

    Returns:
        Exported deployment metadata file name
    """
    na_columns = ['common_name', 'age_class', 'sex', 'length', 'estimated_mass', 'actual_mass',  'state_country']
    column_mapping = {
        'sattag_program': 'GREF',
        'device_id': 'REF',
        'ptt': 'PTT',
        'body': 'BODY',
        'device_wmo_ref': 'WMO',
        'tag_type': 'PARMS',
        'species': 'SPECIES',
        'release_site': 'LOCATION',
        'release_date': 'ON_DATE',
        'recovery_date': 'OFF_DATE',
        'release_latitude': 'HOME_LAT',
        'release_longitude': 'HOME_LON',
    }
    deployments_for_argosqc_df = deployment_df[list(column_mapping.values())].copy()

    # Rename columns from mapping values to keys
    deployments_for_argosqc_df = deployments_for_argosqc_df.rename(
        columns={v: k for k, v in column_mapping.items()})

    # Add NA columns with NaN values
    for col in na_columns:
        deployments_for_argosqc_df[col] = 'NA'

    date_columns = ['release_date', 'recovery_date']
    for col in date_columns:
        if col in deployments_for_argosqc_df.columns:
            # Convert from '06/20/22 00:00:00' to '2022-06-20T00:00:00Z'
            deployments_for_argosqc_df[col] = pd.to_datetime(deployments_for_argosqc_df[col], format='%m/%d/%y %H:%M:%S')
            deployments_for_argosqc_df[col] = deployments_for_argosqc_df[col].dt.strftime('%Y-%m-%dT%H:%M:%SZ')
            # Replace 'NaT' with empty string (will be converted to NA later)
            deployments_for_argosqc_df[col] = deployments_for_argosqc_df[col].replace('NaT', '')

    current_dir = os.path.dirname(__file__)
    relative_path = os.path.join(qc_input_path, program, f'{program}_{cid}')
    file_name = f'{cid}_deployment_meta_delay.csv'
    folder_path = os.path.join(os.path.dirname(current_dir), relative_path)
    upload_url = os.path.join(notebook_base_url, qc_input_path, program, f'{program}_{cid}')
    html_messages = {
        'found':  [
            HTML(f'<a href="{upload_url}" target="_blank">Click here to review {folder_path} in a new tab.</a>')
        ],
        'missing': [
            HTML(f'<h3 style="margin: 0; color: blue;">Generated deployment metadata {file_name} for ArgosQC from local .mdb.</h3>'),
            HTML(f'<a href="{upload_url}" target="_blank">Click here to review or modify {folder_path} in a new tab.</a>')
        ]
    }
    check_file_exists(relative_path, file_name, html_messages, upload_url, True, True)
    absolute_meta_file = os.path.join(folder_path, file_name)
    deployments_for_argosqc_df.to_csv(absolute_meta_file, index=False)
    return absolute_meta_file, deployments_for_argosqc_df


def show_argosqc_results(qc_output_path:str, notebook_base_url:str, program:str, cid:str)->None:
    """
    Display ArgosQC results in a Jupyter notebook with a clickable link to the output folder.

    This function constructs a URL to the ArgosQC output directory for a specific
    program and project, and displays it as an HTML link in the notebook.

    Args:
        qc_output_path: Base path to the QC output directory (relative to notebook server)
        notebook_base_url: Base URL of the Jupyter notebook server (e.g., 'http://localhost:8888')
        program: Program name (e.g., 'vc08')
        cid: Project CID (e.g., '12345')
        show_if_exists: If True, only display the link if the output directory exists.
                       If False, display the link regardless.
        html: If True, display HTML formatted output. If False, print plain text.
        return_url: If True, return the URL string instead of displaying it.

    Returns: None
    """
    current_dir = os.path.dirname(__file__)
    upload_url = os.path.join(notebook_base_url, qc_output_path, program)
    relative_path = os.path.join(qc_output_path, program)
    folder_path = os.path.join(os.path.dirname(current_dir), relative_path)
    html_messages = {
        'found':  [
            HTML(f'<h3 style="margin: 0; color: blue;">ArgosQC results are found in {folder_path}.</h3>'),
            HTML(f'<a href="{upload_url}" target="_blank">Click here to review ArgosQC results in a new tab.</a>')
        ],
        'missing': [
            HTML(f'<h3 style="margin: 0; color: red;">No ArgosQC results found. Please review step 6 Run ArgosQC output or contact OTN data team.</h3>')
        ]
    }
    check_file_exists(relative_path, f'{program}_{cid}', html_messages, upload_url, True, False)
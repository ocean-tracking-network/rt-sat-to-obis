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
# WC API endpoint
WC_API_ENDPOINT = 'https://my.wildlifecomputers.com/services/'


def create_wc_qc_config(
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
    Create a configuration file for wc_qc with customizable parameters.

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


def wc_get_collab_ids(a_key: str = None, s_key: str = None, verbose: bool = False) -> pd.DataFrame:
    """
    Get collaborator IDs from Wildlife Computers API.
    :param a_key:  Wildlife Computers API Access Key
    :param a_key:  Wildlife Computers API Secret Key
    :param verbose:  print verbose output
    :return: a DataFrame containing collaborator information
    """

    # Input validation
    if a_key is None:
        raise ValueError("A valid wc.akey (Access Key) must be provided when downloading data from Wildlife Computers")
    if s_key is None:
        raise ValueError("A valid wc.skey (Secret Key) must be provided when downloading data from Wildlife Computers")
    url = WC_API_ENDPOINT

    # Generate hash (SHA256 of "action=get_collaborators" with secret key)
    message = "action=get_collaborators"
    hash_result = hmac.new(s_key.encode('utf-8'), message.encode('utf-8'), hashlib.sha256).hexdigest()

    if verbose:
        print(f"Generated hash: {hash_result}")

    # Prepare headers
    headers = {'X-Access': a_key, 'X-Hash': hash_result}

    # Prepare form data
    data = {'action': 'get_collaborators'}

    try:
        # Make the POST request
        response = requests.post(url, headers=headers, data=data)
        response.raise_for_status()  # Raise exception for bad status codes

        if verbose:
            print(f"Response status: {response.status_code}")
            print(f"Response content (first 500 chars): {response.text[:500]}")

        # Parse XML response
        root = ET.fromstring(response.content)

        # Extract collaborator data
        collaborators = []
        for collaborator in root.findall('.//collaborator'):
            collaborator_dict = {}
            for child in collaborator:
                collaborator_dict[child.tag] = child.text
            collaborators.append(collaborator_dict)

        # Convert to DataFrame
        if collaborators:
            collab_df = pd.DataFrame(collaborators)
        else:
            # Return empty DataFrame with appropriate structure
            collab_df = pd.DataFrame()
            if verbose:
                warnings.warn("No collaborators found in response")
        collab_list = [f"{email_val} - {id_val}" for id_val, email_val in zip(collab_df['id'], collab_df['email_address'])]

        radio_btn = RadioButtons(options=collab_list,
                                 layout={'width': '600px'},
                                 style={'description_width': 'initial'},
                                 value=None)

        itables.show(collab_df, buttons=['pageLength', "copyHtml5", "csvHtml5"])

        print('Select a collaborator to proceed')
        display(radio_btn)
        return collab_df, radio_btn

    except requests.exceptions.RequestException as e:
        raise Exception(f"API request failed: {e}")
    except ET.ParseError as e:
        raise Exception(f"Failed to parse XML response: {e}")
    except Exception as e:
        raise Exception(f"Unexpected error: {e}")

def sha256_hmac(message: str, key: str) -> str:
    """Return HMAC-SHA256 hex digest (WC API uses this)."""
    return hmac.new(
        key.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()


def parse_xml_nodes(xml_root, xpath):
    """Return list of dicts for XML nodes matching an XPath-like pattern."""
    nodes = xml_root.findall(xpath)
    result = []
    for node in nodes:
        record = {child.tag: child.text for child in node}
        result.append(record)
    return result


def posixtime(x):
    """Convert numeric POSIX string to UTC datetime."""
    if x is None:
        return None
    try:
        return datetime.utcfromtimestamp(float(x))
    except:
        return None


def flatten_dict(nested_dict: dict, parent_key='', separator='_')-> dict:
    """
    Recursively flatten a nested dictionary.

    Args:
        nested_dict: The dictionary to flatten
        parent_key: Used internally for recursion to track parent keys
        separator: The separator to use between nested keys

    Returns:
        A flattened dictionary with keys like 'parent_child_grandchild'
    """
    flattened = {}

    for key, value in nested_dict.items():
        # Create the new key
        new_key = f"{parent_key}{separator}{key}" if parent_key else key

        if isinstance(value, dict):
            # Recursively flatten nested dictionary
            flattened.update(flatten_dict(value, new_key, separator))
        else:
            # Add the key-value pair
            flattened[new_key] = value

    return flattened


def parse_xml_to_dict(response: str, element: str, verbose=False) -> dict[str,str]:
    """
    Parse specified element and sub-elements from XML response into dict.
    """
    data_dict = xmltodict.parse(response.content)
    flattened_dicts = []
    for element in data_dict.get('data', {}).get(element, {}):
        flattened_dict = flatten_dict(element)
        flattened_dicts.append(flattened_dict)
        if verbose:
            print(f'element_data: {element}')
            print(f'flattened_dict: {flattened_dict}')
    return flattened_dicts


def build_request_header(a_key: str, s_key: str, payload: str):
    """
    Build the header of API request
    """
    return {"X-Access": a_key, "X-Hash": sha256_hmac(payload, s_key)}


def unzip_file(extract_dest_path: Path) -> None:
    """
    Unzip files despite extraction error may occur
    Args:
        extract_dest_path: destination folder

    Returns: None
    """
    if extract_dest_path.exists():
        shutil.rmtree(extract_dest_path)
        print(f'Removed existing directory: {extract_dest_path}')

    try:
        with zipfile.ZipFile(Path(str(extract_dest_path) +'.zip'), 'r') as zip_ref:
            try:
                zip_ref.extractall(extract_dest_path)
                print(f'Successfully unzipped to: "{extract_dest_path}"')

                extracted_files = zip_ref.namelist()
                print(f'Extracted {len(extracted_files)} files')

            except zipfile.BadZipFile as e:
                print(f'Warning: Bad zip file - {e}. Continuing...')

                # Try to extract
                print('Attempting to extract valid files...')
                successful_files = 0
                for file_info in zip_ref.infolist():
                    try:
                        zip_ref.extract(file_info, extract_dest_path)
                        successful_files += 1
                    except RuntimeError as e1:
                        print(f'  Could not extract: {file_info.filename} - {e1}')
                print(
                    f'Partially extracted {successful_files} out of {len(zip_ref.namelist())} files')

    except Exception as e:
        print(f'Warning: Failed to process zip file - {e}')


def perform_download(a_key: str, s_key: str, tag_uuid_combobox: widgets.Dropdown = None,
                     deployment_df: pd.DataFrame = None, verbose=False, button: Button = None) -> Path:
    tag_uuid = tag_uuid_combobox.value
    payload = f"action=download_deployment&id={tag_uuid}"
    print(f'Downloading: {tag_uuid}...', sep=' ')
    response = requests.post(
        WC_API_ENDPOINT,
        headers=build_request_header(a_key, s_key, payload),
        data=payload
    )
    dest_path = Path(deployment_df[deployment_df['tag_uuid'] == tag_uuid]['owner'].iloc[0])
    dest_path.mkdir(parents=True, exist_ok=True)
    outfile = Path(os.path.join(dest_path, f"{tag_uuid}.zip"))
    outfile.write_bytes(response.content)
    print(f'Downloaded to: "{outfile}')

    unzip_file(dest_path / tag_uuid)
    return outfile


def get_deployments_for_owner_id(a_key: str, s_key: str, collaborator: str = None, verbose=False) -> pd.DataFrame:
    if not collaborator:
        print('Select a collaborator_id to proceed')
        return pd.DataFrame
    payload = f"action=get_deployments&owner_id={collaborator.split(' - ')[-1]}"
    response = requests.post(WC_API_ENDPOINT, data=payload, headers=build_request_header(a_key, s_key, payload))
    if verbose:
        print(response)
        print(response.text)
    # Parse deployment nodes
    flattened_dicts = parse_xml_to_dict(response, 'deployment')
    deployment_df = pd.DataFrame(flattened_dicts)

    rename_dict = {
        'id': 'tag_uuid',
        'argos_ptt_decimal': 'ptt',
        'argos_program_number': 'tag_program_number',
        'last_location_location_date': 'last_loc_date',
        'labels_category_name': 'label_name',
        'labels_category_label': 'label',
        'last_location_latitude': 'last_loc_lat',
        'last_location_longitude': 'last_loc_lon',
        'tag_tag_type': 'tag_type',
        'tag_serial_number': 'serial_number'
    }
    columns = [
        'tag_uuid', 'ptt', 'tag_program_number', 'status', 'tag_type', 'serial_number', 'last_update_date', 'label_name', 'label',
        'last_loc_date','last_loc_lat', 'last_loc_lon',
        'deploy_id','deployment_start_date', 'deployment_end_date',
        'deployment_start_latitude','argos_first_uplink_date', 'argos_last_uplink_date'
    ]
    deployment_df = deployment_df.rename(columns=rename_dict)
    # Convert epoch to datetime
    for col in [col for col in deployment_df.columns if col.endswith('_date')]:
        # Convert integer timestamps to UTC datetime
        deployment_df[col] = pd.to_datetime(deployment_df[col], unit='s', utc=True)
    print(f'Showing {len(deployment_df)} tag(s) for collaborator: {collaborator}')
    itables.show(deployment_df[columns], buttons=['pageLength', "copyHtml5", "csvHtml5"])
    return deployment_df


def download_tag(a_key: str, s_key: str, deployment_df: pd.DataFrame, verbose=False):
    tag_uuid_combobox = build_combobox(deployment_df['tag_uuid'].tolist())
    download_button = Button(description="Download", button_style='primary')
    display(tag_uuid_combobox, download_button)
    download_button.on_click(partial(perform_download, a_key, s_key, tag_uuid_combobox, deployment_df, verbose))


def build_combobox(option_lst: list[str]) -> widgets.Combobox :
    return widgets.Combobox(
        options=option_lst,
        placeholder='Tag UUID',
        disabled=False,
    )


def export_for_kepler(collaborator: str, deployment_df: pd.DataFrame) -> None:
    """
    Export animal tracking data to a format compatible with Kepler.gl visualization.

    This function processes and exports telemetry/tracking data for use in Kepler.gl,
    an open-source geospatial data visualization tool. The exported file can be
    directly loaded into Kepler.gl for interactive mapping and temporal analysis.

    Args:
        collaborator (str): selected collaborator
        deployment_df (pd.DataFrame): DataFrame containing tag location data
    Returns: None
    """
    if not collaborator:
        print('Select a collaborator_id to proceed')
        return pd.DataFrame

    filename = f"{collaborator.split('@')[0]}_latest_{datetime.now().strftime('%Y%m%d')}.csv"
    latest_loc_df = deployment_df[['tag_uuid', 'last_update_date', 'last_loc_lat', 'last_loc_lon']].copy().rename(columns={
        'last_loc_lat': 'latitude',
        'last_loc_lon': 'longitude'
    })
    itables.options.maxBytes = 0
    itables.show(latest_loc_df,
                 buttons=[
                    'copy',
                    {
                        'extend': 'csv',
                        'filename': filename.replace('.csv', '')
                    },
                    {
                        'extend': 'excel',
                        'filename': filename.replace('.csv', ''),
                        'exportOptions': {
                            'modifier': {
                                'page': 'all'
                            }
                        }
                    }
                ])
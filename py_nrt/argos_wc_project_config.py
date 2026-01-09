import binascii
import hashlib
import json
import os
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
        dest_path: Path = None,
        a_key: str = None,
        s_key: str = None,
        owner_id: str = None,
        time_step: int = 3,
        program: str=None,
        project_id: str =None,
        common_name: str = None,
        species: str = None,
        release_site: str = None,
        state_country: str = None
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
                "data.dir": "data",
                "meta.file": None,
                "maps.dir": f"output/maps/{project_id}",
                "diag.dir": f"output/diag/{project_id}",
                "output.dir": f"output/{program}/{project_id}",
                "return.R": True
            },
            "harvest": {
                "download": False,
                "owner.id": owner_id,
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
    output_path = os.path.join(dest_path, f'{program}_{project_id}.json')
    with open(output_path, 'w') as f:
        json.dump(wc_qc_config, f, indent=2, ensure_ascii=False)
    print(f'Wrote wc_qc config file to {output_path}.')


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
        radio_btn = RadioButtons(options=collab_df['id'].to_list(), value=None)

        itables.show(collab_df)
        print('Select a collaborator_id to proceed')
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


def perform_download(a_key: str, s_key: str, tag_uuid_dropdown: widgets.Dropdown = None, dest_path: Path = None, verbose=False, button: Button=None) -> Path:
    tag_uuid = tag_uuid_dropdown.value
    payload = f"action=download_deployment&id={tag_uuid}"
    print(f'Downloading :{tag_uuid}...', sep=' ')
    response = requests.post(
        WC_API_ENDPOINT,
        headers=build_request_header(a_key, s_key, payload),
        data=payload
    )
    dest_path.mkdir(parents=True, exist_ok=True)
    outfile = Path(os.path.join(dest_path, f"{tag_uuid}.zip"))
    outfile.write_bytes(response.content)
    print('Done')
    return outfile


def get_deployments_for_owner_id(a_key: str, s_key: str, owner_id: str = None, verbose=False) -> pd.DataFrame:
    if not owner_id:
        print('Select a collaborator_id to proceed')
        return pd.DataFrame
    payload = f"action=get_deployments&owner_id={owner_id}"
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
        'argos_program_number': 'sattag_program',
        'last_location_location_date': 'last_loc_date',
        'last_location_latitude': 'last_loc_lat',
        'last_location_longitude': 'last_loc_lon'
    }
    columns = [
        'tag_uuid', 'ptt', 'sattag_program', 'status', 'last_update_date',
        'last_loc_date','last_loc_lat', 'last_loc_lon',
        'deploy_id','deployment_start_date', 'deployment_end_date',
        'deployment_start_latitude','argos_first_uplink_date', 'argos_last_uplink_date'
    ]
    deployment_df = deployment_df.rename(columns=rename_dict)
    # Convert epoch to datetime
    for col in [col for col in deployment_df.columns if col.endswith('_date')]:
        # Convert integer timestamps to UTC datetime
        deployment_df[col] = pd.to_datetime(deployment_df[col], unit='s', utc=True)

    itables.show(deployment_df[columns])
    return deployment_df


def download_tag(a_key: str, s_key: str, deployment_df: pd.DataFrame, dest_path: str, verbose=False):
    tag_uuid_dropdown = build_drop_down(deployment_df['tag_uuid'].tolist())
    download_button = Button(description="Download", button_style='primary')
    display(tag_uuid_dropdown, download_button)
    download_button.on_click(partial(perform_download, a_key, s_key, tag_uuid_dropdown, Path(dest_path), verbose))



def build_drop_down(option_lst: list[str]) -> widgets.Dropdown :
    return widgets.Dropdown(
        options=option_lst,
        description='Select UUID',
        disabled=False,
    )

def wc_get_files(dest: str, a_key: str, s_key: str, owner_id: str = None, subset_ids: str = None, collaborator: bool = True,
                 unzip_files: bool = True, verbose: bool = False, download: bool = True, return_tag_meta: bool = False):
    """
    Download files from Wildlife Computers API.

    :param dest: Destination directory to save downloaded files
    :param a_key: Wildlife Computers API Access Key
    :param s_key: Wildlife Computers API Secret Key
    :param owner_id: Owner ID to filter files by (optional)
    :param subset_ids: Comma-separated subset IDs to download specific files (optional)
    :param collaborator: Whether to include collaborator data (default: True)
    :param unzip_files: Whether to automatically unzip downloaded files (default: True)
    :param verbose: Print verbose output during operation (default: False)
    :param download: Whether to download files or just list them (default: True)
    :param return_tag_meta: Whether to return tag metadata along with file info (default: False)
    :return: DataFrame containing file information and optionally tag metadata
    """

    if a_key is None:
        raise ValueError("wc.access.key must be provided")

    if s_key is None:
        raise ValueError("wc.secret.key must be provided")

    if owner_id is None and not collaborator:
        raise ValueError("Either owner_id must be provided OR collaborator=True")

    base_url = WC_API_ENDPOINT
    # Get collaborator
    if owner_id is None and collaborator:
        ids_df = wc_get_collab_ids(a_key, s_key, verbose)

        # Get deployments for each collaborator ID
        deps_list = []
        for _, row in ids_df.iterrows():
            mid = row["id"]
            msg = f"action=get_deployments&owner_id={mid}"
            digest = sha256_hmac(msg, s_key)

            r = requests.post(
                base_url,
                headers={"X-Access": a_key, "X-Hash": digest},
                data=msg
            )
            root = ET.fromstring(r.text)
            dep = parse_xml_nodes(root, ".//deployment")

            df = pd.DataFrame(dep)
            if not df.empty:
                df = df[["id", "owner", "status", "tag", "last_update_date"]]
                deps_list.append(df)

        deps = pd.concat(deps_list, ignore_index=True)
        deps["last_update_date"] = deps["last_update_date"].apply(posixtime)
        print(f'deps: ')
        itables.show(deps)

    #################################################
    # 2. OWNER-ID MODE
    #################################################
    else:
        msg = f"action=get_deployments&owner_id={owner_id}"
        digest = sha256_hmac(msg, s_key)

        r = requests.post(
            base_url,
            headers={"X-Access": a_key, "X-Hash": digest},
            data=msg
        )
        root = ET.fromstring(r.text)

        # Parse deployment nodes
        deps = pd.DataFrame(parse_xml_nodes(root, ".//deployment"))

        # Required fields only
        keep = [
            "id", "owner", "status", "tag", "argos",
            "deployment", "last_update_date", "last_location",
            "first_uplink_date", "last_uplink_date"
        ]
        deps = deps[[c for c in keep if c in deps.columns]]

        # Convert numeric POSIX timestamps
        for col in ["last_update_date", "first_uplink_date", "last_uplink_date"]:
            if col in deps.columns:
                deps[col] = deps[col].apply(posixtime)

        # ARGOS tag info
        argos = pd.DataFrame(parse_xml_nodes(root, ".//argos"))
        argos = argos.rename(columns={
            "program_number": "sattag_program",
            "ptt_decimal": "ptt"
        })

        # LAST LOCATION
        last_loc = pd.DataFrame(parse_xml_nodes(root, ".//last_location"))
        last_loc = last_loc.rename(columns={
            "location_date": "last_loc_date",
            "longitude": "last_loc_lon",
            "latitude": "last_loc_lat"
        })
        last_loc["last_loc_date"] = last_loc["last_loc_date"].apply(posixtime)

        deps = pd.concat([deps, argos, last_loc], axis=1)

        # DEPLOY start node
        deploy = pd.DataFrame(parse_xml_nodes(root, ".//start"))
        print(deploy.columns)
        deploy.columns = ["deploy_date", "deploy_lat", "deploy_lon"]
        deploy["deploy_date"] = deploy["deploy_date"].apply(posixtime)

        # Join by row order (same as R)
        deploy["id"] = deps["id"]
        deps = deps.merge(deploy, on="id", how="left")

        #################################################
        # Subset by UUID list (if provided)
        #################################################
        if subset_ids:
            uuid_df = pd.read_csv(subset_ids)
            if list(uuid_df.columns) != ["uuid"]:
                raise ValueError("subset.ids CSV must contain a single column named 'uuid'")

            deps = deps[deps["id"].isin(uuid_df["uuid"])]

        #################################################
        # Duplicate PTT check
        #################################################
        if deps["ptt"].duplicated().any():
            deps.to_csv("QC_logfile.csv", index=False)
            raise RuntimeError(
                "Duplicate PTT detected. Metadata written to QC_logfile.csv. "
                "Add UUIDs to QC list and retry."
            )

    #################################################
    # 3. DOWNLOAD ZIPFILES
    #################################################
    dest_path = Path(dest)
    print(dest)
    dest_path.mkdir(parents=True, exist_ok=True)
    if download:
        for _, row in deps.iterrows():
            uuid = row["id"]
            tagid = str(row.get("tag", "tag")).replace('\n', '_n')
            print(f'tagid:{tagid}')
#             if pd.isna(tagid) or (isinstance(tagid, str) and tagid.strip() == ""):
#                 continue

            msg = f"action=download_deployment&id={uuid}"
            digest = sha256_hmac(msg, s_key)

            outfile = dest_path / f"{uuid}_{tagid}.zip"
            print(f'writing to {outfile}...')

            r = requests.post(
                base_url,
                headers={"X-Access": a_key, "X-Hash": digest},
                data=msg
            )

            # Write ZIP
            outfile.write_bytes(r.content)

            if unzip_files:
                with zipfile.ZipFile(outfile, "r") as z:
                    extract_path = outfile.with_suffix("")
                    z.extractall(extract_path)

                outfile.unlink()  # delete zip

    #################################################
    # Return tag metadata if requested
    #################################################
    if return_tag_meta:
        return deps

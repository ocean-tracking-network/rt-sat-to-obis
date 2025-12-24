import binascii
import hashlib
import os
import typing
from collections import defaultdict
from datetime import datetime, date
from itertools import product
from typing import List, Tuple

import numpy as np
import pandas as pd
import plotly
import requests
from ipywidgets import Layout, Checkbox, VBox, Label, Box, Button, widgets, HTML
from IPython.display import display
from shapely import wkb

from sqlalchemy.engine import Engine
import itables
import re
import hmac
import hashlib
import requests
import pandas as pd
from xml.etree import ElementTree as ET
import warnings

itables.init_notebook_mode()
# WC API endpoint
WC_API_ENDPOINT = 'https://my.wildlifecomputers.com/services/'


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

        return collab_df

    except requests.exceptions.RequestException as e:
        raise Exception(f"API request failed: {e}")
    except ET.ParseError as e:
        raise Exception(f"Failed to parse XML response: {e}")
    except Exception as e:
        raise Exception(f"Unexpected error: {e}")

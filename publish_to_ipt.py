import requests
import os
from requests_toolbelt.multipart.encoder import MultipartEncoder
from bs4 import BeautifulSoup

# Need to port this to a standalone package - other places to tuck it have too many dependencies.

# TODO: extend this to allow checking for different versions of the IPT as the forms may change?
# Functional for IPT 2.6.3


def open_ipt_session(ipt_auth, ipt_url):
    """
    Begin a session with the target IPT
    Author: Jon Pye
    :param ipt_auth: Authentication details for the ipt, of the form {'email': 'email@mailserver.com', 'password':'cleartextPassword'}
    :param ipt_url: URL of the IPT we are authenticating with.
    :return: None
    """
    
    # relative path to IPT login form
    login_url = ipt_url + 'login.do'
    
    s = requests.Session()  # open a session
    
    # retrieve the login form
    resp = s.get(login_url)
    
    # login forms generate a CSRF token that we have to persist in our response  
    soup = BeautifulSoup(resp.text, 'lxml')
    
    # Add it to our credentials dictionary
    ipt_auth['csrfToken'] = soup.find("input", {"name": "csrfToken"})['value']
    login = s.post(login_url, data=ipt_auth)
    
    if login.status_code != 200:
        print("Login failed, status code {}".format(login.status_code))
        print(login.text)
        return None
    else:
        return s


def create_new_ipt_project(projname: str, filepath: str, ipt_url: str, ipt_session):
    
    """
    Create a new project on the given IPT using an existing DwC archive zip
    Author: Jon Pye
    :param projname: the project name as given by get_obis_shortname()
    :param filepath: payload resource filepath
    :param ipt_url: URL of the IPT to publish to
    :param ipt_session: authenticated requests session for the IPT
    :return: URL of the resource
    """
    
    path, filename = os.path.split(filepath)
    
    if not filename:  # if the filepath has no name in it
        print('no file specified in filepath, aborting')
        return None
    else:
        print(path, filename)
        print(filepath)
    
    # if there IS a file and it is not a valid DwC Archive, do we want to do anything here? The IPT runs its own checks...
    
    values = MultipartEncoder(fields={'create': 'Create',  # hidden form fields with values
                                      'shortname': projname,
                                      'resourceType': 'samplingevent',
                                      '__checkbox_importDwca': 'true',
                                      'importDwca': 'true',
                                      'file': (filename, 
                                               open(filepath, 'rb'),
                                               'application/x-zip-compressed'),
                                     }
                             )
    create_dataset = ipt_session.post(ipt_url + 'manage/create.do',
                                      data=values,
                                      headers={'Content-Type': values.content_type}
                                     )
    return create_dataset

    
def refresh_ipt_project_files(projname: str, filepath: str, ipt_url: str, ipt_session):
    """
    Update data for a project on the given IPT using an existing DwC archive zip
    Author: Jon Pye
    :param projname: the project name as given by get_obis_shortname()
    :param filepath: payload resource filepath
    :param ipt_url: URL of the IPT to publish to
    :param ipt_session: authenticated requests session for the IPT
    :return: URL of the resource
    """
    
    path, filename = os.path.split(filepath)
    
    if not filename:  # if the filepath has no name in it
        print('no file specified in filepath, aborting')
        return None
    
    values = MultipartEncoder(fields={  'add': 'Add',
                                        'r': projname,
                                        'sourceType': 'source-file',
                                        'validate': 'false', 
                                        'file': (filename,
                                                 open(filepath, 'rb'),
                                                 'application/x-zip-compressed'),
                                     })
    
    update_dataset = ipt_session.post(ipt_url + 'manage/addsource.do',
                                      data=values, 
                                      headers = {'Content-Type': values.content_type}
                                     )
    if update_dataset.status_code == 200:
        # Handle the Are you Sure popup.        
        print("Publication successful")
        return update_dataset
    else:
        print("publication error, check landing page output")
        return update_dataset


def refresh_ipt_project_metadata(projname: str, filepath: str, ipt_url: str, ipt_session):
    """
    Update metadata for a project on the given IPT using an existing eml.xml file
    Author: Jon Pye
    :param projname: the project name as given by get_obis_shortname()
    :param filepath: payload resource filepath
    :param ipt_url: URL of the IPT to publish to
    :param ipt_session: authenticated requests session for the IPT
    :return: URL of the resource
    """
    
    path, filename = os.path.split(filepath)
    
    if not filename:  # if the filepath has no name in it
        print('no file specified in filepath, aborting')
        return None
    
    values = MultipartEncoder(fields={  'emlReplace': 'Replace',
                                        'r': projname,
                                        'sourceType': 'source-file',
                                        'validateEml': 'true',
                                        '__checkbox_validateEml': 'true',
                                        'emlFile': (filename,
                                                    open(filepath, 'rb'),
                                                    'application/xml'),
                                     })

    update_metadata = ipt_session.post(ipt_url + 'manage/replace-eml.do',
                                       data=values, 
                                       headers = {'Content-Type':values.content_type}
                                      )
    return update_metadata


def make_public_ipt_project(projname: str, ipt_url: str, ipt_session):
    """
    Update metadata for a project on the given IPT
    Author: Jon Pye
    :param projname: the project name as given by get_obis_shortname()
    :param ipt_url: URL of the IPT to publish to
    :param ipt_session: authenticated requests session for the IPT
    :return: URL of the resource
    """
    pub_params = {'r' : projname,          # resource = dataset name
                  'makePrivate': 'Public'
                 }
    
    contents = ipt_session.post(ipt_url + 'manage/resource-makePublic.do', data = pub_params)
    return contents

def change_publishing_org_ipt_project(projname: str, ipt_url: str, ipt_session, new_publishing_org_name: str):
    """
    Update metadata for a project on the given IPT. Note - only works for IPT 3.x+
    Author: Mathew Biddle
    :param projname: the project name as given by get_obis_shortname()
    :param ipt_url: URL of the IPT to publish to
    :param ipt_session: authenticated requests session for the IPT
    :param new_publishing_org: the new publishing organisation ID. See publishingOrganizationKey in the IPT source.

    :return: URL of the resource
    """
    # set your publishing organization name to key value pair in this dictionary
    pub_orgs = {
                 'No organisation': "625a5522-1886-4998-be46-52c66dd566c9",
                 'Ocean Tracking Network':"6772852d-ca2e-496f-9bea-dcf86134cb19",
                 'NOAA Integrated Ocean Observing System': "1d38bb22-cbea-4845-8b0c-f62551076080",
                }

    if new_publishing_org_name not in pub_orgs:
        print(f"Publishing organisation '{new_publishing_org_name}' not recognised as one of {pub_orgs.keys()}. Please check the name and try again.")
        return None

    pub_params = {'r' : projname,          # resource = dataset name
                  'publishingOrganizationKey': pub_orgs[new_publishing_org_name],
                 }
    
    contents = ipt_session.post(ipt_url + 'manage/resource-changePublishingOrganization.do', data = pub_params)
    return contents

def add_obis_network_ipt_project(projname: str, ipt_url: str, ipt_session):
    """
    Add the OBIS network to the given IPT project
    Author: Mathew Biddle
    :param projname: the project name as given by get_obis_shortname()
    :param ipt_url: URL of the IPT to publish to
    :param ipt_session: authenticated requests session for the IPT

    :return: URL of the resource
    """
    pub_params = {
            "r": projname, 
            "id": "2b7c7b4f-4d4f-40d3-94de-c28b6fa054a6", #"2b7c7b4f-4d4f-40d3-94de-c28b6fa054a6", # "Ocean Biodiversity Information System (OBIS)"
        }
    contents = ipt_session.post(
        ipt_url + "manage/resource-addNetwork.do", data=pub_params
    )
    
    return contents

def register_ipt_project(projname: str, ipt_url: str, ipt_session):
    """
    Update Register the given IPT project with GBIF. Note - only works for IPT 3.x+
    Author: Mathew Biddle
    :param projname: the project name as given by get_obis_shortname()
    :param ipt_url: URL of the IPT to publish to
    :param ipt_session: authenticated requests session for the IPT

    Need to do the following in the dialog-confirm. 
       * check checkbox-confirm
       * select yes-button

    :return: URL of the resource
    """

    pub_params = {'r' : projname,          # resource = dataset name
                  'checkbox-confirm': 'true',  # checkbox-confirm
                  'yes-button': 'Yes',
                 }
    
    contents = ipt_session.post(ipt_url + 'manage/resource-registerResource.do', data = pub_params)
    return contents

def publish_ipt_project(projname: str, ipt_url: str, ipt_session, publishing_notes: str = ""):
    """
    Update metadata for a project on the given IPT
    Author: Jon Pye
    :param projname: the project name as given by get_obis_shortname()
    :param ipt_url: URL of the IPT to publish to
    :param ipt_session: authenticated requests session for the IPT
    :param publishing_notes: optional message to publish this version with
    :return: URL of the resource
    """
    
    pub_params = {'r' : projname,      # resource = dataset name
                  'autopublish': '',
                  'currPubMode' : 'AUTO_PUBLISH_OFF',
                  'pubMode': '',
                  'currPubFreq': '',
                  'pubFreq': '',
                  'publish': 'Publish',
                  'summary': publishing_notes
             }
    contents = ipt_session.post(ipt_url + 'manage/publish.do', data = pub_params)
    return contents

def check_if_project_exists(projname: str, ipt_url: str, ipt_session):
    """
    Test if a project exists on the IPT already
    Author: Jon Pye
    :param projname: the project name as given by get_obis_shortname()
    :param ipt_url: URL of the IPT to check for this publication
    :param ipt_session: authenticated requests session for the IPT
    :return: True if the project already exists on the IPT in question
    """

    checkUrl = '{ipt_url}ipt/resource?r={projname}'.format(ipt_url=ipt_url, projname=projname)

    contents = ipt_session.post(checkUrl)

    # if it's not found, the IPT returns a 404
    if contents.status_code == 404:
        print("No existing repository by this name: '{}'".format(projname))
        return False
    elif contents.status_code == 200:
        print("Found existing project by name: '{}'".format(projname))
        return True

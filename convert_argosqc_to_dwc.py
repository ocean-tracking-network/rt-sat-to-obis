import pandas as pd
import pyworms
import pprint
from pathlib import Path
import os
import json
import ast
import publish_to_ipt as pub
from jinja2 import Template
from datetime import datetime
import sys

# We will eventually only need one of the following file-zipping functions. I think it's the zipfile-based one
# but it might end up being the shutils based one.

SCRIPT_PATH = Path(os.path.dirname(os.path.realpath(__file__)))

def zip_files(folder_path:str, file_list:list) -> str:
    """
    Old method of zipping files for Darwin Core archive
    Removes the relative paths from the files so that the IPT doesn't get confused.
    Create .zip file from list of files passed
    Author: Jon Pye
    Maintainer: Jon Pye
    :param obis_shortname: OBIS shortname of project
    :param file_list: List of files to include in the zip
    :return: path to the zipped files you provided. Not guaranteed to be a DwC Archive.
    """
     #
    import zipfile

    # if they mess up and pass you a file, name the zip after the folder it's in anyway.
    zip_name = folder_path.parent.name if not folder_path.is_dir() else folder_path.name

    with zipfile.ZipFile(folder_path/ f'{zip_name}_rt.zip', 'w', zipfile.ZIP_DEFLATED) as zip:
        # Add each file to the ZIP
        for f in file_list:
            zip.write(f, arcname=f.name)
            print(f'Zipped file {f}')

    return folder_path / f'{zip_name}_rt.zip'

def make_pyworms_lookup_table(species_list:pd.Series = None) -> pd.DataFrame:
    lookup_dict = {}
    
    for name in species_list.unique():
        if type(name) == str:
            resp = pyworms.aphiaRecordsByMatchNames(name)
            # TODO - handle errors better now that we're not in a notebook
            if len(resp[0]) == 0:
                print('\nNo match for name "{}"'.format(name))
                continue
            elif len(resp[0]) > 1:
                print('\nMultiple matches for name "{}"'.format(name))
                pprint.pprint(resp[0], indent=4)
                continue
            else:
                worms = resp[0][0]
                lookup_dict[name]={'scientificName': name,
                                'scientificNameID': worms['lsid'],
                                'taxonRank': worms['rank'],
                                'kingdom': worms['kingdom'],
                                'phylum': worms['phylum'],
                                'class': worms['class'],
                                'order': worms['order'],
                                'family': worms['family']}
        
    return pd.DataFrame.from_dict(lookup_dict, orient='index')


def make_dwc_from_argosqc_output(output_dir:Path=None, cid:str=None, config_file:Path=None):
    """
    :str output_dir: full path string to where ArgosQC puts its output
    :str cid: string indicating the campaign ID (the substring in each of the output files from ArgosQC)
    """

    if output_dir is None or cid is None:
        print('missing arguments, aborting')
        return None

    if config_file is None:
        config_file = SCRIPT_PATH / 'input' / f'imos_{cid}' / f'config_{cid}.json'

    # argosQC makes a metadata_ file and a modified diag file available in its output.dir
    metadata_df = pd.read_csv(Path(f'{output_dir}/metadata_{cid}_nrt.csv'), dtype={'body': str})
    loc_df = pd.read_csv(Path(f'{output_dir}/diag_{cid}_nrt.csv'))


    # Create tagging Events from metadata dataframe:

    # mapping columns to Darwin Core directly from metadata_df:
    column_map = {'release_date':'eventDate',
                    'release_latitude':'decimalLatitude',
                    'release_longitude':'decimalLongitude',
                    'state_country':'country'}
        
    event_df = metadata_df.rename(columns=column_map)
    event_df['modified'] = pd.to_datetime('now', utc=True).round(freq='s')

    # SMRU-specific:
    # Event IDs are instrument serial number (body) + release_date (eventDate)
    event_df['eventID'] = event_df['body'].astype(str).str.cat(event_df['eventDate'].astype(str), sep='-')
    event_df['geodeticDatum'] = 'EPSG:4326'

    event_df = event_df[['eventID', 'eventDate', 'decimalLatitude', 'decimalLongitude', 'modified', 'geodeticDatum', 'country']]

    # end tagging Events

    # Create tagging Occurrences from metadata dataframe:

    occ_column_map = {'release_date':'eventDate',
                        'species':'scientificName'}
    occ_df = metadata_df.rename(columns=occ_column_map)

    # organismID, occurrenceID and eventID are both also body + eventDate by default. 
    # Left separate so we could override with user preference or extension of the conversion script

    occ_df['occurrenceID'] = occ_df['body'].astype(str).str.cat(occ_df['eventDate'].astype(str), sep='-')
    occ_df['eventID'] = occ_df['body'].astype(str).str.cat(occ_df['eventDate'].astype(str), sep='-')
    occ_df['organismID'] = occ_df['body'].astype(str).str.cat(occ_df['eventDate'].astype(str), sep='-')
    occ_df['basisOfRecord'] = 'HumanObservation'
    occ_df = occ_df[['occurrenceID', 'organismID','eventID', 'sex', 'scientificName', 'basisOfRecord']]

    # end tagging Occurrences

    # create Events from the location datafile

    # add the relevant columns to loc_df from metadata_df to be able to create organismID
    # if there are any tag IDs that we don't have any metadata for, we don't want to publish
    # them to OBIS. So inner joining is best for OBIS publication
    # Publishing enviro data - we maybe don't mind not knowing species - don't do this for enviro

    loc_df = loc_df.merge(metadata_df[['device_id', 'body', 'release_date', 'species']], 
                      how='inner', left_on='ref', right_on='device_id') 

    # combine the organismID + the detection date into the eventID
    loc_df['eventID'] = loc_df['body'].astype(str).str.cat(loc_df[['release_date', 'd_date']], sep='-')

    # where there has been no correction made (corrected positions = NA, 
    #       then use the raw position data
    loc_df['decimalLatitude'] = loc_df['ssm_lat'].fillna(loc_df['lat'])
    loc_df['decimalLongitude'] = loc_df['ssm_lon'].fillna(loc_df['lon'])
    loc_df['eventDate'] = loc_df['d_date']
    loc_df['modified'] = pd.to_datetime('now', utc=True).round(freq='s') 

    # constant
    loc_df['geodeticDatum'] = 'EPSG:4326'

    # ArgosQC calculates ssm_x and ssm_y in km, not in m
    loc_df['coordinateUncertaintyInMeters'] = loc_df[['ssm_x_se', 'ssm_y_se']].max(axis=1) * 1000

    # TODO: revisit uncertainty - make a radius based on the max, but uncertainty is an ellipse
    # OBIS doesn't know about it but we can make a Polygon and include it somewhere to preserve the better
    # knowledge that we have.

    # Where there are multiple hits for a given time step (many satellites have opinions on position at once), 

    loc_df = loc_df.sort_values(['ref', 'd_date', 'lq'], ascending=False)
    # drop all but the best of the location qualities
    loc_df = loc_df.drop_duplicates(subset=['ref','d_date'], keep='first', inplace=False)

    error_table = {3:490,
               2:1010,
               1:1200,
               0:4180,
               -1:6190,
               -2:10280,
               -9:10280} # TODO : What is the corresponding code to -9 LQ? 
                         # argosQC thinks it's a class B
    missing_errors = loc_df['coordinateUncertaintyInMeters'].isna()
    loc_df.loc[missing_errors, 'coordinateUncertaintyInMeters'] = loc_df.loc[missing_errors, 'lq'].map(error_table)

    # end events from location data

    # combine both event sources into event_df
    event_df = pd.concat([event_df, loc_df[['eventID', 'eventDate', 'decimalLatitude', 'decimalLongitude', 'modified','geodeticDatum', 'coordinateUncertaintyInMeters']]])

    # Create Occurrences from location data

    loc_df['occurrenceID'] = loc_df['eventID'].astype(str)
    loc_df['organismID'] =  loc_df['body'].astype(str).str.cat(loc_df['release_date'].astype(str), sep='-')

    # Decimate to first each hour per animal. Acoustics would also use per-receiver location, argos and sat won't need that.
    dets_df = loc_df
    dets_df['scientificName'] = dets_df['species']
    dets_df['basisOfRecord'] = 'MachineObservation'
    dets_df['Date'] = pd.to_datetime(dets_df['d_date']).dt.date
    dets_df['hr'] = pd.to_datetime(dets_df['d_date']).dt.hour
    dets_df['binsize'] = dets_df.groupby(['organismID', 'Date', 'hr']).size().reset_index(name='binsize')['binsize']
    dets_df.drop_duplicates(subset=['organismID','Date', 'hr'], keep='first', inplace=True)
    dets_df.drop('hr', axis=1, inplace=True)
    dets_df['dataGeneralizations'] = dets_df['binsize'].apply(lambda x: 'subsampled by hour, first of {} record(s)'.format(x))

    # end Create Occurrences from location data

    # combine both sources of Occurrences
    occ_df = pd.concat([occ_df, dets_df[['occurrenceID', 'eventID', 'scientificName', 'organismID', 'basisOfRecord']]])


    # get taxonomic information to add:
    lookup_df = make_pyworms_lookup_table(occ_df['scientificName'])

    occ_df = occ_df.join(lookup_df, how='left', on='scientificName', rsuffix='_worms')


    # TODO: add emof functionality, will need a switch per instrument type
    emof_df = pd.DataFrame()

    # Create emofs from biology


    # Create emofs from environmental instruments


    # Save Events and occurrences to csv.

    # ensure there is an output folder for this project.
    # Paths are relative to this executable by default, but let's be explicit:

    Path(f'output/{cid}').mkdir(parents=True, exist_ok=True)

    # create and include the meta.xml and eml.xml
    # set the meta.xml paramaters by hand, using the format of the dataframes above

    event_leading_cols=['id']
    occ_leading_cols=['id']


    # Add id columns to the 3 data types

    event_df['id'] = event_df['eventID']
    occ_df['id'] = occ_df['occurrenceID']
    meta_xml_vars = {}
    event_df = event_df[event_leading_cols + (event_df).columns.drop(event_leading_cols).tolist()]

    occ_df = occ_df[occ_leading_cols + (occ_df).columns.drop(occ_leading_cols).tolist()]

    # setup filepaths and naming for the meta.xml
    occ_filepath = Path('output') / f'{cid}'/ 'occurrences.csv'
    meta_xml_vars['occurrence_filename'] = occ_filepath.name
    occ_df.to_csv(occ_filepath, date_format='%Y-%m-%dT%H:%M:%S', index=False)

    event_filepath = Path('output') / f'{cid}' /'events.csv'
    meta_xml_vars['event_filename'] = event_filepath.name
    event_df.to_csv(event_filepath, date_format='%Y-%m-%dT%H:%M:%S', index=False)


    
    meta_xml_vars['event_cols_list'] = (event_df).columns.drop(event_leading_cols).tolist()
 
    meta_xml_vars['cols_list'] = (occ_df).columns.drop(occ_leading_cols).tolist()

    if not emof_df.empty:
        emof_df['id'] = emof_df['eventID']
        emof_leading_cols=['id', 'eventID']
        emof_filepath = Path('output') / f'{cid}' / 'emof.csv'
        emof_df = emof_df[emof_leading_cols + (emof_df).columns.drop(emof_leading_cols).tolist()]
        emof_df.to_csv(emof_filepath, date_format='%Y-%m-%dT%H:%M:%S')

        meta_xml_vars ['emof_cols_list'] = (emof_df).columns.drop(emof_leading_cols).tolist()
        meta_xml_vars['emof_filename'] = Path('output') / f'{cid}' / 'emofs.csv'

    # grab the template file for making meta.xml
    meta_template_file = open(Path(SCRIPT_PATH) / 'templates' / 'event_meta.xml.j2', mode='r', encoding='UTF-8').read()
    meta_template = Template(meta_template_file)
    meta_result_string = meta_template.render(meta_xml_vars)
    meta_file = Path('output') / f'{cid}' / 'meta.xml'
    fh = open(meta_file, mode='w+', encoding='UTF-8')
    fh.write(meta_result_string)
    fh.close()

    # eml.xml
    eml_file = generate_campaign_eml_from_template(config_file, cid)

    # Add everything we just made to the zipfile
    print("Creating fileset for DwC archive from the following files:")
    if not emof_df.empty:
        dwc_archive = zip_files(Path('output')/ f'{cid}',  # Folder name
                            [   meta_file.resolve(), # meta.xml
                                eml_file.resolve(),   # eml.xml
                                event_filepath.resolve(),
                                occ_filepath.resolve(),
                                emof_filepath.resolve()
                            ])
    else:
        dwc_archive = zip_files(Path('output') / f'{cid}',  # Folder name
                [   meta_file.resolve(), # meta.xml
                    eml_file.resolve(),   # eml.xml
                    event_filepath.resolve(),
                    occ_filepath.resolve()
                ])


    # return the dataframes if people are expecting to review the data
    return occ_df, event_df # , emof_df


def generate_campaign_eml_from_template(config_file:Path=None, cid:str= None):
    """
    :str config_file: full path string to the ArgosQC config file, containing metadata and the template to use
    :str cid: The campaign ID string
    """

    # What we need:
    # Config file must have links to which project template to use -> setup.meta.project_meta_template
    # Config file must have links to contact csv > setup.meta.contacts_file

    # read the config file

    with open(config_file, 'r') as campaign_config:
        config_dict = json.load(campaign_config)
        # config file is a list of dicts:
        config = config_dict[0] # so take the first entry
        
        print(Path(SCRIPT_PATH) / 'templates' / 'eml.xml.j2')

        if 'project_meta_template' in config['meta'].keys():    # TODO: what's our error response?
            template = Path(SCRIPT_PATH) / 'templates' / config['meta']['project_meta_template']
        else:
            template = Path(SCRIPT_PATH) / 'templates' / 'eml.xml.j2'
        
        # allow config files to override IPT naming
        if 'ipt_resource_id' in config['meta'].keys():
            r = config['meta']['ipt_resource_id']

        if 'contacts_file' in config['meta'].keys():            # TODO: what's our error response?
            contacts = Path(SCRIPT_PATH) / 'input' / 'contacts' / config['meta']['contacts_file']

        eml_file = Path(SCRIPT_PATH) / 'output' / f'{cid}' / 'eml.xml'

        template_file = open(template, mode='r', encoding='UTF-8').read()
        template = Template(template_file)
        # TODO: add the three project data sections here? Or in the get_eml_metadata section.

        # Build out the object to populate the template, from config file mostly:
        eml_metadata_source = {}

        eml_metadata_source['nodemanager'] = pd.read_csv(Path(SCRIPT_PATH) / 'input' / 'contacts' / 'data_manager.csv').to_dict(orient='records')

        eml_metadata_source['contacts'] = pd.read_csv(Path(contacts)).to_dict(orient='records')

        eml_metadata_source['dataset_first_publication_date'] = datetime.now().isoformat()

        eml_metadata_source['dataset_first_publication_date_as_date'] = datetime.now().date().isoformat()

        eml_metadata_source['campaignid'] = cid

        result_string = template.render(eml_metadata_source)
        fh = open(eml_file, mode='w+', encoding='UTF-8')
        fh.write(result_string)
        fh.close()
        print(f'EML file written to {eml_file}')

        return eml_file
    
    return None


def republish_campaign(config_file:Path=None, cid:str=None, path_to_archive:Path=None, ipt_authfile:str=None, ipt_url:str=None) -> None:

    if path_to_archive is None:
        print("No DwC archive path provided for {cid}, skipping publish step.")
        return

    # TODO: evaluate fitness of DwC archive before continuing with publication


    with open(config_file, 'r') as campaign_config:
            config_dict = json.load(campaign_config)
            # config file is a list of dicts:
            config = config_dict[0] # so take the first entry

            if 'ipt_resource_id' in config['meta'].keys():    # TODO: what's our error response?
                ds_name = config['meta']['ipt_resource_id']
            else:
                print('No IPT ID in config file. Aborting publication for {cid}')
                return


    # Read the ipt_auth file into a dict for passing to the publish functions
    # 
    ipt_auth = ast.literal_eval(ipt_authfile.read_text()) # TODO: evaluate how safe it is to do this.

    session = pub.open_ipt_session(ipt_auth, ipt_url)
    current_date = datetime.utcnow().strftime('%Y-%m-%d')
    existing_proj = pub.check_if_project_exists(ds_name, ipt_url, session)

    if existing_proj:
        print(f"IPT entry {ds_name} exists for campaign {cid}.")
        # Workaround for IPT behaviour: have to run it 2x to bypass the beg box that pops up on the first request.
        output = pub.refresh_ipt_project_files(ds_name, path_to_archive, ipt_url, session)
        #output = pub.refresh_ipt_project_files(ds_name, path_to_archive, ipt_url, session)

        pub.publish_ipt_project(ds_name, ipt_url, session, publishing_notes=f'Automatically republished from realtime-sat-to-OBIS script on {current_date}')
        
        print(f'Updated data for existing project at {ipt_url}manage/resource?r={ds_name}')
    else:
        print(f"No IPT resource found for {ds_name} on {ipt_url}, creating a new project entry.")
        
        create_result = pub.create_new_ipt_project(ds_name, 
                                path_to_archive,
                                ipt_url,
                                session)
        
        # Can only do this before you publish the project.
        add_publisher = pub.change_publishing_org_ipt_project(ds_name, 
                                                            ipt_url, 
                                                            session, 
                                                            new_publishing_org_name='Ocean Tracking Network')
        
        pub.make_public_ipt_project(ds_name,ipt_url, session)
        
        pub.publish_ipt_project(ds_name,ipt_url, session, publishing_notes=f'Auto-publication from the realtime-sat-to-OBIS script on {current_date}')
        
        # GBIF registration - Can't be undone easily!
        # pub.register_ipt_project(ds_name, ipt_url, session)
        
        print('New project created at {ipt_url}manage/resource?r={dataset_name}'.format(ipt_url=ipt_url, dataset_name=ds_name))

if __name__ == '__main__':
    # mess with script pathing to do a default run
    script_path = Path(os.path.dirname(os.path.realpath(__file__)))

    # the reallink output in the argument doubles the folder and destination file. This parent entry 'fixes' that.
    input_path = Path(sys.argv[1]).parent

    # This lives inside a for loop across all the input folders
    # when we find a metadata.json file of the form config_*.json

    if input_path.exists():
      for f in input_path.glob('config_*.json'):
      # load the file
          config_file = json.load(open(f,'r'))[0]
      # get the CID from the file
          cid = config_file['harvest']['cid']
          print(cid)

    # cid = 'ct188'
    make_dwc_from_argosqc_output(input_path / 'qc' / 'aodn', cid=cid)
    path_to_archive = generate_campaign_eml_from_template(config_file=input_path/ f'config_{cid}.json', cid=cid)
    republish_campaign(config_file=input_path / f'config_{cid}.json', cid=cid, path_to_archive=path_to_archive, ipt_authfile=Path(script_path / '.iptauth_dev'), ipt_url='https://members.devel.oceantrack.org/ipt/')

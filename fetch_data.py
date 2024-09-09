# Functions for reading sources.yaml and fetching different types of data
import yaml
from cerberus import Validator

def fetch_tracks_csv(src: str):
    """
    Fetch a csv file of tracks, verify it's coherent, and map its relevant columns to their final names needed for the DwC translation
    """


def fetch_dataset(src: str, outpath: str = 'output'):
    """
    Read a source definition file and execute it.
    """
    # check if filetype is valid yaml for our purposes
    with open(src, 'r') as stream:
        try:
            datasource = yaml.load(stream)
        except yaml.YAMLError as exception:
            raise exception

    schema = eval(open('./templates/source_schema.py', 'r').read())
    v = Validator(schema)
    v.validate(datasource, schema)
    print(v.errors)    # TODO: Something productive about the errors?

    # if so, read its component data sources into their relevant structures

    fetch_tracks_csv(src=datasource)
    # and write them to the appropriate output

if __name__ == '__main__':
    fetch_dataset('sources/imos_ct180.yml')
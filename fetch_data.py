import pyobistools
import pandas as pd

# Using the QCed data sources - produce a DwC archive from each tag type
# Validate the archive 
# and possibly even autopublish it / autoupdate its publication on an IPT


def generate_rt_sat_DwC(configFile=''):
# Read a config file 
# Set up necessary input and outputs 
# and which flavour of tag we're working with
# call the necessary sub-functions to generate the DwC archive
    tag_family = ''
    metadata_file = ''
    qc_data_folder = ''
    output_folder = ''


# Events
    generate_rt_events(tag_family)
# Occurrences
    generate_rt_occurrences(tag_family)
# Biotic eMoFs
    generate_rt_emofs(tag_family)
# Abiotic eMoFs
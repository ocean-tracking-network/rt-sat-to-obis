import os
import sys
import urllib
import uuid
from dataclasses import dataclass
from getpass import getpass
from io import StringIO
from typing import Union, Dict, List

import itables
import pandas as pd
from IPython.core.display_functions import display
from ipywidgets import Color
from ipywidgets.widgets import widget
from pykeepass import PyKeePass
from pykeepass.exceptions import CredentialsError
from sqlalchemy import create_engine, VARCHAR
from sqlalchemy.engine import Engine
from termcolor import colored

def run_from_ipython():  # pragma: no cover
    """
    Returns True if function was called from ipython, used in pretty ipython
        notebook printing
    """
    try:
        __IPYTHON__
        return True
    except NameError:
        return False


@dataclass
class CustomEngine(Engine):
    """Custom engine object used to store extra OTN specific settings

    Args:
        Engine (_type_): Inherits the sqlalchemy engine object
    """
    auth_method: str
    dblinks: dict
    node: str
    uid: str

    def dispose(self):
        if not self.uid:
            return False
        print(f"Closing connection with UID: {self.uid}: ", end="")
        close_query = \
            f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity " \
            f"WHERE application_name LIKE '%%{self.uid}';"
        try:
            self.execute(close_query)
        except Exception as e:
            if 'orig' in e.__dict__ and 'server closed' in str(e.__dict__['orig']):
                print(f"{CLR.ok('OK!')}")
def print_error(msg_error:str=None) -> None:
    """
    Print error message
    Author: Angela Dini
    Maintainer: Angela Dini
    :param msg_error: error message string
    :return: None
    """
    if msg_error is None:
        print(CLR.error('ERROR!'))
    else:
        print(f"{CLR.error('ERROR:')}\n{msg_error}")

def print_warning(msg_warning:str=None) -> None:
    """
    Print warning message
    Author: Angela Dini
    Maintainer: Angela Dini
    :param msg_warning: warning message string
    :return: None
    """
    if msg_warning is None:
        print(CLR.warn('Warning!'))
    else:
        print(f"{CLR.warn('Warning:')}\n{msg_warning}")

def get_engine(authfile: str = 'database_conn_string.auth',
               host: str = 'localhost', db: str = 'nodename',
               auth_password: str = '', disable_ssl=False) -> Union[bool, CustomEngine]:

    """Create an engine object given a connection.auth file

    Args:
        authfile (str, optional): Filepath to auth file. Defaults to
            './dbtools/database_conn_string.auth'.
        host (str, optional): optional host string. Defaults to '192.168.57.101'.
        db (str, optional): optional target database name. Defaults to 'nodename'.
        auth_password (str, optional): password to unlock auth file. Defaults to None. Do not use
            in production for testing only.

    Returns:
        [type]: [description]
    """
    if not (os.path.isfile(authfile) and os.path.exists(authfile)):
        print(f"{CLR.error}:{authfile} was not found.")
        return False

    _file_name, file_ext = os.path.splitext(authfile)

    engine_uuid = str(uuid.uuid1())
    if file_ext.lower() == '.kdbx':
        try:
            if auth_password:
                kp = PyKeePass(authfile, password=auth_password)
            else:
                kp = PyKeePass(authfile, password=getpass('Auth password:'))
            group = kp.root_group
            entry = kp.root_group.entries[0]  # type: ignore
            # Check for the required custom fields
            missing_fields = False
            if not entry.get_custom_property('port'):
                print(f'{CLR.error("Error")}: port field is missing')
                missing_fields = True

            if not entry.get_custom_property('dbname'):
                print(f'{CLR.error("Error")}: dbname field is missing')
                missing_fields = True

            if missing_fields:
                return False

            connection_string = \
                f"postgresql://{entry.username}:{urllib.parse.quote(entry.password)}@{entry.url}:" \
                f"{entry.get_custom_property('port')}/{entry.get_custom_property('dbname')}"
            if entry.notes != '':
                print(f'Connection keyfile notes: {entry.notes}')

            if disable_ssl is True:
                engine = create_engine(connection_string,
                                    connect_args={"application_name": f"OTN NRT notebooks: {engine_uuid}",
                                                  "gssencmode ":"disable", "sslmode":"disable"})
            else:
                engine = create_engine(connection_string,
                                    connect_args={"application_name": f"OTN NRT notebooks: {engine_uuid}"})
            engine = change_to_customengine(engine)

            # Set engine auth_method
            engine.auth_method = 'kdbx'

            engine.uid = engine_uuid

            engine.dblinks = {}
            # Needs the dblink group to be in the keepass file
            dblinks = kp.find_groups(name='dblink', first=True)
            if dblinks and dblinks.entries: #type: ignore
                for r_entry in dblinks.entries: #type: ignore
                    engine.dblinks[r_entry.title] = {'user': r_entry.username,  # type: ignore
                                                     'password': r_entry.password,
                                                     'host': r_entry.url,
                                                     'port': r_entry.get_custom_property('port'),
                                                     'dbname': r_entry.get_custom_property('dbname')
                                                     }
            # If user has a git access token in their keepass file
            git_access_token_entry = kp.find_groups(name='git_access_token', first=True)
            if git_access_token_entry and git_access_token_entry.entries: #type: ignore
                engine.git_access_token = git_access_token_entry.entries[0].password #type: ignore

        except ValueError as e:
            print(f'Password Incorrect (Error:{e})')
            return False
        except CredentialsError as e:
            print(f'Keepass (KDBX) Password is incorrect')
            return False
        except Exception as e:
            print(f'Unexpected error (Error{e})')
            return False
        return engine
    else:
        if disable_ssl is True:
            engine = create_engine(get_conn_string(authfile=authfile, host=host, db=db),  # type: ignore
                                encoding='utf8',
                                connect_args={"application_name": f"Load to NRT datastore: {engine_uuid}",
                                              "gssencmode ":"disable", "sslmode":"disable"})
        else:
            engine = create_engine(get_conn_string(authfile=authfile, host=host, db=db),  # type: ignore
                    encoding='utf8',
                    connect_args={"application_name": f"Load to NRT datastore: {engine_uuid}"})

        engine = change_to_customengine(engine)

        # Set engine auth_method
        engine.auth_method = 'auth'  # type: ignore
        return engine

def get_conn_string(authfile: str = './dbtools/database_conn_string.auth',
                    host: str = '192.168.57.101',
                    db: str = 'nodename', port: str = '5432',
                    retdict: bool = False) -> Union[bool, str, dict]:
    """Return connection string object from a given authorization file

    Keyword Arguments:
        authfile {str} -- [description] (default: {'./dbtools/database_conn_string.auth'})
        host {str} -- [description] (default: {'192.168.57.101'})
        db {str} -- [description] (default: {'nodename'})
        port {str} -- [description] (default: {'5432'})
        retdict {bool} -- [description] (default: {False})

    Returns:
        [type] -- [description]
    """
    auth_string = open(authfile, 'r').readlines()[0].strip()

    my_args: Dict[str, str] = {}
    for arg in auth_string.split(' '):
        key, val = arg.split('=')
        if val != '%s':
            my_args[key] = val
        # thought about doing it with kwargs, but don't want to figure out default values right now
        elif key == 'host':
            my_args[key] = host
        elif key == 'dbname':
            my_args[key] = db
        elif key == 'port':
            my_args[key] = port
        else:
            print('missing value in %s , Cannot connect to DB.' % authfile)
            return False

    if 'port' not in list(my_args.keys()):
        my_args['port'] = port

    if retdict:
        return my_args
    else:
        conn_str = "postgresql://{user}:{password}@{host}:{port}/{dbname}" \
            .format(**{x: urllib.parse.quote_plus(my_args[x]) for x in my_args.keys()})
        return conn_str

def get_node(engine:CustomEngine ) -> Union[str, bool]:
    """Returns the datbase's NODE value from obis.node

    Args:
        engine (sqlalchemy.engine): input engine object
    """
    if not engine.has_table('node','obis'):
        return 'None'
    try:
        node = engine.execute("SELECT node_name FROM obis.node;").fetchone()[0]
    except Exception as e:
        print_warning('Problem getting node info from obis.nodes:', e)
        return False
    return node

def test_engine_connection(engine: CustomEngine):
    """ (jupyter only) Confirm if database engine can connect and print a summary of connection

    Arguments:
        engine sqlalchemy.engine -- Input engine object
    """
    try:
        engine.connect()

        # Add source node to the engine object
        engine.node = get_node(engine)

        print(("{0}\nConnection Type:{2} Host:{3} Database:{1} User:{4} Node:{5}"
              .format(CLR.ok('Database connection established!'), CLR.info(engine.url.database),
                      CLR.info(engine.url.drivername), CLR.info(engine.url.host),
                      CLR.info(engine.url.username), CLR.info(engine.node))))

        return True
    except Exception as inst:
        print(("{}:{}".format(CLR.error("ERROR"), inst.args[0])))
        return False

def change_to_customengine(engine: Engine) -> CustomEngine:
    """Convienience function to change the class of engine to customengine

    Args:
        engine (Engine): sqlalchemy engine object

    Returns:
        CustomEngine: custom engine object with added variables
    """
    engine.__class__ = CustomEngine
    new_engine:CustomEngine = engine# type: ignore
    return new_engine

class Color():
    """Wrapper for termcolor colored functions. Compatible with jupyter notebooks
    """
    def warn(self, text):
        return colored(text, 'red', 'on_yellow', attrs=['bold'])

    def error(self, text: str):
        return colored(text, 'red', attrs=['reverse', 'bold'])

    def ok(self, text: str):
        return colored(text, 'green', attrs=['bold'])

    def info(self, text: str):
        return colored(text, 'blue', attrs=['bold'])

    def red(self, text: str):
        return colored(text, 'red', attrs=['bold'])

    def yellow(self, text: str):
        return colored(text, 'yellow', attrs=['bold'])

    def magenta(self, text: str):
        return colored(text, 'magenta', attrs=['bold'])

    def bold(self, text: str):
        return colored(text, attrs=['bold'])


CLR = Color()
def map_header_to_table_columns(headers: List[str], ) -> List[str]:
    column_mapping = {
        'DeploymentID': 'deployment_id',
        'date': 'datetime_utc',
        'lon': 'longitude',
        'lat': 'latitude'
    }


def chunk_csv_loader(engine: Engine, input_file: str, table_name: str, schema: str,
                     chunksize: int = 10000) -> bool:
    """CSV chunk loading operation with progress bars for both command-line and notebook

    Args:
        engine (Engine): sqlalchemy engine object
        input_file (str): input csv file location
        table_name (str): target table name
        schema (str): target schema name
        chunksize (int, optional): load chunksize. (Defaults to 10000)
    """
    # Get column names
    headers = pd.read_csv(input_file, dtype=object, nrows=1, encoding='utf-8').columns
    headers = map_header_to_table_columns(headers)

    total_lines = get_file_line_count(input_file)

    # Read file yet again using chunks for memory
    dataframe = pd.read_csv(input_file, dtype=object, chunksize=chunksize, header=0,
                            names=headers, encoding='utf-8')

    dtypes = {x: VARCHAR for x in headers}  # Set all columns to varchar

    try:
        # Batch process all the chunks
        # db transfer
        no_chunk = 0
        conn = engine.raw_connection()
        cursor = conn.cursor()
        cmd = f'COPY {schema}.{table_name} FROM STDIN WITH (FORMAT CSV, HEADER TRUE)'
        progress = widget.IntProgress(0)
        if run_from_ipython():  # pragma: no cover
            # Use progress widget if loading this script from an ipython notebook
            display(progress)

        for chunk in dataframe:
            fh = StringIO()
            chunk.to_csv(fh, index=False, encoding='utf-8')
            # First create the database table using an empty dataframe chunk
            if no_chunk == 0:
                chunk[:0].to_sql(table_name, engine, schema=schema, dtype=dtypes,
                                 index=False, chunksize=chunksize, if_exists='append')
            fh.seek(0)
            cursor.copy_expert(cmd, fh)
            conn.commit()
            # sys.stdout.write('\r')
            no_chunk += 1
            percent = (chunksize * no_chunk) / float(total_lines)
            if percent > 1:
                percent = 1
            # Display the current percentage completed
            if run_from_ipython():  # pragma: no cover
                progress.value = percent*100
                progress.description = '{0}%'.format('{: >5}'.format(round(percent * 100, 1)))
            else:
                sys.stdout.write('\r')
                sys.stdout.write('{0}%[{1: <20}]'.format('{: >5}'.
                                                         format(round(percent * 100, 1)),
                                                         '#'*int(percent*20)))
        if not run_from_ipython():
            sys.stdout.write('\n')
        return True

    except ValueError as e:  # pragma: no cover
        print('Error:', e)
        return False
    except Exception:
        print('Unexpected Error:', sys.exc_info())
        return False


def get_file_line_count(file_path: str) -> int:
    """Returns the number of lines in a file

    Args:
        file_path (str): file path, either in Unix or Windows format

    Returns:
        int: The count of lines in a file
    """

    return sum(1 for i in open(file_path, 'rb'))

def show_df(dataframe:pd.DataFrame, save_as_file: str, show_all_rows=False) -> None:
    """
    Display an interactive DataTable and enable CSV/Excel export with customizable filename.

    Args:
        dataframe: the DataFrame to be displayed
        save_as_file: filename for export
        show_all_rows: If True, display all rows without truncation; otherwise use default row limit

    Returns: None
    """
    if show_all_rows:
        itables.options.maxBytes = 0
    itables.show(dataframe,
                 buttons=[
                    'copy',
                    {
                        'extend': 'csv',
                        'filename': save_as_file.replace('.csv', '')
                    },
                    {
                        'extend': 'excel',
                        'filename': save_as_file.replace('.csv', ''),
                        'exportOptions': {
                            'modifier': {
                                'page': 'all'
                            }
                        }
                    }
                ])


def get_program_campaign_from_ssm_file(ssm_file: str)-> tuple[str, str]:
    ssm_file = ssm_file.replace(str(os.getcwd()), '')
    print(f'ssm_file: {ssm_file}')
    program = ssm_file.split(os.path.sep)[1]
    campaign = ssm_file.split(os.path.sep)[2].replace(program + '_', '')
    return program, campaign

import os
import uuid
from dataclasses import dataclass
from getpass import getpass
from typing import Union

from ipywidgets import Color
from pykeepass import PyKeePass
from pykeepass.exceptions import CredentialsError
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

CLR = Color()

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
        print(f"{CLR.error('ERROR')}:{authfile} was not found.")
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
                                    connect_args={"application_name": f"Nodebooks {__version__}: {engine_uuid}",
                                                  "gssencmode ":"disable", "sslmode":"disable"})
            else:
                engine = create_engine(connection_string,
                                    connect_args={"application_name": f"Nodebooks {__version__}: {engine_uuid}"})
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

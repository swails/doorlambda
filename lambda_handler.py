""" Main Lambda handler for garage door opening service """
import datetime
import logging
import os
from base64 import b64decode
from functools import wraps

import boto3
import requests

def decrypt_environment_variable(variable_name):
    """ Decrypts the passed content """
    encrypted = os.environ[variable_name]
    return boto3.client('kms').decrypt(CiphertextBlob=b64decode(encrypted))['Plaintext']

LOGGER = logging.getLogger(__name__)

def needs_security_token(func):
    """ Wrapper around functions that require a security token """
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        """ Wrapper that ensures login """
        if self._security_token is None:
            self._login()
        try:
            return func(self, *args, **kwargs)
        except requests.HTTPError:
            # May require another login
            self._login()
            return func(self, *args, **kwargs)
    return wrapper

class MyQGarageDoor(object):
    """ Wrapper for interacting with a MyQ Garage door opener

    Parameters
    ----------
    username : str
        The account username for login
    password : str
        The account password for login
    """
    APPLICATION_ID = "NWknvuBd7LoFHfXmKNMBcgajXtZEgKUh4V7WNzMidrpUUluDpVYVZx+xT4PCM5Kx"
    BASE_URL = 'https://myqexternal.myqdevice.com'
    LOGIN_URI = '/api/v4/User/Validate'
    DEVICELIST_URI = '/api/v4/userdevicedetails/get'
    OPENCLOSE_URI = '/api/v4/deviceattribute/putdeviceattribute'
    DOORSTATE_MAP = {'1': 'Open', '2': 'Closed', '4': 'Opening', '5': 'Closing'}

    def __init__(self, username, password):
        self.username = username
        self.password = password
        self._security_token = None
        self._opener_id = None
        self._opener_state = None

    def _login(self):
        """ Logs into the application """
        headers = {"User-Agent": "Chamberlain/3.73", "BrandId": "2", "ApiVersion": "4.1",
                   "Culture": "en", "MyQApplicationId": self.APPLICATION_ID}
        response = requests.post(self.BASE_URL + self.LOGIN_URI, headers=headers,
                                 json=dict(username=self.username, password=self.password))
        response.raise_for_status()
        self._security_token = response.json()['SecurityToken']
        self._get_opener()

    @needs_security_token
    def _get_opener(self):
        """ Gets the list of devices and what state it's in """
        parameters = dict(appId=self.APPLICATION_ID, SecurityToken=self._security_token)
        response = requests.get(self.BASE_URL + self.DEVICELIST_URI, params=parameters)
        response.raise_for_status()
        for device in response.json()['Devices']:
            if device['MyQDeviceTypeName'] == 'GarageDoorOpener':
                self._opener_id = device['MyQDeviceId']
                for attribute in device['Attributes']:
                    if attribute['AttributeDisplayName'] == 'doorstate':
                        self._opener_state = attribute['Value']
        assert self._opener_id is not None, 'Could not ind opener'

    def check_door_state(self):
        """ Returns the state of the door, either Open, Closed, Opening, Closing, or Unknown """
        self._get_opener()
        return self.DOORSTATE_MAP.get(self._opener_state, 'Unknown')

    @needs_security_token
    def _set_door_state(self, value):
        """ Either opens the door (value=1) or closes the door (value=0) """
        parameters = dict(appId=self.APPLICATION_ID, SecurityToken=self._security_token)
        body = dict(ApplicationID=self.APPLICATION_ID, SecurityToken=self._security_token,
                    MyQDeviceId=self._opener_id, AttributeName='desireddoorstate',
                    AttributeValue=value)
        response = requests.put(self.BASE_URL + self.OPENCLOSE_URI, params=parameters, json=body)
        response.raise_for_status()

    def open_door(self):
        """ Opens the garage door """
        self._set_door_state(1)

    def close_door(self):
        """ Closes the garage door """
        self._set_door_state(0)

    def toggle_door(self):
        " Opens the door if it's closed (or closing) and closes the door if it's open (or opening) "
        state = self.check_door_state()
        if state in ('Open', 'Opening'):
            self.close_door()
        elif state in ('Closed', 'Closing'):
            self.open_door()
        else:
            LOGGER.warning('Could not determine door state. Closing door')
            self.close_door()

def handler(event, context):
    """ Handles the Lambda request """
    # Get all of the environment variables
    ACCOUNT = decrypt_environment_variable('ACCOUNT')
    PASSWORD = decrypt_environment_variable('PASSWORD')
    CLEANER_CODE = decrypt_environment_variable('CLEANER_CODE')
    FAMILY_CODE = decrypt_environment_variable('FAMILY_CODE')
    CLEANER_DAY = decrypt_environment_variable('CLEANER_DAY')

    EARLIEST_ALLOWED = 7 # 7 AM EST, or 8 AM EDT
    LATEST_ALLOWED = 17  # 5 PM EST, or 6 PM EDT

    cleaner_access = 'Thursday'
    now = datetime.datetime.now() # this corresponds to UTC in Lambda
    esthour = now.hour - 5 # east standard time hour is UTC - 5
    # The body must always be sent as {"body-json": "code=<code>"}
    code = event['body-json'][len('code='):]

    # Instantiate my door
    door = MyQGarageDoor(ACCOUNT, PASSWORD)

    if code == CLEANER_CODE and now.strftime('%A') == CLEANER_DAY:
        # Our code matches on the right day! Make sure it's an allowable time
        if EARLIEST_ALLOWED < esthour < LATEST_ALLOWED:
            door.toggle_door()
            LOGGER.info('CLEANER: Cleaner opened the door at %d:%d', esthour, now.minute)
        else:
            # We can close the door outside the allowed time slot
            state = door.check_door_state()
            door.close_door()
            LOGGER.warning('CLEANER: BAD TIME: Cleaner code used on %s door at %d:%d; '
                           'Open forbidden', state, esthour, now.minute)
    elif code == FAMILY_CODE:
        state = door.check_door_state()
        door.toggle_door()
        LOGGER.info('FAMILY: Family code used at %d:%d on %d door', esthour, now.minute, state)
    else:
        LOGGER.warning('BAD CODE: Code %s was used -- forbidden!', code)
        return dict(StatusCode=404, Status='404 Forbidden', body='Bad code!')

    return dict(StatusCode=200, Status='200 OK', body='OK')
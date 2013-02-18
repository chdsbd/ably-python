import functools
import types
import requests

from ably.auth import Auth
from ably.channel import Channels
from ably.exceptions import AblyException


def reauth_if_expired(func):
    @functools.wraps(func)
    def wrapper(rest, *args, **kwargs):
        while True:
            try:
                return func(rest, *args, **kwargs)
            except AblyException as e:
                if e.code == 40140:
                    rest.reauth()
                    continue
                raise
    return wrapper


class AblyRest(object):
    """Ably Rest Client"""
    def __init__(self, key=None, app_id=None, key_id=None, key_value=None,
            client_id=None, rest_host="rest.ably.io", rest_port=443,
            encrypted=True, auth_token=None, auth_callback=None,
            auth_url=None, keep_alive=True):
        """Create an AblyRest instance.

        :Parameters:
          **Credentials**
          - `key`: a valid key string

          **Or**
          - `app_id`: Your Ably application id
          - `key_id`: Your Ably key id
          - `key_value`: Your Ably key value

          **Optional Parameters**
          - `client_id`: Undocumented
          - `rest_host`: The host to connect to. Defaults to rest.ably.io
          - `rest_port`: The port to connect to. Defaults to 443
          - `encrypted`: Specifies whether the client should use TLS. Defaults
            to True
          - `auth_token`: Undocumented
          - `auth_callback`: Undocumented
          - `auth_url`: Undocumented
          - `keep_alive`: use persistent connections. Defaults to True
        """
        self.__base_url = 'https://rest.ably.io'

        if key is not None:
            try:
                app_id, key_id, key_value = key.split(':', 3)
            except ValueError:
                raise ValueError("invalid key parameter: %s" % key)

        if not app_id:
            raise ValueError("no app_id provided")

        self.__app_id = app_id
        self.__key_id = key_id
        self.__key_value = key_value
        self.__client_id = client_id
        self.__rest_host = rest_host
        self.__rest_port = rest_port
        self.__encrypted = encrypted
        self.__keep_alive = bool(keep_alive)

        if self.__keep_alive:
            self.__session = requests.Session()
        else:
            self.__session = None

        self.__scheme = 'https'
        self.__authority = '%s://%s:%d' % (self.__scheme, rest_host, rest_port)
        self.__base_uri = '%s/apps/%s' % (self.__authority, app_id)

        self.__auth = Auth(self, app_id=app_id, key_id=key_id,
                key_value=key_value, auth_token=auth_token,
                auth_callback=auth_callback, auth_url=auth_url, 
                client_id=client_id)

        self.__channels = Channels(self)

    def stats(self, params):
        """Returns the stats for this application"""
        return self.get('/stats', params=params).json()

    def time(self):
        """Returns the current server time in ms since the unix epoch"""
        r = self.get('/time', absolute_path=True)
        AblyException.raise_for_response(r)
        return r.json()[0]

    def default_get_headers(self):
        return {
            'Accept': 'application/json',
        }

    def default_post_headers(self):
        return {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
        }

    @reauth_if_expired
    def get(self, path, headers=None, params=None, absolute_path=False):
        headers = self.default_get_headers()
        headers.update(headers or {})
        headers.update(self.__auth.get_auth_headers())

        prefix = self.__authority if absolute_path else self.__base_uri

        r = self._requests.get("%s%s" % (prefix, path), headers=headers)
        AblyException.raise_for_response(r)
        return r

    @reauth_if_expired
    def post(self, path, data=None, headers=None, params=None, 
            absolute_path=False):
        headers = self.default_post_headers()
        headers.update(headers or {})
        headers.update(self.__auth.get_auth_headers())

        prefix = self.__authority if absolute_path else self.__base_uri

        r = self._requests.post("%s%s" % (prefix, path), 
                headers=headers, data=data)
        AblyException.raise_for_response(r)
        return r

    @reauth_if_expired
    def delete(self, path, headers=None, params=None, absolute_path=False):
        headers = dict(headers or {})
        headers.update(self.__auth.get_auth_headers())

        prefix = self.__authority if absolute_path else self.__base_uri

        r = self._requests.delete("%s%s" % (prefix, path), headers=headers)
        AblyException.raise_for_response(r)
        return r

    @property
    def authority(self):
        return self.__authority

    @property
    def base_uri(self):
        return self.__base_uri

    @property
    def app_id(self):
        return self.__app_id or ""

    @property
    def client_id(self):
        return self.__client_id or ""

    @property
    def rest_host(self):
        return self.__rest_host

    @property
    def rest_port(self):
        return self.__rest_port

    @property
    def channels(self):
        """Returns the channels container object"""
        return self.__channels

    @property
    def auth(self):
        return self.__auth

    @property
    def encrypted(self):
        return self.__encrypted

    @property
    def scheme(self):
        return self.__scheme

    @property
    def keep_alive(self):
        return self.__keep_alive

    @property
    def _requests(self):
        return self.__session if self.__keep_alive else requests


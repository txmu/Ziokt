"""Opt-in, authenticated loopback access to RetroShare's native JSON API.

Official interface definitions: libretroshare/src/retroshare/{rsjsonapi,
rspeers,rsfiles}.h. This adapter never creates identities, trusts friends,
publishes shares, or changes RetroShare's network policy.
"""
import base64
import http.client
from pathlib import Path
import re
from urllib.parse import urlsplit

from .protocol import ProtocolError, encoded, secure_read, strict_json

METHODS = {
    'version': ('RsJsonApi/version', {}),
    'counts': ('rsPeers/getPeersCount', {'countLocations': True}),
    'friends': ('rsPeers/getFriendList', {}),
    'online': ('rsPeers/getOnlineList', {}),
    'shares': ('rsFiles/getSharedDirectories', {}),
    'downloads': ('rsFiles/FileDownloads', {}),
}
MAX_RESPONSE = 256 * 1024


class RetroShare:
    def __init__(self, config=None):
        self.config = config or {'enabled': False}
        if type(self.config) is not dict or type(self.config.get('enabled')) is not bool:
            raise ValueError('explicit RetroShare enabled flag required')
        if not self.config['enabled']:
            if set(self.config) != {'enabled'}:
                raise ValueError('disabled RetroShare config accepts only enabled')
            self.enabled = False
            return
        if set(self.config) != {'enabled', 'endpoint', 'auth_file'}:
            raise ValueError('exact RetroShare endpoint and private auth_file required')
        endpoint = urlsplit(self.config['endpoint'])
        if (endpoint.scheme != 'http' or endpoint.hostname not in ('127.0.0.1', '::1')
                or endpoint.username or endpoint.password or endpoint.path not in ('', '/')
                or endpoint.query or endpoint.fragment or not endpoint.port):
            raise ValueError('literal loopback RetroShare JSON API origin required')
        self.host, self.port = endpoint.hostname, endpoint.port
        self.auth_file = Path(self.config['auth_file'])
        if not self.auth_file.is_absolute() or '..' in self.auth_file.parts:
            raise ValueError('absolute owner-private RetroShare credential file required')
        self._authorization()  # Validate private file before advertising enabled.
        self.enabled = True

    def _authorization(self):
        credentials = strict_json(secure_read(self.auth_file, 4096))
        if (type(credentials) is not dict or set(credentials) != {'username', 'password'}
                or type(credentials['username']) is not str
                or not re.fullmatch(r'[A-Za-z0-9_]{1,64}', credentials['username'])
                or type(credentials['password']) is not str
                or not 1 <= len(credentials['password']) <= 1024
                or any(c in credentials['password'] for c in '\r\n\x00')):
            raise ValueError('invalid RetroShare API credentials')
        return 'Basic ' + base64.b64encode((credentials['username'] + ':' + credentials['password']).encode()).decode()

    def call(self, method):
        if not self.enabled:
            raise ProtocolError('NATIVE_UNAVAILABLE', 'RetroShare is not configured')
        if method not in METHODS:
            raise ProtocolError('METHOD_UNSUPPORTED', 'fixed read-only RetroShare method required')
        path, arguments = METHODS[method]
        connection = http.client.HTTPConnection(self.host, self.port, timeout=3)
        try:
            connection.request('POST', '/' + path, body=encoded(arguments), headers={
                'Authorization': self._authorization(), 'Content-Type': 'application/json',
                'Accept': 'application/json'})
            response = connection.getresponse()
            if response.status != 200 or response.getheader('Content-Type', '').split(';')[0].strip() != 'application/json':
                raise ProtocolError('NATIVE_UNAVAILABLE', 'RetroShare request failed; check native API, authentication and version')
            raw = response.read(MAX_RESPONSE + 1)
            if len(raw) > MAX_RESPONSE:
                raise ProtocolError('LIMIT_EXCEEDED', 'RetroShare response budget exceeded')
            data = strict_json(raw)
            if type(data) is not dict or data.get('retval') is False or data.get('error'):
                raise ProtocolError('NATIVE_REJECTED', 'RetroShare reported an unsuccessful operation')
            return data
        except (OSError, http.client.HTTPException) as exc:
            raise ProtocolError('NATIVE_UNAVAILABLE', 'RetroShare native API is unreachable') from exc
        finally:
            connection.close()

    def status(self):
        base = {'schema': 'ziokt.retroshare-status.v1', 'enabled': self.enabled,
                'read_only': True, 'external_peer_transfer': 'not_assessed'}
        if not self.enabled:
            return dict(base, state='not_configured', native_authenticated=False)
        try:
            version = self.call('version')
            if any(type(version.get(k)) is not int or not 0 <= version[k] <= 9999 for k in ('major', 'minor', 'mini')):
                raise ProtocolError('NATIVE_REJECTED', 'RetroShare version response invalid')
            counts = self.call('counts')
            if counts.get('retval') is not True or any(type(counts.get(k)) is not int or not 0 <= counts[k] <= 1000000 for k in ('peersCount', 'onlinePeersCount')):
                raise ProtocolError('NATIVE_REJECTED', 'RetroShare authenticated status response invalid')
            return dict(base, state='connected', native_authenticated=True,
                        version='.'.join(str(version[k]) for k in ('major', 'minor', 'mini')),
                        friends=counts['peersCount'], online=counts['onlinePeersCount'])
        except ProtocolError as exc:
            return dict(base, state='unavailable', native_authenticated=False, reason=exc.code)

    def inspect(self, action):
        data = self.call(action)
        field = {'friends': 'sslIds', 'online': 'sslIds', 'shares': 'dirs', 'downloads': 'hashs'}.get(action)
        if not field or type(data.get(field)) is not list or len(data[field]) > 1024:
            raise ProtocolError('NATIVE_REJECTED', 'bounded RetroShare native list required')
        if action != 'downloads' and data.get('retval') is not True:
            raise ProtocolError('NATIVE_REJECTED', 'RetroShare native operation did not succeed')
        if action in ('friends', 'online', 'downloads'):
            size = 40 if action == 'downloads' else 32
            if any(type(v) is not str or not re.fullmatch('[0-9a-fA-F]{' + str(size) + '}', v) for v in data[field]):
                raise ProtocolError('NATIVE_REJECTED', 'RetroShare native identifier format invalid')
        return {'schema': 'ziokt.retroshare-list.v1', 'kind': action, 'items': data[field],
                'native_authenticated': True, 'read_only': True}

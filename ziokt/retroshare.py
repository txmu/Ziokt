"""Opt-in, authenticated loopback access to RetroShare's native JSON API.

Official interface definitions: libretroshare/src/retroshare/{rsjsonapi,
rspeers,rsfiles}.h. This adapter never creates identities, trusts friends,
publishes shares, or changes RetroShare's network policy.
"""
import base64
import http.client
import json
from decimal import Decimal
from pathlib import Path
import re
from urllib.parse import urlsplit

from .protocol import ProtocolError, encoded, secure_read, strict_json

METHODS = {
    'version': ('rsJsonApi/version', {}),
    'counts': ('rsPeers/getPeersCount', {'countLocations': True}),
    'friends': ('rsPeers/getFriendList', {}),
    'online': ('rsPeers/getOnlineList', {}),
    'shares': ('rsFiles/getSharedDirectories', {}),
    'downloads': ('rsFiles/FileDownloads', {}),
}
MAX_RESPONSE = 256 * 1024


def native_json(raw):
    # RetroShare exposes finite diagnostic floats, while Ziokt's signed wire
    # protocol only permits integers. Keep those diagnostics as strings; do not
    # weaken the canonical signed-protocol parser or coerce a float to a size.
    def pairs(values):
        result={}
        for key,value in values:
            if key in result:raise ValueError('duplicate native JSON field')
            result[key]=value
        return result
    def decimal(value):
        number=Decimal(value)
        if not number.is_finite() or abs(number)>2**53 or len(value)>64:raise ValueError('native diagnostic number')
        return value
    def invalid(_):raise ValueError('nonfinite native JSON value')
    try:return strict_json(encoded(json.loads(raw,object_pairs_hook=pairs,parse_float=decimal,parse_constant=invalid)),MAX_RESPONSE)
    except (ValueError,UnicodeError,RecursionError) as exc:raise ProtocolError('NATIVE_REJECTED','invalid bounded RetroShare JSON response') from exc


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
        if set(self.config)-{'enabled','endpoint','auth_file','transport'} or not {'enabled','endpoint','auth_file'}<=set(self.config):
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
        if method not in METHODS:raise ProtocolError('METHOD_UNSUPPORTED','fixed RetroShare inspection method required')
        path,arguments=METHODS[method]
        return self._request(path,arguments)

    def _request(self,path,arguments,*,allow_false=False):
        if not self.enabled:
            raise ProtocolError('NATIVE_UNAVAILABLE', 'RetroShare is not configured')
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
            data = native_json(raw)
            if type(data) is not dict or (data.get('retval') is False and not allow_false) or data.get('error'):
                raise ProtocolError('NATIVE_REJECTED', 'RetroShare reported an unsuccessful operation')
            return data
        except (OSError, http.client.HTTPException) as exc:
            raise ProtocolError('NATIVE_UNAVAILABLE', 'RetroShare native API is unreachable') from exc
        finally:
            connection.close()

    def status(self):
        base = {'schema': 'ziokt.retroshare-status.v1', 'enabled': self.enabled,
                'read_only': 'transport' not in self.config, 'carrier':'retroshare-f2f-files','external_peer_transfer': 'not_assessed'}
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

    def invite(self):
        result=self._request('rsPeers/getShortInvite',{'sslId':'0'*32,'inviteFlags':41,'baseUrl':''})
        invite=result.get('invite')
        if result.get('retval') is not True or not isinstance(invite,str) or not 1<=len(invite)<=16384:raise ProtocolError('NATIVE_REJECTED','RetroShare invite unavailable')
        return {'invite':invite,'public_certificate':True,'secret_key_included':False}

    def accept_invite(self,invite,expected_peer,confirm):
        from .retroshare_transport import identifier
        expected_peer=identifier(expected_peer,32)
        if confirm is not True or not isinstance(invite,str) or not 1<=len(invite)<=16384:raise ProtocolError('POLICY_DENIED','explicit friend confirmation and bounded certificate required')
        parsed=self._request('rsPeers/parseShortInvite',{'invite':invite})
        if parsed.get('retval') is not True or parsed.get('details',{}).get('id')!=expected_peer:raise ProtocolError('POLICY_DENIED','RetroShare certificate does not match expected peer')
        result=self._request('rsPeers/acceptInvite',{'invite':invite,'flags':0})
        if result.get('retval') is not True:raise ProtocolError('NATIVE_REJECTED','RetroShare friend acceptance rejected')
        return {'peer':expected_peer,'state':'friend_accepted','connected':False}

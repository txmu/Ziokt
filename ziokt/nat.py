"""STUN discovery on the application's own UDP socket, alongside native reuse.

A mapped UDP address is a candidate, never evidence of TCP reachability, peer
identity or anonymity. Signaling and ICE/Corium still own connection negotiation.
"""
import ipaddress
import secrets
import socket
import struct
import time

from .protocol import ProtocolError
from .runtime_policy import require_network

COOKIE=0x2112A442


def stun_binding(stream, server, *, timeout=3, privacy='standard'):
    require_network()
    if privacy!='standard':raise ProtocolError('POLICY_DENIED','STUN address disclosure requires an explicit standard route')
    if (not isinstance(server,dict) or set(server)!={'host','port'} or type(server['port']) is not int or
            not 1<=server['port']<=65535 or type(timeout) not in {int,float} or not 0<timeout<=5):
        raise ProtocolError('INVALID_CONFIG','explicit bounded STUN server required')
    try:host=ipaddress.ip_address(server['host'])
    except (ValueError,TypeError):raise ProtocolError('INVALID_CONFIG','STUN server must be an explicit literal address')
    family=socket.AF_INET6 if host.version==6 else socket.AF_INET
    if stream.family!=family or stream.type&socket.SOCK_DGRAM!=socket.SOCK_DGRAM:
        raise ProtocolError('INVALID_BOUNDARY','caller-owned UDP socket of the matching family required')
    transaction=secrets.token_bytes(12);header=struct.pack('!HHI',1,0,COOKIE)+transaction
    endpoint=(str(host),server['port']);old_timeout=stream.gettimeout();deadline=time.monotonic()+timeout
    try:
        stream.sendto(header,endpoint)
        while True:
            remaining=deadline-time.monotonic()
            if remaining<=0:raise ProtocolError('STUN_TIMEOUT','STUN discovery timed out')
            stream.settimeout(remaining)
            try:packet,source=stream.recvfrom(2049)
            except socket.timeout:raise ProtocolError('STUN_TIMEOUT','STUN discovery timed out')
            if source[:2]!=endpoint:continue
            if len(packet)<20 or len(packet)>2048:raise ProtocolError('INVALID_STUN','bounded STUN response required')
            kind,length,cookie=struct.unpack('!HHI',packet[:8])
            if packet[8:20]!=transaction:continue
            if kind!=0x101 or cookie!=COOKIE or length!=len(packet)-20 or length%4:
                raise ProtocolError('INVALID_STUN','STUN success framing required')
            offset=20;mapped=[]
            while offset<len(packet):
                if offset+4>len(packet):raise ProtocolError('INVALID_STUN','truncated attribute header')
                attribute,size=struct.unpack('!HH',packet[offset:offset+4]);offset+=4
                value=packet[offset:offset+size]
                if len(value)!=size or offset+((size+3)//4)*4>len(packet):raise ProtocolError('INVALID_STUN','truncated attribute')
                offset+=((size+3)//4)*4
                if attribute not in {1,0x20}:continue
                if len(value)<4 or value[0]!=0 or value[1] not in {1,2}:raise ProtocolError('INVALID_STUN','invalid mapped address')
                width=4 if value[1]==1 else 16
                if len(value)!=4+width:raise ProtocolError('INVALID_STUN','mapped address length')
                port=struct.unpack('!H',value[2:4])[0];address=value[4:]
                if attribute==0x20:
                    port^=COOKIE>>16;mask=struct.pack('!I',COOKIE)+transaction
                    address=bytes(byte^mask[index] for index,byte in enumerate(address))
                if not port:raise ProtocolError('INVALID_STUN','zero mapped port')
                mapped.append((attribute,str(ipaddress.ip_address(address)),port))
            preferred=[value for value in mapped if value[0]==0x20] or mapped
            if len(preferred)!=1:raise ProtocolError('INVALID_STUN','one mapped address required')
            return {'schema':'ziokt.stun-candidate.v1','host':preferred[0][1],'port':preferred[0][2],
                    'transport':'udp','same_socket_required':True,'peer_authenticated':False,'reachability_verified':False}
    finally:stream.settimeout(old_timeout)

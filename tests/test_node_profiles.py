"""Joint-node planning/export, twelve route families and drift rejection."""
import base64
import json
from pathlib import Path
import secrets
import tempfile
import unittest

from ziokt.cli import write_exclusive,write_binary_exclusive
from ziokt.config import fingerprint
from ziokt.node import create_profile,plan,export_units,CORES
from ziokt.protocol import ProtocolError

ROOT=Path(__file__).resolve().parents[2]

class NodeProfiles(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.config=self.root/'federation.json';self.registry=self.root/'registry.json';self.virtual=self.root/'virtual.json'
        providers=[{'native_project':'corium','provider_id':'corium-local','root':str(ROOT/'Corium'),'native_config':str(self.root/'corium/etc/corix/networks/default/corix.conf'),
            'state_root':str(self.root/'corium'),'network_id':'default','entrypoint_digest':fingerprint(ROOT/'Corium/corix_v108.sh')}]
        write_exclusive(self.config,{'schema':'ziokt.federation.v1','enabled':True,'federation_id':'test','providers':providers})
        write_binary_exclusive(self.root/'identity',secrets.token_bytes(32))
        services={};routes=[];cores={}
        for i,core in enumerate(sorted(CORES)):
            port=18000+i;native=self.root/(core+'.json');envelope=self.root/(core+'.conf')
            write_exclusive(native,{'role':'broker','listen_host':'127.0.0.1','listen_port':19000+i})
            write_binary_exclusive(envelope,f'role=server\nmode=stream\nlisten=127.0.0.1:{port}\nupstream=127.0.0.1:{19000+i}\n'.encode())
            services['test/'+core]={'coreBinding':{'core':core,'config':{'config_path':str(native)}},'protocolContext':{'role':'broker'},
                'privacy':'envelope','spec':{'envelope_config':str(envelope)},'deploymentLock':{'digest':'sha256:'+'a'*64}}
            cores[core]={'host':'127.0.0.1','port':port};routes.append({'tenant':'test','core':core,'host':'127.0.0.1','port':port})
        write_exclusive(self.registry,{'schema':'shadow6.service-registry.v2','services':services})
        write_exclusive(self.virtual,{'schema':'shadow6.virtual-broker.v1','listen':{'host':'127.0.0.1','port':17443},'identity_key_file':str(self.root/'identity'),
            'cores':cores,'tenants':[{'id':'test','public_keys':[base64.b64encode(secrets.token_bytes(32)).decode()],'approval':'default-approved','max_connections':8,'bytes_per_second':1048576,'burst_bytes':2097152}],
            'routes':routes,'approvals':[],'guard':{'required':True},'gate':{'required':True},'c11relay':{'control_socket':str(self.root/'relay.sock')},
            'limits':{'max_frame':16384,'handshake_seconds':5,'idle_seconds':60},'anonymous_listeners':[],'datagram_listeners':[]})
        self.units={'corium':'corium.service','guard':'shadow6-guard.service','gate':'shadow6-gate.service'}
        self.profile=create_profile(ROOT/'Shadow6',self.config,'corium-local',self.registry,self.virtual,self.units)

    def test_twelve_locked_source_routes_export_dependencies_without_starting_anything(self):
        review=plan(self.profile,probe=False)
        self.assertEqual(set(review['cores']),CORES);self.assertFalse(review['runtime_verified']);self.assertFalse(review['wire_translation'])
        profile_file=self.root/'profile.json';write_exclusive(profile_file,self.profile)
        result=export_units(self.profile,profile_file,self.root/'units','ziokt-test')
        self.assertFalse(result['installed'])
        target=Path(result['files'][0]).read_text();service=Path(result['files'][1]).read_text()
        for unit in self.units.values():self.assertIn(unit,target);self.assertIn(unit,service)
        self.assertIn('--expected-digest',service);self.assertIn('NoNewPrivileges=yes',service)

    def test_drift_missing_s6epe_and_unit_injection_fail_closed(self):
        with self.assertRaises(ProtocolError):create_profile(ROOT/'Shadow6',self.config,'corium-local',self.registry,self.virtual,{**self.units,'gate':'gate.service\nExecStart=evil'})
        altered=json.loads(self.registry.read_bytes());altered['services']['test/go']['privacy']='native';self.registry.write_text(json.dumps(altered))
        with self.assertRaises(ProtocolError):plan(self.profile,probe=False)
        with self.assertRaises(ProtocolError):create_profile(ROOT/'Shadow6',self.config,'corium-local',self.registry,self.virtual,self.units)

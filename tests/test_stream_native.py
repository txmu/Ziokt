"""Production C gateway over real native S trios and the unchanged attachment SDK.

No Core compilation: every installed primary stream Profile is tested. Source
contracts for all twelve families are covered independently. Missing requested
artifacts are failures; no synthetic native wire is substituted.
"""
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import asyncio
import base64
import hashlib
import shlex

from test_native_integration import S, C
from ziokt._runtime import CoriumDataChannel
from ziokt.transport import NativeTransport, native_profile_matrix


class NativeStreamTests(unittest.TestCase):
    def test_source_contract_covers_all_twelve_families_and_thirteen_profiles(self):
        rows = native_profile_matrix(S)
        self.assertEqual(len({r["core"] for r in rows}), 12)
        self.assertEqual(len(rows), 13)
        self.assertTrue(all(not r["runtime_verified"] for r in rows))

    @unittest.skipUnless(os.environ.get("ZIOKT_NATIVE_DATA_TEST") == "1", "explicit native data gate; enabled in integration CI")
    def test_installed_profiles_carry_signed_corium_ping(self):
        sys.path[:0] = [str(C), str(S), str(S/"integration"), str(S/"Crosed")]
        extra_libs = [str(S / "Core-Nim"), str(S / "Core-Idris")]
        existing_libs = [p for p in os.environ.get("LD_LIBRARY_PATH", "").split(":") if p]
        os.environ["LD_LIBRARY_PATH"] = ":".join(extra_libs + existing_libs)
        from test_core import Fixture
        from Deployment.service_registry import ServiceRegistry
        from Deployment.core_catalog import CoreCatalog
        from Deployment.protocol_context import minimal_context
        from Deployment.service_storage import atomic_write
        from libshadow6 import Shadow6, RegistryControl
        from native_profiles import profiles
        from stack_test import generate_configs
        from native_configs import generate_commands
        from cryptography.hazmat.primitives import serialization
        fixture = Fixture(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        ready_key = fixture.root/"data.key"; ready_key.write_bytes(secrets.token_bytes(32)); ready_key.chmod(0o600)
        (fixture.etc/"identity.key").chmod(0o600)
        config = fixture.etc/"corix.conf"
        bindings_file = fixture.root/"transport-bindings.json"
        config.write_text("[ziokt]\nenabled=TRUE\nfederation_id=test\nprovider_id=corium-local\nallow_mutations=TRUE\nallowed_operations=artifact.stage\nallowed_resources=*\ntransport_bindings_file="+str(bindings_file)+"\n"); config.chmod(0o600)
        from ziokt.client import NativeClient
        from ziokt.config import fingerprint
        from ziokt.community import Community, RIGHTS, create_policy
        from ziokt.security import sign
        community_private, community_key = secrets.token_bytes(32), secrets.token_bytes(32)
        community_public = sign({}, community_private, "test")["public_key"]
        community_policy = create_policy(community_private, "native-community", {community_public: sorted(RIGHTS)})
        community_source = Community(fixture.root/"community-source", community_policy, community_public, community_key)
        self.addCleanup(community_source.close)
        manifest = community_source.put_file(b"Community survives native node loss")
        community_source.publish(community_private, "files", "archive", {"name": "archive", **manifest})
        sealed_event = community_source.db.execute("SELECT sealed FROM records").fetchone()[0]
        content = community_source.store.get(manifest["chunks"][0])
        content_digest = "sha256:"+hashlib.sha256(content).hexdigest()
        client = NativeClient("test", {"native_project": "corium", "provider_id": "corium-local", "root": str(C),
            "native_config": str(config), "state_root": str(fixture.root), "network_id": "default",
            "entrypoint_digest": fingerprint(C/"corix_v108.sh")})
        prepared = client.call("operation.prepare", {"operation_id": "network-content", "action": "artifact.stage",
            "resource": content_digest, "arguments": {"data_base64": base64.b64encode(content).decode()}, "expected_revision": None})
        client.call("operation.commit", {"operation_id": "network-content", "plan_digest": prepared["plan_digest"]})
        from ziokt.peer_directory import PeerDirectory
        from ziokt.discovery_native import fetch_records
        discovery_directory = PeerDirectory(fixture.root/'native-discovery',community_policy,community_public,allowed_networks=['127.0.0.0/8'])
        self.addCleanup(discovery_directory.close)
        record = discovery_directory.advertise(community_private,[{'host':'127.0.0.1','port':12345,'fingerprint':'1'*64,'service':'proxy'}],'2'*64)
        discovery_data = json.dumps([record],separators=(',',':')).encode()
        discovery_digest = 'sha256:'+hashlib.sha256(discovery_data).hexdigest()
        prepared = client.call('operation.prepare',{'operation_id':'network-discovery','action':'artifact.stage','resource':discovery_digest,
            'arguments':{'data_base64':base64.b64encode(discovery_data).decode()},'expected_revision':None})
        client.call('operation.commit',{'operation_id':'network-discovery','plan_digest':prepared['plan_digest']})
        server = subprocess.Popen(["bash", str(C/"corix_v108.sh"), "ziokt", "serve-data", "--key-file", str(ready_key)],
                                  env=fixture.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        self.addCleanup(self.stop_server, server)
        import threading
        output, arrived = [], threading.Event()
        def read_ready():
            output.append(server.stdout.readline(65536)); arrived.set()
        reader = threading.Thread(target=read_ready, daemon=True); reader.start()
        if not arrived.wait(15):
            self.stop_server(server)
            self.fail("native Corium data gateway did not become ready")
        event = output[0]
        ready = json.loads(event); self.assertEqual(ready["event"], "ziokt.data-ready")
        native_key = serialization.load_pem_private_key((fixture.etc/"identity.key").read_bytes(), password=None)
        selected = [p for p in profiles() if (S/p["artifact"]).is_file()]
        if os.environ.get("ZIOKT_PROFILE_TEST"):
            selected = [p for p in selected if p["id"] == os.environ["ZIOKT_PROFILE_TEST"]]
        else:
            self.assertEqual({p["id"] for p in selected}, {p["id"] for p in profiles()}, "missing native Profile products")
        self.assertTrue(selected, "at least one real installed Core required")
        for profile in selected:
            with self.subTest(profile=profile["id"]), tempfile.TemporaryDirectory(prefix="ziokt-real-trio-") as directory:
                base = Path(directory)
                with socket.socket() as available:
                    available.bind(("127.0.0.1", 0)); broker_port = available.getsockname()[1]
                output = base/"configs"
                engine = "shadow6-" + profile["benchmarkAlias"]
                if profile["realization"]["launcher"] == "native-files":
                    documents = {}
                    generate_commands(engine, S/profile["artifact"], output, ready["port"], normalized_documents=documents)
                    configs = {}
                    for role, document in documents.items():
                        configs[role] = output/(role+'.json'); atomic_write(configs[role], json.dumps(document).encode())
                else:
                    asyncio.run(generate_configs(engine, output, ready["port"], broker_port))
                    configs = {}
                    for candidate in output.glob('*.json'):
                        document = json.loads(candidate.read_text())
                        role = document.get('role')
                        if role in {'broker', 'agent', 'client'}:
                            self.assertNotIn(role, configs, 'ambiguous native role material')
                            configs[role] = candidate
                    self.assertEqual(set(configs), {'broker', 'agent', 'client'})
                registry = ServiceRegistry(base/"services.json", CoreCatalog(S))
                names = {role: "ziokt/"+role for role in ("broker", "agent", "client")}
                try:
                    for role in names:
                        native = configs[role]
                        native.chmod(0o600)
                        context = minimal_context(profile["core"]); context["role"] = role
                        registry.create(names[role], core=profile["core"], profile=profile["id"], config={"config_path": str(native)}, context=context)
                        registry.apply(names[role]); registry.run(names[role])
                    with Shadow6(control=RegistryControl(registry)) as sdk:
                        binding = {"peer_id": fixture.identity, "shadow6_root": str(S), "service_name": names["client"],
                            "registry_path": str(base/"services.json"), "lock_digest": registry.services[names["client"]]["deploymentLock"]["digest"],
                            "key_file": str(ready_key), "mode": "required", "allow_native_fallback": False, "privacy_profile": "private"}
                        bindings_file.write_text(json.dumps({"schema": "ziokt.transport-bindings.v1", "network_id": "default", "bindings": [binding]}))
                        bindings_file.chmod(0o600)
                    native = fixture.run_core('load_config; dht_send_message '+fixture.identity+' PING')
                    self.assertEqual(native.stdout.strip().splitlines()[-1], "PONG:"+fixture.identity)
                    # Some original Profiles finish their process after one
                    # application session. Start a fresh trio for the next
                    # transaction for every family, preserving native semantics.
                    for role in ("client", "agent", "broker"): registry.stop(names[role])
                    for role in names: registry.run(names[role])
                    query = json.dumps({"digest": content_digest}, separators=(',', ':'))
                    response = fixture.run_core('load_config; dht_send_message '+fixture.identity+' ZIOKT_CONTENT_GET '+shlex.quote(query))
                    result = json.loads(response.stdout.strip().splitlines()[-1])
                    self.assertEqual(base64.b64decode(result["data_base64"]), content)
                    with Community(base/"community-replica", community_policy, community_public, community_key) as replica:
                        # Admission validates the complete signed file manifest.
                        # Persist the actually fetched ciphertext before the event.
                        replica.put_blob(base64.b64decode(result["data_base64"]), content_digest)
                        replica.admit([sealed_event])
                        self.assertEqual(replica.get_file(manifest), b"Community survives native node loss")
                    for role in ('client','agent','broker'): registry.stop(names[role])
                    for role in names: registry.run(names[role])
                    learned = fetch_records(client,fixture.identity,discovery_digest)
                    self.assertEqual(learned,[record])
                    self.assertEqual(discovery_directory.ingest(learned),0)
                    if profile['benchmarkAlias'] in {'go','nim'}:
                        for role in ('client','agent','broker'): registry.stop(names[role])
                        for role in names: registry.run(names[role])
                        from ziokt.native_peer import connect_native
                        carrier = {'kind':'shadow6-stream','shadow6_root':str(S),'registry_path':str(base/'services.json'),
                            'service_name':names['client'],'lock_digest':binding['lock_digest'],
                            'sdk_digest':'sha256:'+hashlib.sha256((S/'libshadow6/__init__.py').read_bytes()).hexdigest()}
                        stream = connect_native('127.0.0.1',ready['port'],carrier)
                        try:
                            channel = CoriumDataChannel(stream.handle,ready_key.read_bytes(),native_key,fixture.identity,'default','private')
                            channel.frames.socket = stream
                            self.assertEqual(channel.call('PING')['data'],'PONG:'+fixture.identity)
                        finally: stream.close()
                finally:
                    for role in ("client", "agent", "broker"):
                        try: registry.stop(names[role])
                        except (OSError, ValueError): pass

    @staticmethod
    def stop_server(server):
        import signal
        if server.poll() is None:
            os.killpg(server.pid, signal.SIGTERM)
            try: server.wait(5)
            except subprocess.TimeoutExpired: os.killpg(server.pid, signal.SIGKILL); server.wait()
        for stream in (server.stdout, server.stderr):
            stream.close()

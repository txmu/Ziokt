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
        content = b"Ziokt native dual-direction content"
        content_digest = "sha256:"+hashlib.sha256(content).hexdigest()
        client = NativeClient("test", {"native_project": "corium", "provider_id": "corium-local", "root": str(C),
            "native_config": str(config), "state_root": str(fixture.root), "network_id": "default",
            "entrypoint_digest": fingerprint(C/"corix_v108.sh")})
        prepared = client.call("operation.prepare", {"operation_id": "network-content", "action": "artifact.stage",
            "resource": content_digest, "arguments": {"data_base64": base64.b64encode(content).decode()}, "expected_revision": None})
        client.call("operation.commit", {"operation_id": "network-content", "plan_digest": prepared["plan_digest"]})
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

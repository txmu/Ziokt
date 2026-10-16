import importlib.util
from pathlib import Path
import time
import unittest

PATH = Path(__file__).resolve().parents[1] / "spec/provider_runtime.py"
spec = importlib.util.spec_from_file_location("reference", PATH)
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


def request(method="capabilities.get", **changes):
    value = {"protocol": "zfcp/1", "request_id": "request-1", "federation_id": "test",
             "provider_id": "native", "method": method, "params": {},
             "deadline_ms": time.time_ns() // 1_000_000 + 20_000, "nonce": "a" * 32}
    return {**value, **changes}


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.config = runtime.validate_config({"schema": "ziokt.provider.v1", "enabled": True,
                                              "federation_id": "test", "provider_id": "native"})

    def test_capabilities_match_native_service_binding_support(self):
        from ziokt import _runtime as integrated
        for provider,expected in [('corium',False),('shadow6',True)]:
            methods={c['operation'] for c in integrated.capabilities(provider,self.config)['capabilities']}
            self.assertEqual('service.binding' in methods,expected)

    def test_reject_duplicate_keys_floats_depth_and_noncanonical_text(self):
        for raw in (b'{"a":1,"a":2}', b'{"a":1.5}', b'{"a":NaN}',
                    b'{"a":9007199254740992}', b'[' * 18 + b']' * 18,
                    b'{"a":"\\u0000"}', b'{"a":"e\\u0301"}', b'{"a":"\\ud800"}', b'\xff'):
            with self.subTest(raw=raw), self.assertRaises(runtime.ProtocolError):
                runtime.strict_json(raw)

    def test_exact_scope_schema_deadline_and_nonce(self):
        for changes in ({"protocol": "zfcp/2"}, {"extra": True}, {"provider_id": "other"},
                        {"federation_id": "other"}, {"nonce": "bad"},
                        {"deadline_ms": True}, {"deadline_ms": 0},
                        {"deadline_ms": time.time_ns() // 1_000_000 + 90_000}):
            with self.subTest(changes=changes), self.assertRaises(runtime.ProtocolError):
                runtime.validate_request(request(**changes), self.config)

    def test_mutations_and_untyped_query_rejected(self):
        for value in (request("operation.commit"), request(params={"command": "echo"}),
                      request("objects.list", params={"kind": []}),
                      request("objects.list", params={"limit": True}),
                      request("objects.list", params={"limit": 101}),
                      request("objects.list", params={"cursor": {}})):
            with self.subTest(value=value), self.assertRaises(runtime.ProtocolError):
                runtime.validate_request(value, self.config)

    def test_native_signature_rejects_untyped_or_oversized_inputs(self):
        from ziokt import _runtime as native
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import serialization
        private=ec.generate_private_key(ec.SECP256K1())
        public=private.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        signature=native.native_ec_sign(private,b'scoped message')
        native.native_ec_verify(public,signature,b'scoped message')
        for key,sig,message in [(None,signature,b'scoped message'),([],signature,b'x'),(public,{},b'x'),(public,'0'*258,b'x'),('x'*4097,signature,b'x'),(public,signature,'not bytes'),(public,signature,b'tampered')]:
            with self.subTest(key=type(key).__name__,signature=type(sig).__name__), self.assertRaises(native.ProtocolError) as raised:
                native.native_ec_verify(key,sig,message)
            self.assertEqual(raised.exception.code,'NATIVE_SIGNATURE_REJECTED')

    def test_disabled_provider_does_not_admit_requests(self):
        self.config["enabled"] = False
        with self.assertRaises(runtime.ProtocolError) as raised:
            runtime.validate_request(request(), self.config)
        self.assertEqual(raised.exception.code, "ZIOKT_DISABLED")

    def test_configuration_cannot_enable_unimplemented_mutations(self):
        for change in ({"enabled": "TRUE"}, {"allow_mutations": True}, {"unknown": 0}):
            with self.assertRaises(runtime.ProtocolError):
                runtime.validate_config({**self.config, **change})

    def test_cursor_detects_changed_inventory(self):
        records = [{"kind": "service", "object_id": str(i)} for i in range(3)]
        first = runtime.page(records, {"limit": 1})
        second = runtime.page(records, {"limit": 1, "cursor": first["next_cursor"]})
        self.assertEqual(second["objects"][0]["object_id"], "1")
        with self.assertRaises(runtime.ProtocolError) as raised:
            runtime.page(records + [{"kind": "service", "object_id": "new"}],
                         {"cursor": first["next_cursor"]})
        self.assertEqual(raised.exception.code, "STALE_CURSOR")


if __name__ == "__main__":
    unittest.main()

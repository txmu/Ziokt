"""Corium's optional outbound transport selector, independent of Core family."""


def native_transport_main(args):
    root, network, peer, message_type, payload = Path(args[0]).absolute(), args[1], args[2], args[3], args[4]
    config = load_config("corium", root/"etc/corix/networks"/network/"corix.conf")
    if not config["enabled"] or "transport_bindings_file" not in config:
        return 80
    value = strict_json(secure_read(config["transport_bindings_file"]))
    if not isinstance(value, dict) or set(value) != {"schema", "network_id", "bindings"} or value["schema"] != "ziokt.transport-bindings.v1" or value["network_id"] != network or not isinstance(value["bindings"], list) or len(value["bindings"]) > 64:
        fail("INVALID_CONFIG", "exact scoped native transport bindings required")
    bindings = [b for b in value["bindings"] if isinstance(b, dict) and b.get("peer_id") == peer]
    if not bindings:
        return 80
    if len(bindings) != 1:
        fail("INVALID_CONFIG", "duplicate native peer transport binding")
    binding = bindings[0]
    required = {"peer_id", "shadow6_root", "service_name", "registry_path", "lock_digest", "key_file", "mode", "allow_native_fallback"}
    if not required <= set(binding) or set(binding)-required-{"privacy_profile"} or binding["mode"] not in {"required", "preferred"} or type(binding["allow_native_fallback"]) is not bool:
        fail("INVALID_CONFIG", "exact reviewed native service binding required")
    privacy = binding.get("privacy_profile", "standard")
    if not isinstance(privacy, str) or privacy not in {"standard", "private", "restricted"}:
        fail("INVALID_CONFIG", "explicit native privacy profile required")
    if privacy == "restricted": fail("NO_POLICY_COMPLIANT_PATH", "verified anonymous carrier evidence required")
    if privacy == "private" and binding["allow_native_fallback"]:
        fail("POLICY_DENIED", "private binding requires policy evidence before another path can be approved")
    for field in ("shadow6_root", "registry_path", "key_file"):
        if not isinstance(binding[field], str) or not Path(binding[field]).is_absolute() or ".." in Path(binding[field]).parts:
            fail("INVALID_CONFIG", "fixed private transport material paths required")
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", str(binding["lock_digest"])):
        fail("INVALID_CONFIG", "native deployment lock digest required")
    shadow = Path(binding["shadow6_root"])
    sys.path[:0] = [str(shadow), str(shadow/"Deployment"), str(shadow/"Crosed")]
    from Deployment.service_registry import ServiceRegistry
    from Deployment.core_catalog import CoreCatalog
    from libshadow6 import Shadow6, RegistryControl
    from cryptography.hazmat.primitives import serialization
    registry = ServiceRegistry(binding["registry_path"], CoreCatalog(shadow))
    private = serialization.load_pem_private_key(secure_read(root/"etc/corix/networks"/network/"identity.key"), password=None)
    try:
        with Shadow6(control=RegistryControl(registry)) as sdk:
            item = registry.services.get(binding["service_name"], {})
            if (item.get("deploymentLock") or {}).get("digest") != binding["lock_digest"]:
                fail("STALE_PLAN", "native service lock drifted; explicit review required")
            # No Core selection, native-wire decoding, or guarantee promotion.
            with sdk.connect_handle(binding["service_name"], timeout=10) as handle:
                if handle.describe().get("lockDigest") != binding["lock_digest"]:
                    fail("STALE_PLAN", "opened native attachment differs from reviewed deployment lock")
                result = CoriumDataChannel(handle, secure_read(binding["key_file"], 32), private, peer, network, privacy).call(message_type, payload)
        if result.get("status") != "success":
            fail("NATIVE_REQUEST_REJECTED", "native Corium peer rejected the request")
        response = result["data"] if "data" in result else result
        print(response if isinstance(response, str) else encoded(response).decode())
        return 0
    except Exception as exc:
        retryable = isinstance(exc, (OSError, TimeoutError)) or getattr(exc, "code", "") in {"DATA_TIMEOUT", "DATA_CLOSED", "DATA_RETRY_EXHAUSTED", "ApplicationReadinessTimeout", "ControlCenterUnavailable", "ConnectionTimedOut", "ConnectionRefused", "PeerUnavailable"}
        if binding["mode"] == "preferred" and binding["allow_native_fallback"] and retryable:
            return 80
        if isinstance(exc, ProtocolError): raise
        fail("NATIVE_TRANSPORT_UNAVAILABLE", "native application boundary unavailable; direct fallback denied")

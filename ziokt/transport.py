"""Every Native Core is consumed through the same application contract."""
from .protocol import ProtocolError


class NativeTransport:
    def __init__(self, sdk):
        # An operator-provisioned libshadow6 facade. No family selection or
        # hidden path creation takes place in application networking.
        self.sdk = sdk

    def open(self, service, *, kind=None, reliable=None, ordered=None,
             timeout=10, cancellation=None):
        requirements = {}
        if kind is not None:
            if kind not in {"stream", "message"}:
                raise ProtocolError("INVALID_BOUNDARY", "stream or message contract required")
            requirements["kind"] = kind
        for name, value in (("reliable", reliable), ("ordered", ordered)):
            if value is not None:
                if type(value) is not bool:
                    raise ProtocolError("INVALID_BOUNDARY", "explicit boolean transport guarantee required")
                requirements[name] = value
        return self.sdk.connect_handle(service, timeout=timeout, cancellation=cancellation,
                                       require=requirements or None)


def native_profile_matrix(shadow6_root):
    """Source contracts for all Profiles; never called runtime verification."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(shadow6_root) / "Crosed"))
    from native_profiles import profiles
    return [{"core": p["core"], "profile": p["id"], "boundary": p["applicationBoundary"],
             "native_transport":p['nativeTransport'], "resource_limits":p['limits'],
             "platform_requirements":p['requirements'], "shutdown":p['shutdown'],
             "observation": "source-contract", "runtime_verified": False} for p in profiles()]


def plan_profiles(shadow6_root, purpose):
    """Review all source contracts; deployment still verifies each chosen path."""
    if purpose not in {'proxy-stream', 'discovery', 'content'}:
        raise ProtocolError('INVALID_BOUNDARY', 'explicit native application purpose required')
    rows = native_profile_matrix(shadow6_root)
    for row in rows:
        boundary = row['boundary']
        stream = boundary['kind'] == 'stream' and boundary.get('reliable') is True and boundary.get('ordered') is True
        row.update({'purpose':purpose, 'eligible':purpose != 'proxy-stream' or stream,
            'application_adapter':'nested-mtls' if purpose == 'proxy-stream' else 'corium-signed-bounded-records',
            'requires_reviewed_lock':True, 'implicit_family_translation':False,
            'fragment_limit':boundary.get('max_record') if boundary['kind'] == 'message' else None})
    return rows

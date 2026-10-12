"""ZFCP/1 opt-in native profile. Vendored in S and embedded in C.

No Ziokt installation is needed by either native provider. Local owner authority
gates fixed journaled operations; remote grants belong to the separate mTLS API.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import time
import unicodedata

PROTOCOL = "zfcp/1"
MAX_REQUEST = 65_536
MAX_RESPONSE = 262_144
MAX_CONFIG = 262_144
MAX_OBJECTS = 4096
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
METHODS = ("capabilities.get", "status.get", "objects.list", "operation.prepare",
           "operation.commit", "operation.abort", "operation.status", "operation.reconcile", "events.list", "content.get", "governance.fact", "zkt.status", "zkt.account")


class ProtocolError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def fail(code, message):
    raise ProtocolError(code, message)


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def windows_file_info(handle):
    """Retrieve NTFS file information via OS handle to verify volume and inode identity."""
    import ctypes
    from ctypes import wintypes
    class BY_HANDLE_FILE_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("dwFileAttributes", wintypes.DWORD),
            ("ftCreationTime", wintypes.FILETIME),
            ("ftLastAccessTime", wintypes.FILETIME),
            ("ftLastWriteTime", wintypes.FILETIME),
            ("dwVolumeSerialNumber", wintypes.DWORD),
            ("nFileSizeHigh", wintypes.DWORD),
            ("nFileSizeLow", wintypes.DWORD),
            ("nNumberOfLinks", wintypes.DWORD),
            ("nFileIndexHigh", wintypes.DWORD),
            ("nFileIndexLow", wintypes.DWORD),
        ]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.POINTER(BY_HANDLE_FILE_INFORMATION)]
    kernel.GetFileInformationByHandle.restype = wintypes.BOOL
    info = BY_HANDLE_FILE_INFORMATION()
    if not kernel.GetFileInformationByHandle(handle, ctypes.byref(info)):
        fail("UNSAFE_FILE", "Windows file information cannot be inspected")
    return info


def windows_owner_controlled(handle, private):
    """Validate actual NT owner/DACL; chmod bits are not an ACL on Windows."""
    import ctypes
    from ctypes import wintypes
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi.GetSecurityInfo.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    advapi.GetSecurityInfo.restype = wintypes.DWORD
    advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                         wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    advapi.EqualSid.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    advapi.GetAce.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)]
    advapi.ConvertStringSidToSidW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)]
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    owner, dacl, descriptor = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
    token, allowed = wintypes.HANDLE(), []
    try:
        if advapi.GetSecurityInfo(handle, 1, 5, ctypes.byref(owner), None, ctypes.byref(dacl), None, ctypes.byref(descriptor)):
            fail("UNSAFE_FILE", "Windows file security cannot be inspected")
        if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 8, ctypes.byref(token)):
            fail("UNSAFE_FILE", "Windows owner token unavailable")
        size = wintypes.DWORD()
        advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
        if not 1 <= size.value <= 16384:
            fail("UNSAFE_FILE", "invalid Windows owner token")
        buffer = ctypes.create_string_buffer(size.value)
        if not advapi.GetTokenInformation(token, 1, buffer, size, ctypes.byref(size)):
            fail("UNSAFE_FILE", "Windows owner token unavailable")
        current = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
        for name in ("S-1-5-18", "S-1-5-32-544"):
            sid = ctypes.c_void_p()
            if not advapi.ConvertStringSidToSidW(name, ctypes.byref(sid)):
                fail("UNSAFE_FILE", "Windows trusted SID unavailable")
            allowed.append(sid)
        if not owner or not any(advapi.EqualSid(owner, sid) for sid in (current, allowed[1])):
            fail("UNSAFE_FILE", "Windows file owner must be current user or local administrators")
        if private:
            if not dacl:
                fail("UNSAFE_FILE", "private Windows file requires a restrictive DACL")
            header = ctypes.string_at(dacl, 8)
            count = int.from_bytes(header[4:6], "little")
            if count > 128:
                fail("UNSAFE_FILE", "Windows ACL exceeds budget")
            for index in range(count):
                ace = ctypes.c_void_p()
                if not advapi.GetAce(dacl, index, ctypes.byref(ace)):
                    fail("UNSAFE_FILE", "Windows ACL cannot be read")
                raw = ctypes.string_at(ace, 8)
                if raw[1] & 8:  # INHERIT_ONLY_ACE does not grant this object access.
                    continue
                if raw[0] == 1:  # ACCESS_DENIED_ACE
                    continue
                if raw[0] != 0 or int.from_bytes(raw[2:4], "little") < 12:
                    fail("UNSAFE_FILE", "unsupported Windows permission entry")
                sid = ctypes.c_void_p(ace.value + 8)
                if not any(advapi.EqualSid(sid, trusted) for trusted in (current, *allowed)):
                    fail("UNSAFE_FILE", "private Windows file grants access to another identity")
    finally:
        if token:
            kernel.CloseHandle(token)
        if descriptor:
            kernel.LocalFree(descriptor)
        for sid in allowed:
            kernel.LocalFree(sid)


def make_private(path):
    """Restrict a newly created Ziokt object, including a real Windows DACL."""
    path = Path(path)
    if os.name != "nt":
        path.chmod(0o700 if path.is_dir() else 0o600)
        return
    import ctypes
    from ctypes import wintypes
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                  wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    advapi.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    advapi.GetSecurityDescriptorDacl.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.BOOL), ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.BOOL)]
    advapi.SetSecurityInfo.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    advapi.SetSecurityInfo.restype = wintypes.DWORD
    token, descriptor, text = wintypes.HANDLE(), ctypes.c_void_p(), ctypes.c_void_p()
    handle = None
    try:
        if path.is_symlink():
            fail("UNSAFE_FILE", "private object cannot be a symlink")
        # READ_CONTROL | WRITE_DAC, OPEN_EXISTING, BACKUP_SEMANTICS and
        # OPEN_REPARSE_POINT. Only this object's handle is ever modified.
        handle = kernel.CreateFileW(str(path.absolute()), 0x60000, 7, None, 3, 0x02200000, None)
        if handle in (None, ctypes.c_void_p(-1).value):
            fail("UNSAFE_FILE", "private Windows object cannot be opened")
        windows_owner_controlled(handle, False)
        if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 8, ctypes.byref(token)):
            fail("UNSAFE_FILE", "Windows private owner unavailable")
        size = wintypes.DWORD()
        advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
        if not 1 <= size.value <= 16384:
            fail("UNSAFE_FILE", "invalid Windows private owner")
        buffer = ctypes.create_string_buffer(size.value)
        if not advapi.GetTokenInformation(token, 1, buffer, size, ctypes.byref(size)):
            fail("UNSAFE_FILE", "Windows private owner unavailable")
        sid = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
        if not advapi.ConvertSidToStringSidW(sid, ctypes.byref(text)):
            fail("UNSAFE_FILE", "Windows private SID unavailable")
        current = ctypes.wstring_at(text)
        inheritance = "OICI" if path.is_dir() else ""
        sddl = "D:P" + "".join("(A;" + inheritance + ";FA;;;" + identity + ")" for identity in ("SY", "BA", current))
        if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(descriptor), None):
            fail("UNSAFE_FILE", "private Windows DACL invalid")
        present, defaulted, dacl = wintypes.BOOL(), wintypes.BOOL(), ctypes.c_void_p()
        if not advapi.GetSecurityDescriptorDacl(descriptor, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted)) or not present:
            fail("UNSAFE_FILE", "private Windows DACL missing")
        if advapi.SetSecurityInfo(handle, 1, 4 | 0x80000000, None, None, dacl, None):
            fail("UNSAFE_FILE", "private Windows DACL could not be applied")
        windows_owner_controlled(handle, True)
    finally:
        if handle not in (None, ctypes.c_void_p(-1).value): kernel.CloseHandle(handle)
        if token: kernel.CloseHandle(token)
        if descriptor: kernel.LocalFree(descriptor)
        if text: kernel.LocalFree(text)


def strict_json(raw, limit=MAX_REQUEST, string_limit=8192):
    if not isinstance(raw, bytes) or len(raw) > limit:
        fail("INVALID_JSON", "JSON size limit")
    try:
        text = raw.decode("utf-8", "strict")
        depth, quoted, escaped = 0, False, False
        for char in text:
            if quoted:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    quoted = False
            elif char == '"':
                quoted = True
            elif char in "[{":
                depth += 1
                if depth > 16:
                    raise ValueError("nesting")
            elif char in "]}":
                depth -= 1

        def pairs(items):
            result = {}
            for key, child in items:
                if key in result:
                    raise ValueError("duplicate key")
                result[key] = child
            return result

        def reject(_):
            raise ValueError("noninteger number")

        value = json.loads(text, object_pairs_hook=pairs,
                           parse_float=reject, parse_constant=reject)

        def bounded(item, level=0):
            if level > 16:
                raise ValueError("nesting")
            if type(item) is int and not -(2**53 - 1) <= item <= 2**53 - 1:
                raise ValueError("integer range")
            if isinstance(item, str):
                if (len(item.encode("utf-8")) > string_limit or "\0" in item or
                        unicodedata.normalize("NFC", item) != item):
                    raise ValueError("string")
            if isinstance(item, dict):
                for key, child in item.items():
                    bounded(key, level + 1)
                    bounded(child, level + 1)
            elif isinstance(item, list):
                for child in item:
                    bounded(child, level + 1)
        bounded(value)
        return value
    except (ValueError, UnicodeError, RecursionError):
        fail("INVALID_JSON", "strict bounded UTF-8 JSON required")


def secure_read(path, limit=MAX_CONFIG, private=True):
    """Stable regular-file reads, never symlinks, FIFOs or unsafe modes."""
    path = Path(path)
    before = path.lstat()
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    try:
        opened = os.fstat(fd)

        def identity(s):
            if os.name == "nt":
                return (s.st_mode, s.st_size)
            return (s.st_dev, s.st_ino, s.st_mode, s.st_uid, s.st_nlink,
                    s.st_size, s.st_mtime_ns, s.st_ctime_ns)

        if os.name == "nt":
            import msvcrt
            handle = msvcrt.get_osfhandle(fd)
            windows_owner_controlled(handle, private is True)
            info = windows_file_info(handle)
            if (info.dwVolumeSerialNumber != before.st_dev
                    or ((info.nFileIndexHigh << 32) | info.nFileIndexLow) != before.st_ino
                    or info.nNumberOfLinks != 1):
                fail("UNSAFE_FILE", "stable owner-controlled regular file required")
        if (not stat.S_ISREG(opened.st_mode) or (os.name != "nt" and opened.st_uid != os.geteuid())
                or (os.name != "nt" and opened.st_nlink != 1) or opened.st_size > limit
                or (os.name != "nt" and private and stat.S_IMODE(opened.st_mode) != 0o600)
                or (os.name != "nt" and private is False and opened.st_mode & 0o022)
                or identity(before) != identity(opened)
                or (os.name != "nt" and identity(path.lstat()) != identity(opened))
                or (before.st_dev, before.st_ino, before.st_size) != (path.lstat().st_dev, path.lstat().st_ino, path.lstat().st_size)):
            fail("UNSAFE_FILE", "stable owner-controlled regular file required")
        data = bytearray()
        while len(data) <= limit:
            chunk = os.read(fd, min(65536, limit + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        if (len(data) != opened.st_size or len(data) > limit
                or identity(opened) != identity(os.fstat(fd))
                or (os.name != "nt" and identity(opened) != identity(path.lstat()))
                or (before.st_dev, before.st_ino, before.st_size) != (path.lstat().st_dev, path.lstat().st_ino, path.lstat().st_size)):
            fail("UNSAFE_FILE", "file changed during read")
        return bytes(data)
    finally:
        os.close(fd)


def validate_config(value):
    allowed = {"schema", "enabled", "federation_id", "provider_id", "allow_mutations",
               "allowed_operations", "allowed_resources", "package_root", "package_trust_file", "artifact_root", "transport_bindings_file", "coordinator_public_key"}
    if (not isinstance(value, dict) or set(value) - allowed or
            value.get("schema") != "ziokt.provider.v1" or
            type(value.get("enabled", False)) is not bool or
            type(value.get("allow_mutations", False)) is not bool):
        fail("INVALID_CONFIG", "invalid provider configuration")
    result = {"schema": "ziokt.provider.v1", "enabled": False,
              "federation_id": None, "provider_id": None,
              "allow_mutations": False, "allowed_operations": [], "allowed_resources": [], **value}
    for name in ("federation_id", "provider_id"):
        field = result[name]
        if field is not None and (not isinstance(field, str) or not ID.fullmatch(field)):
            fail("INVALID_CONFIG", "invalid provider scope")
        if result["enabled"] and field is None:
            fail("INVALID_CONFIG", "enabled provider requires explicit scope")
    for field in ("allowed_operations", "allowed_resources"):
        values = result[field]
        if (not isinstance(values, list) or len(values) > 64 or
                any(not isinstance(v, str) or not 1 <= len(v) <= 160 for v in values) or len(set(values)) != len(values)):
            fail("INVALID_CONFIG", "bounded explicit native action/resource allowlists required")
    known_operations = {"service.stop", "service.run", "artifact.stage", "package.install", "package.activate",
                        "wiki.create", "snapshot.create", "strata.create", "chain.mine", "recovery.checkpoint", "recovery.restore"}
    if any(v not in known_operations for v in result["allowed_operations"]):
        fail("INVALID_CONFIG", "unknown native action")
    if "coordinator_public_key" in result and (not isinstance(result["coordinator_public_key"], str) or not re.fullmatch("[a-f0-9]{64}", result["coordinator_public_key"])):
        fail("INVALID_CONFIG", "pinned Ed25519 coordinator authority required")
    for name in ("package_root", "package_trust_file", "artifact_root", "transport_bindings_file"):
        if name in result and (not isinstance(result[name], str) or not Path(result[name]).is_absolute() or ".." in Path(result[name]).parts):
            fail("INVALID_CONFIG", "native package settings require fixed absolute paths")
    if result["allow_mutations"] and (not result["enabled"] or not result["allowed_operations"] or not result["allowed_resources"]):
        fail("INVALID_CONFIG", "mutations require enabled support and explicit action/resource allowlists")
    return result


def load_config(provider, path):
    if path is None:
        return validate_config({"schema": "ziokt.provider.v1"})
    try:
        raw = secure_read(path)
    except FileNotFoundError:
        # An explicitly selected missing configuration is an error.
        fail("INVALID_CONFIG", "selected provider configuration is missing")
    if provider == "shadow6":
        return validate_config(strict_json(raw, MAX_CONFIG))
    try:
        text = raw.decode("utf-8", "strict")
        fields, inside, seen = {}, False, False
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith(("#", ";")):
                continue
            if line.startswith("["):
                if not line.endswith("]"):
                    if inside:
                        raise ValueError("section")
                    continue
                inside = line[1:-1].strip() == "ziokt"
                if inside:
                    if seen:
                        raise ValueError("duplicate section")
                    seen = True
                continue
            if inside:
                key, sep, value = line.partition("=")
                key, value = key.strip(), value.strip()
                if not sep or key in fields or key not in {
                        "enabled", "federation_id", "provider_id", "allow_mutations", "allowed_operations", "allowed_resources",
                        "package_root", "package_trust_file", "artifact_root", "transport_bindings_file", "coordinator_public_key"}:
                    raise ValueError("field")
                if key in {"enabled", "allow_mutations"}:
                    if value not in {"TRUE", "FALSE"}:
                        raise ValueError("boolean")
                    value = value == "TRUE"
                elif key in {"allowed_operations", "allowed_resources"}:
                    value = [part.strip() for part in value.split(",") if part.strip()]
                fields[key] = value
        return validate_config({"schema": "ziokt.provider.v1", **fields})
    except (ValueError, UnicodeError):
        fail("INVALID_CONFIG", "strict [ziokt] configuration required")


def identifier(value, label):
    if not isinstance(value, str) or not ID.fullmatch(value):
        fail("INVALID_REQUEST", "invalid " + label)


def validate_request(value, config):
    fields = {"protocol", "request_id", "federation_id", "provider_id",
              "method", "params", "deadline_ms", "nonce"}
    if not isinstance(value, dict) or set(value) != fields or value["protocol"] != PROTOCOL:
        fail("INVALID_REQUEST", "exact ZFCP/1 request required")
    for field in ("request_id", "federation_id", "provider_id"):
        identifier(value[field], field)
    if not isinstance(value["nonce"], str) or not re.fullmatch(r"[0-9a-f]{32}", value["nonce"]):
        fail("INVALID_REQUEST", "invalid nonce")
    now = time.time_ns() // 1_000_000
    if type(value["deadline_ms"]) is not int or not now < value["deadline_ms"] <= now + 30_000:
        fail("DEADLINE_EXCEEDED", "deadline must be within 30 seconds")
    if (not isinstance(value["method"], str) or not isinstance(value["params"], dict)):
        fail("INVALID_REQUEST", "typed method and params required")
    if not config["enabled"]:
        fail("ZIOKT_DISABLED", "native Ziokt support is disabled")
    if any(value[k] != config[k] for k in ("federation_id", "provider_id")):
        fail("SCOPE_MISMATCH", "provider scope does not match")
    if value["method"] not in METHODS:
        fail("METHOD_UNSUPPORTED", "operation not available in this native profile")
    params = value["params"]
    method = value["method"]
    if method == "governance.fact":
        if set(params) != {"transaction_hash"} or not isinstance(params["transaction_hash"], str) or not re.fullmatch("[a-f0-9]{64}", params["transaction_hash"]):
            fail("INVALID_PARAMS", "exact native signed transaction reference required")
    elif method == "content.get":
        if (not {"peer_id", "digest"} <= set(params) or set(params)-{"peer_id", "digest", "offset", "length"} or
                not isinstance(params["peer_id"], str) or not re.fullmatch("[a-f0-9]{64}", params["peer_id"]) or
                not isinstance(params["digest"], str) or not re.fullmatch("sha256:[a-f0-9]{64}", params["digest"]) or
                type(params.get("offset", 0)) is not int or not 0 <= params.get("offset", 0) <= 64*1024*1024 or
                type(params.get("length", 6144)) is not int or not 1 <= params.get("length", 6144) <= 6144):
            fail("INVALID_PARAMS", "fixed native peer and bounded content range required")
    elif method in {"zkt.status", "zkt.account"}:
        if set(params) != (set() if method == "zkt.status" else {"address"}):
            fail("INVALID_PARAMS", "exact native reputation query required")
        if method == "zkt.account" and (not isinstance(params["address"], str) or not re.fullmatch(r"[a-f0-9]{64}", params["address"])):
            fail("INVALID_PARAMS", "native account identity required")
    elif method.startswith("operation."):
        expected = ({"operation_id", "action", "resource", "arguments", "expected_revision"}
                    if method == "operation.prepare" else
                    {"operation_id", "plan_digest"} if method in {"operation.commit", "operation.abort"} else {"operation_id"})
        optional = {"lease_ms", "fence"} if method == "operation.prepare" else set()
        if not expected <= set(params) or set(params) - expected - optional:
            fail("INVALID_PARAMS", "exact native operation parameters required")
        if "lease_ms" in params and (type(params["lease_ms"]) is not int or not 250 <= params["lease_ms"] <= 30000):
            fail("INVALID_PARAMS", "native prepare lease must be 250..30000 ms")
        identifier(params.get("operation_id"), "operation_id")
        if method == "operation.prepare" and (not isinstance(params["action"], str) or not isinstance(params["resource"], str) or not isinstance(params["arguments"], dict)):
            fail("INVALID_PARAMS", "typed native operation required")
    elif method == "events.list":
        if (set(params) - {"after_seq", "limit"} or type(params.get("after_seq", 0)) is not int or params.get("after_seq", 0) < 0 or
                type(params.get("limit", 50)) is not int or not 1 <= params.get("limit", 50) <= 100):
            fail("INVALID_PARAMS", "bounded event cursor required")
    elif method != "objects.list":
        if params:
            fail("INVALID_PARAMS", "empty params required")
    else:
        if set(params) - {"kind", "limit", "cursor"}:
            fail("INVALID_PARAMS", "unknown object query field")
        if (type(params.get("limit", 50)) is not int or
                not 1 <= params.get("limit", 50) <= 100):
            fail("INVALID_PARAMS", "page size must be 1..100")
        if (not isinstance(params.get("kind", "all"), str) or
                params.get("kind", "all") not in {"all", "service", "package", "environment", "application", "identity", "proposal", "recovery", "name"}):
            fail("INVALID_PARAMS", "unsupported object kind")
        if "cursor" in params and (not isinstance(params["cursor"], str) or
                not re.fullmatch(r"[0-9a-f]{64}:[0-9]{1,5}", params["cursor"])):
            fail("INVALID_PARAMS", "invalid snapshot cursor")
    return value


def safe_directory(path):
    """Read inventory only through non-symlink owner-controlled directories."""
    path = Path(path).absolute()
    for candidate in reversed((path, *path.parents)):
        info = candidate.lstat()
        if not stat.S_ISDIR(info.st_mode):
            fail("UNSAFE_FILE", "inventory directory must not be a symlink")
        if candidate == path and os.name != "nt" and (info.st_uid != os.geteuid() or info.st_mode & 0o022):
            fail("UNSAFE_FILE", "inventory directory must be owner-controlled")
    return path


def object_record(config, kind, native_id, state, properties):
    strict_json(encoded(properties), MAX_RESPONSE)
    if not isinstance(native_id, str) or len(native_id.encode()) > 512:
        fail("INVALID_NATIVE_STATE", "invalid native object identity")
    key = hashlib.sha256((kind + "\0" + native_id).encode()).hexdigest()
    record = {"object_id": "ziokt://{}/{}/{}/{}".format(
        config["federation_id"], config["provider_id"], kind, key),
        "owner_provider": config["provider_id"], "kind": kind,
        "native_id": native_id, "state": state,
        "observation": "stored-metadata", "properties": properties}
    record["revision"] = "sha256:" + digest(record)
    return record


def native_objects(provider, root, network, config):
    records = []
    if provider == "shadow6":
        # Reuse the native validator, but do not call @transaction list/status:
        # those methods create lock files and can migrate stored state.
        sys.dont_write_bytecode = True
        sys.path.insert(0, str(root / "Deployment"))
        from service_registry import ServiceRegistry
        from core_catalog import CoreCatalog
        registry = ServiceRegistry(catalog=CoreCatalog(root))
        for name, item in registry.services.items():
            binding, profile = item.get("coreBinding") or {}, item.get("profileBinding") or {}
            lock = item.get("deploymentLock") or {}
            record = object_record(config, "service", name, item["state"], {
                "core": binding.get("core"), "core_version": binding.get("version"),
                "profile": profile.get("profile"), "lock_digest": lock.get("digest")})
            from service_registry import digest as native_digest, encoded as native_encode
            record["revision"] = native_digest(native_encode(item))
            records.append(record)
        if "package_root" in config and Path(config["package_root"]).exists():
            sys.path.insert(0, str(root/"Package-Manager"))
            from shadow6_pkg import list_packages, verify_package
            safe_directory(config["package_root"])
            packages = list_packages(Path(config["package_root"]))
            if len(packages) > MAX_OBJECTS: fail("INVENTORY_LIMIT", "native package inventory exceeds budget")
            for item in packages:
                selector = item["kind"]+"/"+item["id"]+"@"+item["version"]
                properties = {**item, "native_signature_verified": False}
                if "package_trust_file" in config:
                    source = Path(config["package_root"])/item["kind"]/item["id"]/"versions"/item["version"]
                    manifest, package = verify_package(source, Path(config["package_trust_file"]))
                    package.close(); properties["native_signature_verified"] = True
                    properties["manifest_digest"] = "sha256:"+digest(manifest)
                records.append(object_record(config, "package", selector, "active" if item["active"] else "installed", properties))
                if item["kind"] == "app":
                    records.append(object_record(config, "application", selector, "active" if item["active"] else "installed", properties))
    else:
        suffix = "networks/" + network
        directories = (("package", root / "var/lib/corix" / suffix / "installed"),
                       ("environment", root / "usr/corix/strata" / suffix),
                       ("recovery", root / "var/lib/corix" / suffix / "snapshots"))
        for kind, path in directories:
            try:
                safe_directory(path)
            except FileNotFoundError:
                continue
            with os.scandir(path) as entries:
                count = 0
                for entry in entries:
                    count += 1
                    if count > MAX_OBJECTS:
                        fail("INVENTORY_LIMIT", "native inventory exceeds snapshot budget")
                    if not entry.is_dir(follow_symlinks=False):
                        continue
                    directory = safe_directory(entry.path)
                    if kind == "package":
                        try:
                            fields = {key: secure_read(directory / key, 512, False).decode("utf-8").strip()
                                      for key in ("name", "slot", "version")}
                        except FileNotFoundError:
                            continue
                        if not all(fields.values()):
                            fail("INVALID_NATIVE_STATE", "incomplete package identity")
                        native_id = fields["name"] + ":" + fields["slot"]
                        state = "registered"
                    else:
                        native_id, fields, state = entry.name, {"network_id": network}, "present"
                    records.append(object_record(config, kind, native_id, state, fields))
        # Project fixed public metadata from the original native databases.
        # Message bodies, ACL members, keys and peer addresses stay native.
        queries = (("forum/forum.db", "identity", "SELECT id_hash,type,last_updated_height FROM identity_cache", ("native_type", "height")),
                   ("forum/forum.db", "application", "SELECT group_id || '/' || slug,latest_version_hash,locked_by_user_id IS NOT NULL FROM wiki_pages", ("version_hash", "locked")),
                   ("forum/forum.db", "application", "SELECT 'forum/' || tx_hash,source_type,encryption_mode FROM messages", ("native_type", "encryption_mode")),
                   ("forum/forum.db", "application", "SELECT 'mail/' || tx_hash,mail_object_hash,timestamp FROM mails", ("content_digest", "timestamp")),
                   ("blockchain/chain.db", "application", "SELECT 'template/' || template_name,package_hash,activation_height FROM active_app_templates", ("package_hash", "height")),
                   ("forum/forum.db", "name", "SELECT domain_name,target_hash,last_update_height FROM nns_records", ("target_hash", "height")),
                   ("blockchain/chain.db", "proposal", "SELECT hash,type,block_height FROM transactions WHERE type LIKE '%proposal%'", ("native_type", "height")))
        from contextlib import closing
        for filename, kind, query, columns in queries:
            path = root/"var/lib/corix"/suffix/filename
            if not path.exists(): continue
            with closing(native_database(path)) as db:
                rows = db.execute(query+" LIMIT ?", (MAX_OBJECTS+1,)).fetchall()
            if len(rows) > MAX_OBJECTS: fail("INVENTORY_LIMIT", "native object projection exceeds budget")
            for row in rows:
                properties = dict(zip(columns, row[1:]))
                records.append(object_record(config, kind, row[0], "native-recorded", properties))
    if len(records) > MAX_OBJECTS:
        fail("INVENTORY_LIMIT", "native inventory exceeds snapshot budget")
    records.sort(key=lambda item: item["object_id"])
    if len({item["object_id"] for item in records}) != len(records):
        fail("INVALID_NATIVE_STATE", "duplicate native object identity")
    return records


def page(records, params):
    records = [r for r in records if params.get("kind", "all") in {"all", r["kind"]}]
    snapshot = digest(records)
    offset = 0
    if "cursor" in params:
        previous, raw_offset = params["cursor"].split(":")
        offset = int(raw_offset)
        if previous != snapshot:
            fail("STALE_CURSOR", "inventory changed; restart pagination")
        if offset > len(records):
            fail("INVALID_PARAMS", "cursor beyond snapshot")
    limit = params.get("limit", 50)
    end = offset + limit
    return {"objects": records[offset:end], "snapshot_digest": "sha256:" + snapshot,
            "next_cursor": snapshot + ":" + str(end) if end < len(records) else None,
            "total": len(records)}


def capabilities(provider, config):
    return {"schema": "ziokt.capabilities.v1", "native_project": provider,
            "enabled": config["enabled"], "provider_id": config["provider_id"],
            "federation_id": config["federation_id"], "protocol": PROTOCOL,
            "profile": "local-v1", "mutations": config["allow_mutations"],
            "capabilities": [{"id": "ziokt." + method + ".v1", "operation": method,
                              "status": "available" if config["enabled"] and (method not in {"operation.prepare", "operation.commit", "operation.abort", "operation.reconcile"} or config["allow_mutations"]) else "disabled"}
                              for method in METHODS if provider == "corium" or (not method.startswith("zkt.") and method not in {"content.get", "governance.fact"})],
            "native_actions": sorted(OPERATIONS[provider]),
            "object_kinds": ["service", "package", "application"] if provider == "shadow6" else ["package", "environment", "application", "identity", "name", "proposal", "recovery"],
            "transport": "native-application-boundary; one Core family per path" if provider == "shadow6" else "native-signature-preserving Ziokt binding; explicit fallback"}


def status(provider, config, network):
    return {"schema": "ziokt.provider-status.v1", "native_project": provider,
            "enabled": config["enabled"], "provider_id": config["provider_id"],
            "federation_id": config["federation_id"], "network_id": network,
            "mutations": config["allow_mutations"], "listeners": 0,
            "listener_scope": "local-rpc-process", "recovery": "explicit-native-operation"}


def rpc(provider, root, network, config, stream):
    request_id = None
    try:
        raw = stream.readline(MAX_REQUEST + 2)
        if not raw.endswith(b"\n") or len(raw) > MAX_REQUEST + 1:
            fail("INVALID_REQUEST", "bounded newline-terminated request required")
        if stream.read(1):
            fail("INVALID_REQUEST", "one request per process required")
        value = strict_json(raw[:-1])
        if isinstance(value, dict) and isinstance(value.get("request_id"), str) and ID.fullmatch(value["request_id"]):
            request_id = value["request_id"]
        request = validate_request(value, config)
        method = request["method"]
        if method == "capabilities.get":
            result = capabilities(provider, config)
        elif method == "status.get":
            result = status(provider, config, network)
        elif method.startswith("operation.") or method == "events.list":
            result = operation_dispatch(provider, root, network, config, method, request["params"])
        elif method == "governance.fact":
            if provider != "corium": fail("METHOD_UNSUPPORTED", "native chain facts belong to Corium")
            result = governance_fact(root, network, request["params"]["transaction_hash"])
        elif method == "content.get":
            if provider != "corium": fail("METHOD_UNSUPPORTED", "content peer ownership belongs to native Corium")
            import contextlib, io
            params = request["params"]
            query = {k:v for k,v in params.items() if k != "peer_id"}
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = native_transport_main([str(root), network, params["peer_id"], "ZIOKT_CONTENT_GET", encoded(query).decode()])
            if code != 0: fail("NO_APPROVED_BINDING", "content retrieval requires an explicit native application binding")
            result = strict_json(output.getvalue().strip().encode())
        elif method in {"zkt.status", "zkt.account"}:
            if provider != "corium":
                fail("METHOD_UNSUPPORTED", "native ZKT reputation belongs to Corium")
            result = zkt_read_status(root / "var/lib/corix/networks" / network / "blockchain/chain.db", request["params"].get("address"))
        else:
            result = page(native_objects(provider, root, network, config), request["params"])
        if time.time_ns() // 1_000_000 >= request["deadline_ms"]:
            fail("DEADLINE_EXCEEDED", "request deadline exceeded")
        response = {"protocol": PROTOCOL, "request_id": request_id, "ok": True, "result": result}
        if len(encoded(response)) > MAX_RESPONSE:
            fail("RESPONSE_LIMIT", "response exceeds page budget")
    except ProtocolError as exc:
        response = {"protocol": PROTOCOL, "request_id": request_id, "ok": False,
                    "error": {"code": exc.code, "message": str(exc)}}
    except (OSError, ValueError, ImportError, UnicodeError, sqlite3.Error, TypeError, KeyError):
        response = {"protocol": PROTOCOL, "request_id": request_id, "ok": False,
                    "error": {"code": "NATIVE_STATE_UNAVAILABLE", "message": "native inventory cannot be read safely"}}
    sys.stdout.buffer.write(encoded(response) + b"\n")
    return 0 if response["ok"] else 2


def main(provider, root=None, argv=None, rpc_stream=None):
    parser = argparse.ArgumentParser(prog=provider + " ziokt")
    parser.add_argument("--config", type=Path, help="private native provider configuration")
    if provider == "corium":
        parser.add_argument("--network", default=os.environ.get("CORIUM_NETWORK_ID_OVERRIDE", "default"))
    parser.add_argument("action", choices=("capabilities", "status", "rpc", "serve-data"))
    parser.add_argument("--stdio", action="store_true")
    parser.add_argument("--key-file", type=Path)
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args(argv)
    try:
        if args.stdio != (args.action == "rpc"):
            fail("INVALID_REQUEST", "rpc requires --stdio; other actions do not accept it")
        network = args.network if provider == "corium" else None
        if network is not None:
            identifier(network, "network")
        root = Path(root or os.environ.get("CORIUM_ROOT", "/")).absolute()
        path = args.config
        if provider == "corium" and path is not None:
            expected = root / "etc/corix/networks" / network / "corix.conf"
            if path.absolute() != expected:
                fail("INVALID_CONFIG", "Corium config must match its native root/network")
        if provider == "corium" and path is None:
            path = root / "etc/corix/networks" / network / "corix.conf"
            # Absent native config means disabled, without creating any state.
            if not path.exists() and not path.is_symlink():
                path = None
        elif provider == "shadow6" and path is None:
            path = Path.home() / ".config/shadow6/ziokt.json"
            if not path.exists() and not path.is_symlink():
                path = None
        config = load_config(provider, path)
        if args.action == "serve-data":
            if provider != "corium" or not config["enabled"]:
                fail("ZIOKT_DISABLED", "Corium native Ziokt data support must be enabled")
            if args.key_file is None or not 0 <= args.port <= 65535:
                fail("INVALID_CONFIG", "private application key and bounded loopback port required")
            serve_corium_data(root, network, args.key_file, args.port)
            return 0
        if args.action == "rpc":
            return rpc(provider, root, network, config, rpc_stream or sys.stdin.buffer)
        value = capabilities(provider, config) if args.action == "capabilities" else status(provider, config, network)
        sys.stdout.buffer.write(encoded(value) + b"\n")
        return 0
    except (ProtocolError, OSError, ValueError) as exc:
        response = {"protocol": PROTOCOL, "request_id": None, "ok": False,
                    "error": {"code": getattr(exc, "code", "INVALID_CONFIG"),
                              "message": str(exc) if isinstance(exc, ProtocolError) else "configuration cannot be read safely"}}
        sys.stdout.buffer.write(encoded(response) + b"\n")
        return 2

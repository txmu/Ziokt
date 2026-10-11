"""Common workspace intent with native ownership and evidence-based readiness."""
from .protocol import ProtocolError, identifier
from .policy import PROFILES


def review(manifest, inventory):
    fields = {"schema", "workspace_id", "federation_id", "services", "applications", "packages", "identities", "privacy", "recovery"}
    if not isinstance(manifest, dict) or set(manifest) != fields or manifest["schema"] != "ziokt.workspace.v1":
        raise ProtocolError("INVALID_WORKSPACE", "exact workspace manifest required")
    identifier(manifest["workspace_id"], "workspace_id")
    identifier(manifest["federation_id"], "federation_id")
    if not isinstance(manifest["privacy"], str) or manifest["privacy"] not in PROFILES or not isinstance(manifest["recovery"], dict):
        raise ProtocolError("INVALID_WORKSPACE", "explicit privacy and recovery intent required")
    if inventory.get("federation_id") != manifest["federation_id"]:
        raise ProtocolError("SCOPE_MISMATCH", "workspace inventory belongs to another federation")
    index = {r["object_id"]: r for r in inventory.get("objects", [])}
    resolved, missing = {}, []
    for kind in ("services", "applications", "packages", "identities"):
        refs = manifest[kind]
        if not isinstance(refs, list) or len(refs) > 64 or not all(isinstance(v, str) for v in refs):
            raise ProtocolError("INVALID_WORKSPACE", "bounded object references required")
        resolved[kind] = []
        for ref in refs:
            if ref not in index:
                missing.append(ref)
            else:
                resolved[kind].append(index[ref])
    return {"schema": "ziokt.workspace-review.v1", "workspace_id": manifest["workspace_id"],
            "resolved": resolved, "missing": missing, "materials_resolved": not missing,
            "runtime_ready": False, "privacy": manifest["privacy"], "recovery": manifest["recovery"]}
